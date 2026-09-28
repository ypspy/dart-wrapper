"""진단 후보를 검토 테이블에 맞추고 TSV로 주고받는다."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, fields

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.extracting.constants import EXTRACTOR_VERSION
from app.extracting.field_bundles import DART_DOCUMENT_VIEW
from app.models.audit_report_fact import AuditReportFact
from app.models.corp import Corp
from app.models.disclosure import Disclosure
from app.models.extraction_job import ExtractionJob
from app.models.extraction_review import ExtractionReview
from app.reviewing.candidates import FactView, ReviewCandidate, SummaryRow, build_candidates

_META_FIELDS = frozenset({"corp_code", "year_end", "rcept_dt", "corp_cls"})
_ReviewKey = tuple[str, str, str, str, str]

EXPORT_COLUMNS: tuple[str, ...] = (
    "rcept_no",
    "dcm_no",
    "bundle",
    "signal",
    "subject",
    "extractor_version",
    "in_research_panel",
    "stratum",
    "tail",
    "queue_order",
    "raw_value",
    "verdict",
    "tag",
    "note",
    "viewer_url",
)

_FORBIDDEN_SIGNALS = frozenset(
    {
        "hours_nonpositive",
        "hours_total_missing",
        "account_negative",
        "unit_missing",
        "subsidiary_negative",
        "date_nonpositive",
    }
)
_REPRESENTATIVE_SIGNALS = frozenset({"rare_code", "auditor_invalid", "fail"})
_IQR_SIGNALS = frozenset({"iqr_low", "iqr_high"})
_ALLOWED_VERDICTS = frozenset({"hold", "source", "logic"})
_ALLOWED_TAGS = frozenset({"as_written", "real_magnitude", "rare_but_valid", "other"})
_TAG_BLOCKING_VERDICTS = frozenset({"logic", "hold"})
_IMPORT_HEADERS = (
    "rcept_no",
    "dcm_no",
    "bundle",
    "signal",
    "subject",
    "verdict",
    "tag",
    "note",
)


class ExtractionReviewError(Exception):
    """진단을 시작하지 못하거나 TSV를 받아들이지 못할 때."""


def fact_to_view(
    fact: AuditReportFact,
    disclosure: Disclosure | None,
    corp: Corp | None,
) -> FactView:
    """FactView 필드를 fact에서 복사하고 접수·회사 메타를 덮어쓴다.

    disclosure가 없으면 접수일은 빈 문자열이다.
    """
    values: dict[str, object] = {}
    for field in fields(FactView):
        if field.name in _META_FIELDS:
            continue
        values[field.name] = getattr(fact, field.name)
    if disclosure is None:
        values["rcept_dt"] = ""
    else:
        values["corp_code"] = disclosure.corp_code
        values["year_end"] = disclosure.year_end
        values["rcept_dt"] = disclosure.rcept_dt
    if corp is not None:
        values["corp_cls"] = corp.corp_cls
    return FactView(**values)  # type: ignore[arg-type]


async def diagnose(session: AsyncSession) -> list[SummaryRow]:
    """현재 추출기 ok 행의 후보를 검토 테이블에 맞추고 요약을 돌려준다.

    세션 commit은 호출자가 한다. facts와 카탈로그는 읽기만 한다.
    """
    running = await session.execute(
        select(ExtractionJob.job_id).where(ExtractionJob.status.in_(("pending", "running")))
    )
    if running.first() is not None:
        raise ExtractionReviewError("추출 잡이 진행 중이라 진단을 시작하지 않습니다.")

    rows = (
        await session.execute(
            select(AuditReportFact, Disclosure, Corp)
            .outerjoin(Disclosure, Disclosure.rcept_no == AuditReportFact.rcept_no)
            .outerjoin(Corp, Corp.corp_code == Disclosure.corp_code)
            .where(
                AuditReportFact.fetch_status == "ok",
                AuditReportFact.extractor_version == EXTRACTOR_VERSION,
            )
        )
    ).all()
    if not rows:
        raise ExtractionReviewError("현재 추출기 ok 행이 없습니다.")

    views = [fact_to_view(fact, disclosure, corp) for fact, disclosure, corp in rows]
    candidates, summary = build_candidates(views)
    await _upsert_reviews(session, candidates)
    return summary


async def _upsert_reviews(session: AsyncSession, candidates: list[ReviewCandidate]) -> None:
    """자연키로 맞추고, 이번 후보에 없는 행은 비활성으로 둔다."""
    stored = (await session.execute(select(ExtractionReview))).scalars().all()
    by_key = {_review_key(row): row for row in stored}
    seen: set[_ReviewKey] = set()
    for candidate in candidates:
        key = _candidate_key(candidate)
        seen.add(key)
        current = by_key.get(key)
        if current is None:
            session.add(_new_review(candidate))
            continue
        _refresh_review(current, candidate)
    for row in stored:
        if _review_key(row) not in seen:
            row.active = False


def _refresh_review(row: ExtractionReview, candidate: ReviewCandidate) -> None:
    """값이 같으면 판정을 두고, 다르면 hold와 이전 판정 메모로 되돌린다."""
    row.extractor_version = EXTRACTOR_VERSION
    row.in_research_panel = candidate.in_research_panel
    row.stratum = candidate.stratum
    row.tail = candidate.tail
    row.queue_order = candidate.queue_order
    row.active = True
    if row.raw_value == candidate.raw_value:
        return
    old_tag = row.tag or "-"
    prefix = f"이전 판정={row.verdict}; 이전 태그={old_tag}; 이전 값={row.raw_value}\n"
    row.verdict = "hold"
    row.tag = ""
    row.note = prefix + row.note
    row.raw_value = candidate.raw_value


def _new_review(candidate: ReviewCandidate) -> ExtractionReview:
    """신규 후보는 판정 hold, 빈 태그·메모로 넣는다."""
    return ExtractionReview(
        rcept_no=candidate.rcept_no,
        dcm_no=candidate.dcm_no,
        bundle=candidate.bundle,
        signal=candidate.signal,
        subject=candidate.subject,
        extractor_version=EXTRACTOR_VERSION,
        in_research_panel=candidate.in_research_panel,
        stratum=candidate.stratum,
        tail=candidate.tail,
        queue_order=candidate.queue_order,
        raw_value=candidate.raw_value,
        active=True,
        verdict="hold",
        tag="",
        note="",
    )


def _review_key(row: ExtractionReview) -> _ReviewKey:
    """검토 행의 자연키."""
    return (row.rcept_no, row.dcm_no, row.bundle, row.signal, row.subject)


def _candidate_key(candidate: ReviewCandidate) -> _ReviewKey:
    """후보의 자연키."""
    return (
        candidate.rcept_no,
        candidate.dcm_no,
        candidate.bundle,
        candidate.signal,
        candidate.subject,
    )


@dataclass(frozen=True)
class _ParsedImport:
    """검증 전 TSV 한 행. 빈 칸은 그대로 둔다."""

    key: _ReviewKey
    verdict: str
    tag: str
    note: str


@dataclass
class _ReviewPatch:
    """쓰기 전에 모아 두는 판정·태그·메모 변경."""

    row: ExtractionReview
    verdict: str | None
    tag: str | None
    note: str | None


async def has_source_and_logic_iqr_stratum(session: AsyncSession) -> bool:
    """활성 IQR 행을 층으로 묶어, source와 logic이 같이 있는 층이 있으면 참.

    다음 hold 창이 비어 있어도 층이 갈려 있으면 참이다.
    """
    rows = await _load_active_reviews(session)
    return any(_mixed_verdict(group) for group in _iqr_groups(rows).values())


async def export_tsv(session: AsyncSession, *, next_slice: bool) -> list[dict[str, str]]:
    """활성 검토 행을 내보내기 열로 만든다.

    next_slice가 거짓이면 금지·대표 신호와 순번 1–5인 IQR이다.
    참이면 판정이 갈린 IQR 층의 다음 hold만이다.
    """
    rows = await _load_active_reviews(session)
    if next_slice:
        picked = _next_slice_rows(rows)
    else:
        picked = [row for row in rows if _in_default_slice(row)]
    picked.sort(key=_export_sort_key)
    return [_export_record(row) for row in picked]


async def import_tsv(session: AsyncSession, text: str) -> int:
    """TSV에서 판정·태그·메모만 반영하고 데이터 행 수를 돌려준다.

    헤더·중복·자연키·판정·태그를 모두 확인한 뒤에만 속성을 바꾼다.
    실패하면 ExtractionReviewError이며 세션은 그대로다. commit은 호출자가 한다.
    """
    parsed = _parse_import(text)
    if not parsed:
        return 0
    stored = (await session.execute(select(ExtractionReview))).scalars().all()
    by_key = {_review_key(row): row for row in stored}
    patches = _plan_patches(parsed, by_key)
    for patch in patches:
        _apply_patch(patch)
    return len(parsed)


def _in_default_slice(row: ExtractionReview) -> bool:
    """기본 집합: 금지 신호, 대표 신호, 순번 1–5인 IQR."""
    if row.signal in _FORBIDDEN_SIGNALS or row.signal in _REPRESENTATIVE_SIGNALS:
        return True
    if row.signal not in _IQR_SIGNALS or row.queue_order is None:
        return False
    return 1 <= row.queue_order <= 5


async def _load_active_reviews(session: AsyncSession) -> list[ExtractionReview]:
    """active가 참인 검토 행만 읽는다."""
    stored = (
        (await session.execute(select(ExtractionReview).where(ExtractionReview.active.is_(True))))
        .scalars()
        .all()
    )
    return list(stored)


def _iqr_groups(rows: list[ExtractionReview]) -> dict[str, list[ExtractionReview]]:
    """IQR 신호만 층 키로 묶는다."""
    grouped: dict[str, list[ExtractionReview]] = {}
    for row in rows:
        if row.signal not in _IQR_SIGNALS:
            continue
        grouped.setdefault(row.stratum, []).append(row)
    return grouped


def _mixed_verdict(group: list[ExtractionReview]) -> bool:
    """한 층에 source와 logic이 둘 다 있으면 참."""
    verdicts = {row.verdict for row in group}
    return "source" in verdicts and "logic" in verdicts


def _next_slice_rows(rows: list[ExtractionReview]) -> list[ExtractionReview]:
    """source와 logic이 함께 있는 층의 IQR만, 꼬리별 m+1부터 m+5 hold를 고른다."""
    chosen: list[ExtractionReview] = []
    for group in _iqr_groups(rows).values():
        if not _mixed_verdict(group):
            continue
        for tail in {row.tail for row in group}:
            chosen.extend(_next_tail(group, tail))
    return chosen


def _next_tail(group: list[ExtractionReview], tail: str) -> list[ExtractionReview]:
    """판정된 순번의 최댓값 다음 다섯 칸 중 hold만 뽑는다. 판정 행이 없으면 빈다."""
    tail_rows = [row for row in group if row.tail == tail]
    judged = [
        row.queue_order
        for row in tail_rows
        if row.verdict != "hold" and row.queue_order is not None
    ]
    if not judged:
        return []
    lower = max(judged) + 1
    upper = lower + 4
    return [
        row
        for row in tail_rows
        if row.verdict == "hold"
        and row.queue_order is not None
        and lower <= row.queue_order <= upper
    ]


def _export_sort_key(row: ExtractionReview) -> tuple[str, str, bool, int, str, str]:
    """층, 신호, 순번(없으면 뒤), 접수번호, 문서번호."""
    queue_order = 0 if row.queue_order is None else row.queue_order
    return (row.stratum, row.signal, row.queue_order is None, queue_order, row.rcept_no, row.dcm_no)


def _export_record(row: ExtractionReview) -> dict[str, str]:
    """한 검토 행을 문자열 열로 만든다. viewer_url은 문서 뷰어 주소다."""
    queue_order = "" if row.queue_order is None else str(row.queue_order)
    panel = "true" if row.in_research_panel else "false"
    viewer_url = DART_DOCUMENT_VIEW.format(rcept_no=row.rcept_no, dcm_no=row.dcm_no)
    values = {
        "rcept_no": row.rcept_no,
        "dcm_no": row.dcm_no,
        "bundle": row.bundle,
        "signal": row.signal,
        "subject": row.subject,
        "extractor_version": row.extractor_version,
        "in_research_panel": panel,
        "stratum": row.stratum,
        "tail": row.tail,
        "queue_order": queue_order,
        "raw_value": row.raw_value,
        "verdict": row.verdict,
        "tag": row.tag,
        "note": row.note,
        "viewer_url": viewer_url,
    }
    return {column: values[column] for column in EXPORT_COLUMNS}


def _parse_import(text: str) -> list[_ParsedImport]:
    """헤더·중복·판정 형식을 확인하고, 쓰기는 하지 않는다."""
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    fieldnames = list(reader.fieldnames or [])
    if any(name not in fieldnames for name in _IMPORT_HEADERS):
        raise ExtractionReviewError("TSV 헤더에 자연키와 판정, 태그, 메모가 없습니다.")
    parsed: list[_ParsedImport] = []
    seen: set[_ReviewKey] = set()
    for raw in reader:
        cells = {name: _import_cell(raw, name) for name in _IMPORT_HEADERS}
        verdict = cells["verdict"]
        if verdict and verdict not in _ALLOWED_VERDICTS:
            raise ExtractionReviewError("판정은 hold, source, logic만 적을 수 있습니다.")
        key = (
            cells["rcept_no"],
            cells["dcm_no"],
            cells["bundle"],
            cells["signal"],
            cells["subject"],
        )
        if key in seen:
            raise ExtractionReviewError("TSV에 같은 자연키가 두 번 있습니다.")
        seen.add(key)
        parsed.append(_ParsedImport(key=key, verdict=verdict, tag=cells["tag"], note=cells["note"]))
    return parsed


def _import_cell(raw: dict[str, str | None], name: str) -> str:
    """없는 칸은 빈 문자열로 본다."""
    value = raw.get(name)
    if value is None:
        return ""
    return value


def _plan_patches(
    parsed: list[_ParsedImport],
    by_key: dict[_ReviewKey, ExtractionReview],
) -> list[_ReviewPatch]:
    """자연키와 태그를 모두 확인한다. 여기서는 속성을 바꾸지 않는다."""
    patches: list[_ReviewPatch] = []
    for item in parsed:
        current = by_key.get(item.key)
        if current is None:
            raise ExtractionReviewError("TSV의 자연키에 해당하는 검토 행이 없습니다.")
        tag = _normalized_tag(item.tag)
        effective = item.verdict or current.verdict
        if tag and effective in _TAG_BLOCKING_VERDICTS:
            raise ExtractionReviewError("logic 또는 hold 판정에는 태그를 적을 수 없습니다.")
        patches.append(
            _ReviewPatch(
                row=current,
                verdict=item.verdict or None,
                tag=tag,
                note=item.note or None,
            )
        )
    return patches


def _normalized_tag(tag: str) -> str | None:
    """빈 칸은 유지, '-'는 빈 태그, 그 외는 허용된 네 값만."""
    if tag == "":
        return None
    if tag == "-":
        return ""
    if tag not in _ALLOWED_TAGS:
        raise ExtractionReviewError(
            "태그는 as_written, real_magnitude, rare_but_valid, other만 적을 수 있습니다."
        )
    return tag


def _apply_patch(patch: _ReviewPatch) -> None:
    """비어 있지 않은 칸만 기존 행에 쓴다. '-' 태그는 빈 문자열이다."""
    if patch.verdict is not None:
        patch.row.verdict = patch.verdict
    if patch.tag is not None:
        patch.row.tag = patch.tag
    if patch.note is not None:
        patch.row.note = patch.note
