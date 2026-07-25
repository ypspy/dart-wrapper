"""Admin 카탈로그 수집 오케스트레이션.

수집은 `report_type × 날짜` 슬라이스로 나누고, 슬라이스 안에서는 공시(접수번호) 하나를
처리할 때마다 저장·기록을 확정한다. 그래서 차단·중단으로 끊겨도 성공분은 남고,
재개 시에는 실패·미처리 공시만 다시 처리한다.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.errors import CatalogNotFound
from app.models.disclosure import Disclosure
from app.ports.entry_collector import CollectRequest, DisclosureListItem, EntryCollector
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.entry_repository import EntryRepository
from app.repositories.job_repository import JobRepository
from app.repositories.slice_repository import SliceRepository
from app.schemas.catalog import (
    ExtractRequest,
    ExtractResponse,
    JobLogItem,
    JobStatusResponse,
    ResumeRequest,
)
from app.schemas.entry import EntryRecord

logger = logging.getLogger(__name__)


def _params_key(payload: dict[str, object]) -> str:
    """같은 범위의 중복 수집을 판별하기 위한 정규화 키를 만든다."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def iter_dates(start_date: str, end_date: str) -> list[str]:
    """YYYYMMDD 구간을 하루 단위 슬라이스 날짜 목록으로 펼친다."""
    start = date(int(start_date[:4]), int(start_date[4:6]), int(start_date[6:8]))
    end = date(int(end_date[:4]), int(end_date[4:6]), int(end_date[6:8]))
    if end < start:
        start, end = end, start

    days: list[str] = []
    current = start
    while current <= end:
        days.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return days


def disclosures_from_records(records: Sequence[EntryRecord]) -> list[Disclosure]:
    """수집된 leaf를 접수번호별로 묶어 disclosure 행을 만든다."""
    by_rcp: dict[str, list[EntryRecord]] = {}
    for record in records:
        by_rcp.setdefault(record.rcept_no, []).append(record)

    rows: list[Disclosure] = []
    for rcept_no, group in by_rcp.items():
        sample = group[0]
        rows.append(
            Disclosure(
                rcept_no=rcept_no,
                corp_code=sample.corp_code,
                corp_name=sample.corp_name,
                report_nm=sample.report_nm,
                report_type=sample.report_type,
                correction_type=sample.correction_type,
                submitter=sample.submitter,
                rcept_dt=sample.rcept_dt or "",
                bsns_year=sample.bsns_year,
                year_end=sample.year_end,
                disclosure_url=sample.disclosure_url,
                entry_count=len(group),
            )
        )
    return rows


