"""진단 후보를 검토 테이블에 맞춘다."""

from __future__ import annotations

from dataclasses import fields

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.extracting.constants import EXTRACTOR_VERSION
from app.models.audit_report_fact import AuditReportFact
from app.models.corp import Corp
from app.models.disclosure import Disclosure
from app.models.extraction_job import ExtractionJob
from app.models.extraction_review import ExtractionReview
from app.reviewing.candidates import FactView, ReviewCandidate, SummaryRow, build_candidates

_META_FIELDS = frozenset({"corp_code", "year_end", "rcept_dt", "corp_cls"})
_ReviewKey = tuple[str, str, str, str, str]


class ExtractionReviewError(Exception):
    """진단을 시작하지 못하거나 모집단이 비었을 때."""


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
