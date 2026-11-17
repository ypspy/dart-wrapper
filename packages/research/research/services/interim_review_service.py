"""반기·분기 검토보고서 추출 잡.

감사 추출과 같은 잡·로그·soft-stop·force-finish·차단 연속 틀을 쓰고,
DART 요청은 넘겨받은 dart_http 클라이언트만 사용한다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.dart_http import DartHttpClient
from app.errors import CatalogConflict, CatalogNotFound, SourceFetchError
from app.models.entry import Entry
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.entry_repository import EntryRepository
from research.extracting.interim_review import INTERIM_EXTRACTOR_VERSION, parse_interim_review
from research.extracting.interim_review import InterimReviewParse
from research.extracting.interim_selector import (
    InterimLeafIds,
    interim_doc_kind,
    interim_fs_scope,
    interim_review_kind,
    is_interim_review_document,
    select_interim_leaves,
)
from research.extracting.selector import SelectorEntry
from research.models.extraction_job import ExtractionJob
from research.models.interim_review_fact import InterimReviewFact
from research.repositories.extraction_job_repository import ExtractionJobRepository
from research.repositories.interim_fact_repository import InterimFactRepository
from research.services.dart_job_lock import INTERIM_EXTRACTOR_ID, assert_dart_idle
from research.services.extraction_service import _load_auditor_names, html_looks_blocked

logger = logging.getLogger(__name__)

_BLOCK_HTTP_STATUSES = frozenset({403, 429})
_TABLE_MISSING = "interim_review_facts 테이블이 없습니다. 생성 스크립트를 먼저 실행하세요."


class _BlockStreakExceeded(Exception):
    """연속 차단 응답으로 추출 잡을 멈출 때 쓴다."""


def _should_skip(fact: InterimReviewFact | None, mode: str) -> bool:
    """ok·v1 행은 extract와 resume 모두 요청 없이 건너뛴다."""
    if fact is None or mode not in {"extract", "resume"}:
        return False
    return fact.fetch_status == "ok" and fact.extractor_version == INTERIM_EXTRACTOR_VERSION


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


class InterimReviewService:
    """검토보고서 추출 잡을 만들고 문서 단위로 실행한다."""

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
        """테이블과 DART 잠금을 확인한 뒤 검토 추출 잡을 등록한다."""
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "report_types": list(report_types),
        }
        async with self._sessionmaker() as session:
            if not await _interim_table_exists(session):
                raise CatalogConflict(_TABLE_MISSING)
            await assert_dart_idle(session)
            job_id = uuid.uuid4().hex
            jobs = ExtractionJobRepository(session)
            await jobs.create(job_id, INTERIM_EXTRACTOR_ID, params, mode=mode)
            await jobs.add_log(job_id, "info", "반기·분기 검토보고서 추출 작업을 등록했습니다.")
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

    async def run_job(self, job_id: str) -> None:
        """기간 안 검토 문서를 하나씩 추출하고 커밋한다."""
        async with self._sessionmaker() as session:
            job = await session.get(ExtractionJob, job_id)
            if job is None:
                raise ValueError(f"추출 작업을 찾을 수 없습니다: {job_id}")
            params = dict(job.params or {})
            mode = job.mode
            await ExtractionJobRepository(session).set_status(job_id, "running")
            await session.commit()

        start_date = str(params.get("start_date", ""))
        end_date = str(params.get("end_date", ""))
        report_types = list(params.get("report_types") or [])
        try:
            await self._run_window_loop(job_id, start_date, end_date, report_types, mode)
        except _BlockStreakExceeded as exc:
            logger.warning("검토보고서 추출 작업이 차단으로 중단되었습니다: %s", job_id)
            async with self._sessionmaker() as session:
                jobs = ExtractionJobRepository(session)
                await jobs.set_status(job_id, "failed", error_message=str(exc))
                await jobs.add_log(job_id, "error", f"추출 작업이 중단되었습니다: {exc}")
                await session.commit()
        except Exception as exc:
            logger.exception("검토보고서 추출 작업이 중단되었습니다: %s", job_id)
            async with self._sessionmaker() as session:
                jobs = ExtractionJobRepository(session)
                await jobs.set_status(job_id, "failed", error_message=str(exc))
                await jobs.add_log(job_id, "error", f"추출 작업이 중단되었습니다: {exc}")
                await session.commit()

    async def _run_window_loop(
        self,
        job_id: str,
        start_date: str,
        end_date: str,
        report_types: list[str],
        mode: str,
    ) -> None:
        """기간 안 접수를 돌며 검토 대상 문서만 처리한다."""
        async with self._sessionmaker() as session:
            rcept_nos = await DisclosureRepository(session).list_rcept_nos(
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
            for dcm_no in _interim_dcm_nos(filing):
                fetch_status = await self._extract_one(job_id, filing, dcm_no, mode)
                if fetch_status is not None:
                    processed += 1
                block_streak = await self._apply_block_streak(fetch_status, block_streak)
        await self._finish_success(job_id, processed)

    async def _apply_block_streak(self, fetch_status: str | None, streak: int) -> int:
        """차단 연속 횟수를 갱신하고 한도를 넘으면 기다린 뒤 중단한다."""
        if fetch_status != "blocked":
            return 0
        streak += 1
        if streak >= self._block_streak_threshold:
            if self._block_wait_seconds > 0:
                await asyncio.sleep(self._block_wait_seconds)
            raise _BlockStreakExceeded(
                "추출이 차단된 것으로 보여 중단합니다. 재개로 이어서 처리하세요."
            )
        return streak

    async def _finish_success(self, job_id: str, processed: int) -> None:
        """잡을 완료로 표시한다."""
        async with self._sessionmaker() as session:
            jobs = ExtractionJobRepository(session)
            await jobs.set_status(job_id, "succeeded")
            await jobs.add_log(
                job_id,
                "info",
                f"반기·분기 검토보고서 추출 작업을 마쳤습니다. 문서 {processed}건.",
            )
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

    async def _extract_one(
        self,
        job_id: str,
        filing: list[Entry],
        dcm_no: str,
        mode: str,
    ) -> str | None:
        """문서 하나를 처리한다. 예기치 않은 예외는 fetch_failed로 남긴다."""
        try:
            return await self._process_document(job_id, filing, dcm_no, mode)
        except Exception as exc:
            sample = next((entry for entry in filing if entry.dcm_no == dcm_no), None)
            if sample is None:
                raise
            await self._mark_document_failed(job_id, sample, exc)
            return "fetch_failed"

    async def _process_document(
        self,
        job_id: str,
        filing: list[Entry],
        dcm_no: str,
        mode: str,
    ) -> str | None:
        """문서 하나를 추출·저장한다. 건너뛰면 None."""
        rows = [entry for entry in filing if entry.dcm_no == dcm_no]
        named = next(
            (
                entry
                for entry in rows
                if is_interim_review_document(entry.report_type, entry.source, entry.document_name)
            ),
            None,
        )
        if named is None or not named.dcm_no:
            return None
        selectors = [selector for entry in rows if (selector := _to_selector(entry)) is not None]
        leaves = select_interim_leaves(selectors)

        async with self._sessionmaker() as session:
            existing = await InterimFactRepository(session).get(named.rcept_no, named.dcm_no)
            if _should_skip(existing, mode):
                return None

        fact = await self._build_fact(named, rows, leaves)
        await self._save(job_id, fact)
        return fact.fetch_status

    async def _build_fact(
        self,
        named: Entry,
        rows: list[Entry],
        leaves: InterimLeafIds,
    ) -> InterimReviewFact:
        """report leaf만 요청하고 파서 결과로 행을 만든다."""
        doc_kind = interim_doc_kind(named.report_type, named.source, named.document_name) or ""
        review_kind = interim_review_kind(named.report_type, named.source, named.document_name)
        fs_scope = interim_fs_scope(named.report_type, named.source, named.document_name)
        by_id = {entry.entry_id: entry for entry in rows}
        base = _shell(
            named,
            leaves,
            doc_kind=doc_kind,
            review_kind=review_kind or "",
            fs_scope=fs_scope,
        )
        report = by_id.get(leaves.report_entry_id or "")
        if leaves.report_entry_id is None or report is None:
            base.fetch_status = "section_missing"
            return base
        if not report.viewer_url:
            base.fetch_status = "fetch_failed"
            return base
        try:
            html = await self._http.fetch_html(report.viewer_url)
        except SourceFetchError as exc:
            if exc.status_code in _BLOCK_HTTP_STATUSES:
                base.fetch_status = "blocked"
            else:
                base.fetch_status = "fetch_failed"
            return base
        if html_looks_blocked(html):
            base.fetch_status = "blocked"
            return base
        parsed = parse_interim_review(
            html,
            auditor_names=self._auditor_names,
            doc_kind=doc_kind or None,
            review_kind=review_kind or None,
        )
        _apply_parse(base, parsed)
        base.fetch_status = "ok"
        return base

    async def _save(self, job_id: str, fact: InterimReviewFact) -> None:
        """문서 하나를 커밋하고 완료 로그를 남긴다."""
        async with self._sessionmaker() as session:
            await InterimFactRepository(session).upsert(fact)
            await ExtractionJobRepository(session).add_log(
                job_id,
                "info",
                f"{fact.rcept_no}/{fact.dcm_no} 추출 완료({fact.fetch_status}).",
            )
            await session.commit()

    async def _mark_document_failed(
        self,
        job_id: str,
        sample: Entry,
        exc: BaseException,
    ) -> None:
        """문서 예외를 fetch_failed로 남기고 다음 문서로 넘어간다."""
        rcept_no = sample.rcept_no
        dcm_no = sample.dcm_no or ""
        logger.exception("검토보고서 추출에 실패했습니다: %s/%s", rcept_no, dcm_no)
        doc_kind = interim_doc_kind(sample.report_type, sample.source, sample.document_name) or ""
        review_kind = (
            interim_review_kind(sample.report_type, sample.source, sample.document_name) or ""
        )
        fact = InterimReviewFact(
            rcept_no=rcept_no,
            dcm_no=dcm_no,
            source_report_type=sample.report_type or "",
            review_kind=review_kind,
            fs_scope=interim_fs_scope(sample.report_type, sample.source, sample.document_name),
            doc_kind=doc_kind,
            fetch_status="fetch_failed",
            conflicts=[],
            review_report_date_candidates=[],
            emphasis_of_matter=False,
            going_concern=False,
            extractor_version=INTERIM_EXTRACTOR_VERSION,
        )
        async with self._sessionmaker() as session:
            existing = await InterimFactRepository(session).get(rcept_no, dcm_no)
            if existing is not None:
                existing.fetch_status = "fetch_failed"
                fact = existing
            await InterimFactRepository(session).upsert(fact)
            await ExtractionJobRepository(session).add_log(
                job_id,
                "error",
                f"{rcept_no}/{dcm_no} 추출 실패: {exc}",
            )
            await session.commit()


def _interim_dcm_nos(filing: list[Entry]) -> list[str]:
    """검토 대상 첨부가 있는 dcm_no를 등장 순으로 모은다."""
    seen: dict[str, None] = {}
    for entry in filing:
        if not entry.dcm_no:
            continue
        if is_interim_review_document(entry.report_type, entry.source, entry.document_name):
            seen.setdefault(entry.dcm_no, None)
    return list(seen.keys())


def _shell(
    named: Entry,
    leaves: InterimLeafIds,
    *,
    doc_kind: str,
    review_kind: str,
    fs_scope: str,
) -> InterimReviewFact:
    """파서 전 공통 열만 채운 행."""
    return InterimReviewFact(
        rcept_no=named.rcept_no,
        dcm_no=named.dcm_no or "",
        source_report_type=named.report_type or "",
        review_kind=review_kind,
        fs_scope=fs_scope,
        doc_kind=doc_kind,
        cover_entry_id=leaves.cover_entry_id,
        report_entry_id=leaves.report_entry_id,
        fs_parent_entry_id=leaves.fs_parent_entry_id,
        notes_entry_id=leaves.notes_entry_id,
        fetch_status="section_missing",
        conflicts=[],
        review_report_date_candidates=[],
        emphasis_of_matter=False,
        going_concern=False,
        extractor_version=INTERIM_EXTRACTOR_VERSION,
    )


def _apply_parse(fact: InterimReviewFact, parsed: InterimReviewParse) -> None:
    """파서 결과를 행에 옮긴다."""
    fact.reviewer_raw = parsed.reviewer_raw
    fact.reviewer_resolved = parsed.reviewer_resolved
    fact.reviewer_status = parsed.reviewer_status
    fact.conclusion_raw = parsed.conclusion_raw
    fact.conclusion_code = parsed.conclusion_code
    fact.conclusion_status = parsed.conclusion_status
    fact.review_report_date_raw = parsed.review_report_date_raw
    fact.review_report_date = parsed.review_report_date
    fact.review_report_date_status = parsed.review_report_date_status
    fact.review_report_date_candidates = list(parsed.review_report_date_candidates)
    fact.review_period_raw = parsed.review_period_raw
    fact.review_period_resolved = parsed.review_period_resolved
    fact.review_period_status = parsed.review_period_status
    fact.gaap_code = parsed.gaap_code
    fact.gaap_status = parsed.gaap_status
    fact.emphasis_of_matter = parsed.emphasis_of_matter
    fact.going_concern = parsed.going_concern
    fact.emphasis_raw = parsed.emphasis_raw
    fact.emphasis_status = parsed.emphasis_status


async def _interim_table_exists(session: AsyncSession) -> bool:
    """interim_review_facts 테이블이 이미 있는지 본다."""
    connection = await session.connection()

    def _has(sync_conn: object) -> bool:
        from sqlalchemy import inspect

        return bool(inspect(sync_conn).has_table("interim_review_facts"))

    return bool(await connection.run_sync(_has))
