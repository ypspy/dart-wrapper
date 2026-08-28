"""감사보고서 표지·의견 추출 오케스트레이션."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.dart_http import DartHttpClient
from app.errors import SourceFetchError
from app.extracting.a001_section import extract_a001_current_audit
from app.extracting.activity_header import extract_activity_header
from app.extracting.auditor_body import extract_body_auditor
from app.extracting.constants import EXTRACTOR_VERSION
from app.extracting.cover import extract_cover_auditor, extract_cover_period
from app.extracting.dates import (
    extract_date_candidates,
    parse_rcept_dt,
    parse_year_end,
    pick_audit_report_date,
)
from app.extracting.gaap import classify_gaap
from app.extracting.opinion import classify_opinion
from app.extracting.resolve import (
    corp_name_conflicts,
    resolve_auditor,
    resolve_opinion,
    year_end_conflicts,
)
from app.extracting.result import FieldResult
from app.extracting.selector import (
    LeafIds,
    SelectorEntry,
    fs_scope_for,
    group_by_dcm,
    is_audit_document,
    select_leaves,
)
from app.extracting.text import compact
from app.models.audit_report_fact import AuditReportFact
from app.models.entry import Entry
from app.models.extraction_job import ExtractionJob
from app.repositories.entry_repository import EntryRepository
from app.repositories.extraction_job_repository import ExtractionJobRepository
from app.repositories.fact_repository import FactRepository
from app.services.dart_job_lock import DART_EXTRACTOR_ID, assert_dart_idle

logger = logging.getLogger(__name__)

_SKIPPED = FieldResult(raw=None, code=None, status="skipped")
_NOT_FOUND_STATUSES = (
    "auditor_status",
    "opinion_status",
    "gaap_status",
    "audit_report_date_status",
    "current_period_status",
)
_DEDICATED_REPORTS = frozenset({"F001", "F002"})
_BLOCK_MARKERS = (
    "captcha",
    "캡차",
    "자동입력방지",
    "비정상적인접근",
    "access denied",
    "차단되었습니다",
)
_A001_OPINION_CODES = (
    ("의견거절", "disclaimer"),
    ("부적정", "adverse"),
    ("한정의견", "qualified"),
    ("한정", "qualified"),
    ("적정", "unqualified"),
    ("거절", "disclaimer"),
)
_AUDITOR_NAMES_PATH = (
    Path(__file__).resolve().parent.parent / "extracting" / "data" / "auditor_names.txt"
)


def _load_auditor_names() -> tuple[str, ...]:
    """D-3-1 감사인명 사전을 읽는다."""
    if not _AUDITOR_NAMES_PATH.is_file():
        return ()
    return tuple(
        line.strip()
        for line in _AUDITOR_NAMES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def html_looks_blocked(html: str) -> bool:
    """차단·캡차로 보이는 응답 본문인지 판별한다."""
    compacted = compact(html).lower()
    return any(compact(marker).lower() in compacted for marker in _BLOCK_MARKERS)


def _html_text(html: str) -> str:
    """HTML에서 본문 텍스트를 꺼낸다."""
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)


def _looks_like_letter(text: str) -> bool:
    """의견 본문 서식처럼 보이는지 판별한다."""
    compacted = compact(text)
    return len(compacted) >= 200 or "감사의견" in compacted


def _to_selector(entry: Entry) -> SelectorEntry | None:
    """카탈로그 행을 selector 입력으로 바꾼다. 식별자가 없으면 건너뛴다."""
    if not entry.dcm_no or not entry.report_type:
        return None
    return SelectorEntry(
        entry_id=entry.entry_id,
        rcept_no=entry.rcept_no,
        dcm_no=entry.dcm_no,
        report_type=entry.report_type,
        source=entry.source,
        document_name=entry.document_name,
        section_name=entry.section_name,
    )


def _has_not_found_field(fact: AuditReportFact) -> bool:
    """reparse 대상인 not_found 필드가 있는지 본다."""
    return any(getattr(fact, name) == "not_found" for name in _NOT_FOUND_STATUSES)


def _should_skip(fact: AuditReportFact | None, mode: str) -> bool:
    """이미 성공한 행은 건너뛰고, reparse는 not_found가 있을 때만 다시 가져온다."""
    if fact is None:
        return False
    if mode == "reparse":
        return not _has_not_found_field(fact)
    return fact.fetch_status == "ok"


def _map_a001_opinion(result: FieldResult) -> FieldResult:
    """A001 당기 칸 문구를 의견 코드로 옮긴다."""
    if result.status != "ok" or not result.raw:
        return result
    compacted = compact(result.raw)
    for label, code in _A001_OPINION_CODES:
        if compact(label) in compacted:
            return FieldResult(raw=result.raw, code=code, status="ok")
    return FieldResult(raw=result.raw, code="other", status="ok")


def _field_status(value: object, *sources: FieldResult | None) -> str:
    """해소 값과 출처 상태로 필드 status를 정한다."""
    if value:
        return "ok"
    present = [item for item in sources if item is not None]
    if present and all(item.status == "skipped" for item in present):
        return "skipped"
    return "not_found"


def _sibling_conflict(left: AuditReportFact, right: AuditReportFact) -> dict[str, str]:
    """형제 행 의견 불일치 기록."""
    return {
        "field": "sibling_opinion",
        "left": left.opinion_code or "",
        "right": right.opinion_code or "",
        "left_source": left.source_report_type,
        "right_source": right.source_report_type,
    }


def _append_conflict(fact: AuditReportFact, conflict: dict[str, str]) -> None:
    """같은 sibling_opinion 쌍이 없으면 conflicts에 추가한다."""
    conflicts = list(fact.conflicts or [])
    for existing in conflicts:
        if not isinstance(existing, dict):
            continue
        if (
            existing.get("field") == conflict["field"]
            and existing.get("right_source") == conflict["right_source"]
            and existing.get("right") == conflict["right"]
        ):
            return
    conflicts.append(conflict)
    fact.conflicts = conflicts


class ExtractionService:
    """감사 추출 잡을 만들고 문서 단위로 실행한다."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        http: DartHttpClient,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._http = http
        self._auditor_names = _load_auditor_names()

    async def start(
        self,
        start_date: str,
        end_date: str,
        report_types: list[str],
        mode: str,
    ) -> str:
        """DART 잠금을 확인하고 추출 잡을 등록한다. 백그라운드는 호출측에서 돌린다."""
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "report_types": list(report_types),
        }
        async with self._sessionmaker() as session:
            await assert_dart_idle(session)
            job_id = uuid.uuid4().hex
            jobs = ExtractionJobRepository(session)
            await jobs.create(job_id, DART_EXTRACTOR_ID, params, mode=mode)
            await jobs.add_log(job_id, "info", "추출 작업을 등록했습니다.")
            await session.commit()
        return job_id

    async def run_job(self, job_id: str) -> None:
        """기간 안 감사 문서를 하나씩 추출하고 커밋한다."""
        async with self._sessionmaker() as session:
            job = await session.get(ExtractionJob, job_id)
            if job is None:
                raise ValueError(f"추출 작업을 찾을 수 없습니다: {job_id}")
            params = dict(job.params or {})
            mode = job.mode
            jobs = ExtractionJobRepository(session)
            await jobs.set_status(job_id, "running")
            await session.commit()

        start_date = str(params.get("start_date", ""))
        end_date = str(params.get("end_date", ""))
        report_types = list(params.get("report_types") or [])

        try:
            async with self._sessionmaker() as session:
                entries = await EntryRepository(session).list_for_extraction(
                    start_date, end_date, report_types
                )

            by_rcept: dict[str, list[Entry]] = defaultdict(list)
            for entry in entries:
                by_rcept[entry.rcept_no].append(entry)

            processed = 0
            for rcept_no, filing in by_rcept.items():
                audit_selectors: list[SelectorEntry] = []
                for entry in filing:
                    selector = _to_selector(entry)
                    if selector is None:
                        continue
                    if is_audit_document(
                        selector.report_type, selector.source, selector.document_name
                    ):
                        audit_selectors.append(selector)
                for dcm_no in group_by_dcm(audit_selectors):
                    await self._process_document(job_id, filing, dcm_no, mode)
                    processed += 1

            async with self._sessionmaker() as session:
                jobs = ExtractionJobRepository(session)
                await jobs.set_status(job_id, "succeeded")
                await jobs.add_log(
                    job_id, "info", f"추출 작업을 마쳤습니다. 문서 {processed}건."
                )
                await session.commit()
        except Exception as exc:
            logger.exception("추출 작업이 중단되었습니다: %s", job_id)
            async with self._sessionmaker() as session:
                jobs = ExtractionJobRepository(session)
                await jobs.set_status(job_id, "failed", error_message=str(exc))
                await jobs.add_log(
                    job_id, "error", f"추출 작업이 중단되었습니다: {exc}"
                )
                await session.commit()

    async def _process_document(
        self,
        job_id: str,
        filing: list[Entry],
        dcm_no: str,
        mode: str,
    ) -> None:
        """문서 하나를 추출·저장하고 형제 의견 conflict를 갱신한다."""
        audit_entries = [entry for entry in filing if entry.dcm_no == dcm_no]
        if not audit_entries:
            return
        sample = audit_entries[0]
        rcept_no = sample.rcept_no

        async with self._sessionmaker() as session:
            facts = FactRepository(session)
            existing = await facts.get(rcept_no, dcm_no)
            if _should_skip(existing, mode):
                return

            fact = await self._extract_document(filing, audit_entries)
            await facts.upsert(fact)
            await self._apply_sibling_opinion(session, fact, sample)
            await ExtractionJobRepository(session).add_log(
                job_id,
                "info",
                f"{rcept_no}/{dcm_no} 추출 완료({fact.fetch_status}).",
            )
            await session.commit()

    async def _extract_document(
        self,
        filing: list[Entry],
        audit_entries: list[Entry],
    ) -> AuditReportFact:
        """leaf HTML을 가져와 파서·해소 후 fact 행을 만든다."""
        sample = audit_entries[0]
        audit_selectors = [
            selector
            for entry in audit_entries
            if (selector := _to_selector(entry)) is not None
        ]
        other_selectors = [
            selector
            for entry in filing
            if entry.dcm_no != sample.dcm_no
            and (selector := _to_selector(entry)) is not None
        ]
        leaves = select_leaves(audit_selectors + other_selectors)
        by_id = {entry.entry_id: entry for entry in filing}

        html_by_role: dict[str, str] = {}
        blocked = False
        failed = False
        section_missing = (
            leaves.cover_entry_id is None and leaves.opinion_entry_id is None
        )
        for role in (
            "cover_entry_id",
            "opinion_entry_id",
            "activity_entry_id",
            "a001_opinion_entry_id",
            "a001_cover_entry_id",
        ):
            entry_id = getattr(leaves, role)
            if not entry_id:
                continue
            entry = by_id.get(entry_id)
            if entry is None or not entry.viewer_url:
                failed = True
                continue
            try:
                html = await self._http.fetch_html(entry.viewer_url)
            except SourceFetchError:
                failed = True
                continue
            if html_looks_blocked(html):
                blocked = True
                continue
            html_by_role[role] = html

        if blocked:
            fetch_status = "blocked"
        elif failed:
            fetch_status = "fetch_failed"
        elif section_missing:
            fetch_status = "section_missing"
        else:
            fetch_status = "ok"

        return self._build_fact(sample, leaves, html_by_role, fetch_status, by_id)

    def _build_fact(
        self,
        sample: Entry,
        leaves: LeafIds,
        html_by_role: dict[str, str],
        fetch_status: str,
        by_id: dict[str, Entry],
    ) -> AuditReportFact:
        """파서 결과와 해소 값을 fact 행으로 모은다."""
        cover_html = html_by_role.get("cover_entry_id")
        if cover_html is not None:
            cover_period = extract_cover_period(cover_html)
            cover_auditor = extract_cover_auditor(cover_html)
        else:
            cover_period = _SKIPPED
            cover_auditor = _SKIPPED

        opinion_html = html_by_role.get("opinion_entry_id")
        if opinion_html is not None:
            opinion_text = _html_text(opinion_html)
            letter_opinion = classify_opinion(
                opinion_text, looks_like_letter=_looks_like_letter(opinion_text)
            )
            gaap = classify_gaap(opinion_text)
            date_candidates = extract_date_candidates(opinion_text)
            date_iso, date_status, _passing = pick_audit_report_date(
                date_candidates,
                period_end=parse_year_end(sample.year_end),
                rcept_dt=parse_rcept_dt(sample.rcept_dt),
            )
            body_auditor = extract_body_auditor(opinion_text, self._auditor_names)
            date_raw = " ".join(item.date_raw for item in date_candidates) or None
            date_payload = [
                {"date": item.iso, "snippet": item.snippet} for item in date_candidates
            ]
        else:
            letter_opinion = _SKIPPED
            gaap = _SKIPPED
            date_iso, date_status, date_raw = None, "skipped", None
            date_payload = []
            body_auditor = _SKIPPED

        a001_html = html_by_role.get("a001_opinion_entry_id")
        if a001_html is not None:
            a001_opinion_raw, a001_auditor = extract_a001_current_audit(a001_html)
            a001_opinion = _map_a001_opinion(a001_opinion_raw)
        else:
            a001_opinion = _SKIPPED
            a001_auditor = _SKIPPED

        activity_html = html_by_role.get("activity_entry_id")
        activity_corp, activity_year = (
            extract_activity_header(activity_html)
            if activity_html is not None
            else (None, None)
        )
        a001_cover_html = html_by_role.get("a001_cover_entry_id")
        a001_cover_period = (
            extract_cover_period(a001_cover_html)
            if a001_cover_html is not None
            else _SKIPPED
        )

        listing = sample.submitter if sample.report_type in _DEDICATED_REPORTS else None
        auditor = resolve_auditor(
            cover=None if cover_auditor.status == "skipped" else cover_auditor,
            a001=None if a001_auditor.status == "skipped" else a001_auditor,
            body=None if body_auditor.status == "skipped" else body_auditor,
            listing=listing,
            report_type=sample.report_type or "",
        )
        opinion = resolve_opinion(letter=letter_opinion, a001=a001_opinion)
        conflicts = [
            *auditor["conflicts"],
            *opinion["conflicts"],
            *corp_name_conflicts(sample.corp_name, activity_corp, None),
            *year_end_conflicts(
                sample.year_end,
                activity_year,
                a001_cover_period.raw if a001_cover_period.status == "ok" else None,
                cover_period.raw if cover_period.status == "ok" else None,
            ),
        ]

        if sample.year_end:
            current_resolved, current_source, current_status = (
                sample.year_end,
                "listing",
                "ok",
            )
        elif cover_period.status == "ok":
            current_resolved, current_source, current_status = (
                cover_period.raw,
                "cover",
                "ok",
            )
        else:
            current_resolved, current_source = None, None
            current_status = cover_period.status

        document_name = sample.document_name
        if sample.report_type == "A001":
            cover_entry = by_id.get(leaves.cover_entry_id or "")
            if cover_entry is not None:
                document_name = cover_entry.document_name or document_name

        return AuditReportFact(
            rcept_no=sample.rcept_no,
            dcm_no=sample.dcm_no or "",
            source_report_type=sample.report_type or "",
            fs_scope=fs_scope_for(sample.report_type or "", document_name),
            cover_entry_id=leaves.cover_entry_id,
            opinion_entry_id=leaves.opinion_entry_id,
            activity_entry_id=leaves.activity_entry_id,
            a001_opinion_entry_id=leaves.a001_opinion_entry_id,
            a001_cover_entry_id=leaves.a001_cover_entry_id,
            auditor=cover_auditor.raw if cover_auditor.status != "skipped" else None,
            auditor_body=body_auditor.raw if body_auditor.status != "skipped" else None,
            auditor_a001=a001_auditor.raw if a001_auditor.status != "skipped" else None,
            auditor_listing=listing,
            auditor_status=_field_status(
                auditor["value"], cover_auditor, a001_auditor, body_auditor
            ),
            auditor_resolved=auditor["value"],
            auditor_source=auditor["source"],
            opinion_raw=letter_opinion.raw
            if letter_opinion.status != "skipped"
            else a001_opinion.raw,
            opinion_code=opinion["value"],
            opinion_status=_field_status(opinion["value"], letter_opinion, a001_opinion),
            opinion_resolved=opinion["value"],
            opinion_source=opinion["source"],
            audit_report_date_raw=date_raw,
            audit_report_date_candidates=date_payload,
            audit_report_date=date_iso,
            audit_report_date_status=date_status,
            audit_report_date_source="letter" if date_status == "ok" else None,
            gaap_raw=gaap.raw if gaap.status != "skipped" else None,
            gaap_code=gaap.code if gaap.status != "skipped" else None,
            gaap_status=gaap.status,
            gaap_resolved=gaap.code if gaap.status == "ok" else None,
            gaap_source="letter" if gaap.status == "ok" else None,
            current_period_raw=cover_period.raw
            if cover_period.status != "skipped"
            else None,
            current_period_status=current_status,
            current_period_resolved=current_resolved,
            current_period_source=current_source,
            fetch_status=fetch_status,
            conflicts=conflicts,
            extractor_version=EXTRACTOR_VERSION,
        )

    async def _apply_sibling_opinion(
        self,
        session: AsyncSession,
        fact: AuditReportFact,
        sample: Entry,
    ) -> None:
        """같은 기업·결산월·범위의 F001/F002와 A001 의견이 다르면 양쪽에 기록한다."""
        if not sample.corp_code or not sample.year_end or not fact.opinion_code:
            return
        siblings = await FactRepository(session).list_siblings(
            corp_code=sample.corp_code,
            year_end=sample.year_end,
            fs_scope=fact.fs_scope,
            rcept_no=fact.rcept_no,
        )
        for sibling in siblings:
            dedicated = fact.source_report_type in _DEDICATED_REPORTS
            other_dedicated = sibling.source_report_type in _DEDICATED_REPORTS
            if dedicated == other_dedicated:
                continue
            if not sibling.opinion_code or sibling.opinion_code == fact.opinion_code:
                continue
            _append_conflict(fact, _sibling_conflict(fact, sibling))
            _append_conflict(sibling, _sibling_conflict(sibling, fact))
            await FactRepository(session).upsert(sibling)
        await FactRepository(session).upsert(fact)
