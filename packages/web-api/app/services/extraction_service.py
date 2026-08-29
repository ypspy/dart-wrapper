"""감사보고서 표지·의견 추출 오케스트레이션."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.dart_http import DartHttpClient
from app.errors import CatalogNotFound, SourceFetchError
from app.extracting.a001_section import extract_a001_current_audit
from app.extracting.activity_header import extract_activity_header
from app.extracting.auditor_body import extract_body_auditor
from app.extracting.constants import EXTRACTOR_VERSION
from app.extracting.cover import (
    extract_cover_auditor,
    extract_cover_company_name,
    extract_cover_period,
)
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
from app.schemas.catalog import JobLogItem
from app.schemas.extract import ExtractJobStatusResponse
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
_REQUIRED_LEAF_ROLES = ("cover_entry_id", "opinion_entry_id")
_LEAF_ROLES = (
    "cover_entry_id",
    "opinion_entry_id",
    "activity_entry_id",
    "a001_opinion_entry_id",
    "a001_cover_entry_id",
)
_BLOCK_HTTP_STATUSES = frozenset({403, 429})
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
    """같은 버전의 성공 행은 건너뛰고, reparse는 not_found가 있을 때만 다시 가져온다."""
    if fact is None:
        return False
    if mode == "reparse":
        return not _has_not_found_field(fact)
    return fact.fetch_status == "ok" and fact.extractor_version == EXTRACTOR_VERSION


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


def _copy_operator_fields(fact: AuditReportFact, existing: AuditReportFact | None) -> None:
    """기존 override·LLM 컬럼을 유지하고, override가 있으면 보고일에 우선한다."""
    if existing is None:
        return
    fact.audit_report_date_override = existing.audit_report_date_override
    fact.date_resolver_model = existing.date_resolver_model
    fact.date_resolver_prompt_version = existing.date_resolver_prompt_version
    fact.date_resolver_raw_response = existing.date_resolver_raw_response
    if existing.audit_report_date_override:
        fact.audit_report_date = existing.audit_report_date_override
        fact.audit_report_date_status = "ok"
        fact.audit_report_date_source = "override"
    elif existing.audit_report_date_source in {"llm", "override"}:
        fact.audit_report_date = existing.audit_report_date
        fact.audit_report_date_status = existing.audit_report_date_status
        fact.audit_report_date_source = existing.audit_report_date_source


def _failed_fact(sample: Entry, existing: AuditReportFact | None) -> AuditReportFact:
    """예외가 난 문서의 fetch_failed 행을 만든다."""
    if existing is not None:
        existing.fetch_status = "fetch_failed"
        return existing
    return AuditReportFact(
        rcept_no=sample.rcept_no,
        dcm_no=sample.dcm_no or "",
        source_report_type=sample.report_type or "",
        fs_scope=fs_scope_for(sample.report_type or "", sample.document_name),
        fetch_status="fetch_failed",
        conflicts=[],
        audit_report_date_candidates=[],
        extractor_version=EXTRACTOR_VERSION,
    )


class _BlockStreakExceeded(Exception):
    """연속 차단 응답으로 추출 잡을 멈출 때 쓴다."""


class ExtractionService:
    """감사 추출 잡을 만들고 문서 단위로 실행한다."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        http: DartHttpClient,
        *,
        block_streak_threshold: int = 5,
        block_wait_seconds: float = 60.0,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._http = http
        self._auditor_names = _load_auditor_names()
        self._block_streak_threshold = block_streak_threshold
        self._block_wait_seconds = block_wait_seconds
        self._stop_requested: set[str] = set()

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

    async def request_soft_stop(self, job_id: str) -> None:
        """다음 접수 경계에서 추출을 멈춘다. 이미 저장한 문서는 유지한다."""
        self._stop_requested.add(job_id)
        async with self._sessionmaker() as session:
            jobs = ExtractionJobRepository(session)
            job = await session.get(ExtractionJob, job_id)
            if job is None:
                raise CatalogNotFound(f"추출 작업을 찾을 수 없습니다: {job_id}")
            await jobs.add_log(
                job_id,
                "warning",
                "중단 요청을 받았습니다. 진행 중인 접수까지만 처리합니다.",
            )
            await session.commit()

    async def force_finish(self, job_id: str) -> None:
        """멈춘 것으로 보이는 추출 잡을 즉시 부분 종료해 잠금을 푼다."""
        self._stop_requested.add(job_id)
        async with self._sessionmaker() as session:
            jobs = ExtractionJobRepository(session)
            job = await session.get(ExtractionJob, job_id)
            if job is None:
                raise CatalogNotFound(f"추출 작업을 찾을 수 없습니다: {job_id}")
            if job.status not in {"pending", "running"}:
                return
            await jobs.set_status(
                job_id,
                "partial",
                error_message="운영자가 작업을 강제 종료했습니다.",
            )
            await jobs.add_log(
                job_id,
                "warning",
                "운영자가 작업을 강제 종료했습니다. 미완료분은 이어하기로 재개하세요.",
            )
            await session.commit()

    async def get_status(self, job_id: str) -> ExtractJobStatusResponse:
        """추출 작업 현황과 최근 로그를 반환한다.

        :raises CatalogNotFound: 해당 작업이 없는 경우
        """
        async with self._sessionmaker() as session:
            job = await session.get(ExtractionJob, job_id)
            if job is None:
                raise CatalogNotFound(f"추출 작업을 찾을 수 없습니다: {job_id}")
            logs = await ExtractionJobRepository(session).recent_logs(job_id)

        return ExtractJobStatusResponse(
            job_id=job.job_id,
            status=job.status,
            mode=job.mode,
            params=job.params,
            error_message=job.error_message,
            started_at=job.started_at,
            finished_at=job.finished_at,
            logs=[JobLogItem.model_validate(log) for log in logs],
        )

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
                rcept_nos = await EntryRepository(session).list_rcept_nos_for_extraction(
                    start_date, end_date, report_types
                )

            processed = 0
            block_streak = 0
            for rcept_no in rcept_nos:
                if job_id in self._stop_requested:
                    await self._finish_partial(job_id, processed)
                    return
                async with self._sessionmaker() as session:
                    filing = await EntryRepository(session).list_by_rcept_no(rcept_no)
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
                    try:
                        fetch_status = await self._process_document(job_id, filing, dcm_no, mode)
                    except Exception as exc:
                        sample = next(
                            (entry for entry in filing if entry.dcm_no == dcm_no),
                            None,
                        )
                        if sample is None:
                            raise
                        await self._mark_document_failed(job_id, sample, exc)
                        fetch_status = "fetch_failed"
                    if fetch_status is not None:
                        processed += 1
                    if fetch_status == "blocked":
                        block_streak += 1
                        if block_streak >= self._block_streak_threshold:
                            if self._block_wait_seconds > 0:
                                await asyncio.sleep(self._block_wait_seconds)
                            raise _BlockStreakExceeded(
                                "추출이 차단된 것으로 보여 중단합니다. " "재개로 이어서 처리하세요."
                            )
                    else:
                        block_streak = 0

            async with self._sessionmaker() as session:
                jobs = ExtractionJobRepository(session)
                await jobs.set_status(job_id, "succeeded")
                await jobs.add_log(job_id, "info", f"추출 작업을 마쳤습니다. 문서 {processed}건.")
                await session.commit()
        except _BlockStreakExceeded as exc:
            logger.warning("추출 작업이 차단으로 중단되었습니다: %s", job_id)
            async with self._sessionmaker() as session:
                jobs = ExtractionJobRepository(session)
                await jobs.set_status(job_id, "failed", error_message=str(exc))
                await jobs.add_log(job_id, "error", f"추출 작업이 중단되었습니다: {exc}")
                await session.commit()
        except Exception as exc:
            logger.exception("추출 작업이 중단되었습니다: %s", job_id)
            async with self._sessionmaker() as session:
                jobs = ExtractionJobRepository(session)
                await jobs.set_status(job_id, "failed", error_message=str(exc))
                await jobs.add_log(job_id, "error", f"추출 작업이 중단되었습니다: {exc}")
                await session.commit()

    async def _finish_partial(self, job_id: str, processed: int) -> None:
        """soft-stop으로 중간 종료한다."""
        async with self._sessionmaker() as session:
            jobs = ExtractionJobRepository(session)
            await jobs.set_status(job_id, "partial")
            await jobs.add_log(
                job_id,
                "warning",
                f"중단 요청으로 추출을 멈췄습니다. 처리한 문서 {processed}건.",
            )
            await session.commit()

    async def _process_document(
        self,
        job_id: str,
        filing: list[Entry],
        dcm_no: str,
        mode: str,
    ) -> str | None:
        """문서 하나를 추출·저장하고 형제 의견 conflict를 갱신한다.

        건너뛰면 None, 처리하면 fetch_status를 반환한다.
        """
        audit_entries = [entry for entry in filing if entry.dcm_no == dcm_no]
        if not audit_entries:
            return None
        sample = audit_entries[0]
        rcept_no = sample.rcept_no

        async with self._sessionmaker() as session:
            existing = await FactRepository(session).get(rcept_no, dcm_no)
            if _should_skip(existing, mode):
                return None

        try:
            fact = await self._extract_document(filing, audit_entries)
        except Exception as exc:
            await self._mark_document_failed(job_id, sample, exc)
            return "fetch_failed"

        async with self._sessionmaker() as session:
            facts = FactRepository(session)
            existing = await facts.get(rcept_no, dcm_no)
            _copy_operator_fields(fact, existing)
            await facts.upsert(fact)
            await self._apply_sibling_opinion(session, fact, sample)
            await ExtractionJobRepository(session).add_log(
                job_id,
                "info",
                f"{rcept_no}/{dcm_no} 추출 완료({fact.fetch_status}).",
            )
            await session.commit()
        return fact.fetch_status

    async def _mark_document_failed(
        self,
        job_id: str,
        sample: Entry,
        exc: BaseException,
    ) -> None:
        """문서 예외를 fetch_failed로 남기고 다음 문서로 넘어갈 수 있게 한다."""
        rcept_no = sample.rcept_no
        dcm_no = sample.dcm_no or ""
        logger.exception("문서 추출에 실패했습니다: %s/%s", rcept_no, dcm_no)
        async with self._sessionmaker() as session:
            facts = FactRepository(session)
            existing = await facts.get(rcept_no, dcm_no)
            await facts.upsert(_failed_fact(sample, existing))
            await ExtractionJobRepository(session).add_log(
                job_id,
                "error",
                f"{rcept_no}/{dcm_no} 추출 실패: {exc}",
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
            selector for entry in audit_entries if (selector := _to_selector(entry)) is not None
        ]
        other_selectors = [
            selector
            for entry in filing
            if entry.dcm_no != sample.dcm_no and (selector := _to_selector(entry)) is not None
        ]
        leaves = select_leaves(audit_selectors + other_selectors)
        by_id = {entry.entry_id: entry for entry in filing}

        html_by_role: dict[str, str] = {}
        blocked = False
        failed = False
        section_missing = leaves.cover_entry_id is None and leaves.opinion_entry_id is None
        for role in _LEAF_ROLES:
            entry_id = getattr(leaves, role)
            if not entry_id:
                continue
            entry = by_id.get(entry_id)
            required = role in _REQUIRED_LEAF_ROLES
            if entry is None or not entry.viewer_url:
                if required:
                    failed = True
                continue
            try:
                html = await self._http.fetch_html(entry.viewer_url)
            except SourceFetchError as exc:
                if exc.status_code in _BLOCK_HTTP_STATUSES:
                    blocked = True
                elif required:
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
            date_payload = [{"date": item.iso, "snippet": item.snippet} for item in date_candidates]
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
            extract_activity_header(activity_html) if activity_html is not None else (None, None)
        )
        a001_cover_html = html_by_role.get("a001_cover_entry_id")
        a001_cover_period = (
            extract_cover_period(a001_cover_html) if a001_cover_html is not None else _SKIPPED
        )
        a001_cover_corp = (
            extract_cover_company_name(a001_cover_html) if a001_cover_html is not None else None
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
            *corp_name_conflicts(sample.corp_name, activity_corp, a001_cover_corp),
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
            opinion_raw=(
                letter_opinion.raw if letter_opinion.status != "skipped" else a001_opinion.raw
            ),
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
            current_period_raw=cover_period.raw if cover_period.status != "skipped" else None,
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
        facts = FactRepository(session)
        siblings = await facts.list_siblings(
            corp_code=sample.corp_code,
            year_end=sample.year_end,
            fs_scope=fact.fs_scope,
            rcept_no=fact.rcept_no,
        )
        mutated = False
        for sibling in siblings:
            dedicated = fact.source_report_type in _DEDICATED_REPORTS
            other_dedicated = sibling.source_report_type in _DEDICATED_REPORTS
            if dedicated == other_dedicated:
                continue
            if not sibling.opinion_code or sibling.opinion_code == fact.opinion_code:
                continue
            _append_conflict(fact, _sibling_conflict(fact, sibling))
            _append_conflict(sibling, _sibling_conflict(sibling, fact))
            await facts.upsert(sibling)
            mutated = True
        if mutated:
            await facts.upsert(fact)