class CatalogService:
    """수집 작업을 만들고, 슬라이스 단위로 실행하며, 현황을 조회한다."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        collector: EntryCollector,
        *,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
        block_streak_threshold: int = 5,
        block_wait_seconds: float = 60.0,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._collector = collector
        self._max_retries = max(1, max_retries)
        self._retry_backoff_seconds = retry_backoff_seconds
        self._block_streak_threshold = block_streak_threshold
        self._block_wait_seconds = block_wait_seconds

    async def start_extract(self, request: ExtractRequest) -> ExtractResponse:
        """수집 작업을 등록한다. 같은 범위가 진행 중이면 기존 작업을 돌려준다."""
        return await self._start_job(request.model_dump(mode="json"), mode="collect")

    async def start_resume(self, request: ResumeRequest) -> ExtractResponse:
        """미완료·실패 슬라이스를 이어서 처리할 작업을 등록한다."""
        return await self._start_job(request.model_dump(mode="json"), mode="resume")

    async def run_job(self, job_id: str, request: ExtractRequest) -> None:
        """요청 기간을 날짜 슬라이스로 나눠 순서대로 처리한다."""
        days = iter_dates(request.start_date, request.end_date)
        targets = [(request.report_type, day) for day in days]
        await self._run_slices(job_id, targets, request.include_attachments)

    async def run_resume_job(self, job_id: str, request: ResumeRequest) -> None:
        """완료되지 않은 슬라이스만 골라 다시 처리한다."""
        async with self._sessionmaker() as session:
            pending = await SliceRepository(session).list_incomplete(
                report_type=request.report_type,
                slice_id=request.slice_id,
            )
            targets = [(row.report_type, row.slice_date) for row in pending]

        if not targets:
            async with self._sessionmaker() as session:
                jobs = JobRepository(session)
                await jobs.mark_running(job_id)
                await jobs.add_log(job_id, "info", "재개할 슬라이스가 없습니다.")
                await jobs.mark_finished(job_id, "succeeded", total_entries=0, saved_entries=0)
                await session.commit()
            return

        await self._run_slices(job_id, targets, request.include_attachments)

    async def get_status(self, job_id: str) -> JobStatusResponse:
        """작업 현황과 최근 로그를 반환한다.

        :raises CatalogNotFound: 해당 작업이 없는 경우
        """
        async with self._sessionmaker() as session:
            jobs = JobRepository(session)
            job = await jobs.get(job_id)
            if job is None:
                raise CatalogNotFound(f"수집 작업을 찾을 수 없습니다: {job_id}")
            logs = await jobs.recent_logs(job_id)

        return JobStatusResponse(
            job_id=job.job_id,
            status=job.status,
            mode=job.mode,
            params=job.params,
            total_entries=job.total_entries,
            saved_entries=job.saved_entries,
            error_message=job.error_message,
            started_at=job.started_at,
            finished_at=job.finished_at,
            logs=[JobLogItem.model_validate(log) for log in logs],
        )

    async def _start_job(self, params: dict[str, object], *, mode: str) -> ExtractResponse:
        """같은 파라미터의 진행 중 작업을 재사용하거나 새 작업을 만든다."""
        params_key = _params_key({"mode": mode, **params})

        async with self._sessionmaker() as session:
            jobs = JobRepository(session)
            existing = await jobs.find_active(params_key)
            if existing is not None:
                logger.info("이미 진행 중인 수집 작업을 재사용합니다: %s", existing.job_id)
                return ExtractResponse(
                    job_id=existing.job_id, status=existing.status, mode=existing.mode
                )

            job_id = uuid.uuid4().hex
            await jobs.create(job_id, params, params_key, mode=mode)
            await jobs.add_log(job_id, "info", "수집 작업을 등록했습니다.")
            await session.commit()

        return ExtractResponse(job_id=job_id, status="pending", mode=mode)

    async def _run_slices(
        self,
        job_id: str,
        targets: Sequence[tuple[str, str]],
        include_attachments: bool,
    ) -> None:
        """슬라이스 목록을 차례로 처리하고 작업을 마감한다."""
        async with self._sessionmaker() as session:
            jobs = JobRepository(session)
            await jobs.mark_running(job_id)
            await jobs.add_log(job_id, "info", f"슬라이스 {len(targets)}개를 처리합니다.")
            await session.commit()

        saved_total = 0
        incomplete = 0

        try:
            for report_type, slice_date in targets:
                saved, is_complete = await self._process_slice(
                    job_id, report_type, slice_date, include_attachments
                )
                saved_total += saved
                if not is_complete:
                    incomplete += 1
        except Exception as exc:  # 예기치 못한 오류만 작업 실패로 남긴다.
            logger.exception("수집 작업이 중단되었습니다: %s", job_id)
            async with self._sessionmaker() as session:
                jobs = JobRepository(session)
                await jobs.mark_failed(job_id, str(exc))
                await jobs.add_log(job_id, "error", f"수집 작업이 중단되었습니다: {exc}")
                await session.commit()
            return

        status = "succeeded" if incomplete == 0 else "partial"
        message = None if incomplete == 0 else f"미완료 슬라이스가 {incomplete}개 남아 있습니다."

        async with self._sessionmaker() as session:
            jobs = JobRepository(session)
            await jobs.mark_finished(
                job_id,
                status,
                total_entries=saved_total,
                saved_entries=saved_total,
                error_message=message,
            )
            await jobs.add_log(
                job_id,
                "info" if incomplete == 0 else "warning",
                f"엔트리 {saved_total}건을 저장했습니다. 미완료 슬라이스 {incomplete}개.",
            )
            await session.commit()

    async def _process_slice(
        self,
        job_id: str,
        report_type: str,
        slice_date: str,
        include_attachments: bool,
    ) -> tuple[int, bool]:
        """하루치 슬라이스를 처리하고 (저장 엔트리 수, 완료 여부)를 반환한다."""
        async with self._sessionmaker() as session:
            slices = SliceRepository(session)
            slice_row = await slices.get_or_create_slice(report_type, slice_date)
            slice_id = slice_row.slice_id
            await slices.mark_slice_status(slice_id, "running")
            await session.commit()

        day_request = CollectRequest(
            report_type=report_type,
            start_date=slice_date,
            end_date=slice_date,
            include_attachments=include_attachments,
        )

        try:
            listed = await self._collector.list_disclosures(day_request)
        except Exception as exc:
            logger.warning("%s 목록 수집 실패: %s", slice_date, exc)
            async with self._sessionmaker() as session:
                await SliceRepository(session).mark_slice_status(slice_id, "failed")
                await JobRepository(session).add_log(
                    job_id, "error", f"{slice_date} 목록 수집에 실패했습니다: {exc}"
                )
                await session.commit()
            return 0, False

        async with self._sessionmaker() as session:
            await SliceRepository(session).set_listed(slice_id, listed.listed_count, job_id)
            await JobRepository(session).add_log(
                job_id, "info", f"{slice_date} 목록 {listed.listed_count}건을 확인했습니다."
            )
            await session.commit()

        saved_total = 0
        for item in listed.items:
            saved_total += await self._process_disclosure(
                job_id, slice_id, item, include_attachments
            )

        async with self._sessionmaker() as session:
            updated = await SliceRepository(session).evaluate_complete(slice_id)
            is_complete = updated.status == "complete"
            await JobRepository(session).add_log(
                job_id,
                "info" if is_complete else "warning",
                (
                    f"{slice_date} 완전성: 목록 {updated.listed_count}건 중 "
                    f"성공 {updated.succeeded}건, 실패 {updated.failed_count}건"
                ),
            )
            await session.commit()

        return saved_total, is_complete

    async def _process_disclosure(
        self,
        job_id: str,
        slice_id: str,
        item: DisclosureListItem,
        include_attachments: bool,
    ) -> int:
        """공시 1건을 파싱해 저장한다. 이미 성공한 공시는 건너뛴다."""
        async with self._sessionmaker() as session:
            slices = SliceRepository(session)
            attempt = await slices.get_attempt(item.rcept_no)
            if attempt is not None and attempt.status == "succeeded":
                await slices.reassign_attempt(item.rcept_no, slice_id)
                await session.commit()
                return 0

        try:
            records = await self._collector.extract_disclosure(
                item, include_attachments=include_attachments
            )
        except Exception as exc:
            logger.warning("공시 %s 상세 파싱 실패: %s", item.rcept_no, exc)
            async with self._sessionmaker() as session:
                await SliceRepository(session).upsert_attempt(
                    rcept_no=item.rcept_no,
                    slice_id=slice_id,
                    report_type=item.report_type,
                    status="failed",
                    last_error=str(exc),
                )
                await JobRepository(session).add_log(
                    job_id, "warning", f"공시 {item.rcept_no} 처리에 실패했습니다: {exc}"
                )
                await session.commit()
            return 0

        async with self._sessionmaker() as session:
            saved = await EntryRepository(session).upsert_many(records)
            await DisclosureRepository(session).upsert_many(disclosures_from_records(records))
            await SliceRepository(session).upsert_attempt(
                rcept_no=item.rcept_no,
                slice_id=slice_id,
                report_type=item.report_type,
                status="succeeded",
                entry_count=saved,
            )
            await session.commit()

        return saved
