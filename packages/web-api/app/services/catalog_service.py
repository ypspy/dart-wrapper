"""Admin 카탈로그 수집 서비스. 백그라운드 실행과 상태 추적을 담당한다."""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.errors import CatalogNotFound
from app.ports.entry_collector import EntryCollector
from app.repositories.entry_repository import EntryRepository
from app.repositories.job_repository import JobRepository
from app.schemas.catalog import ExtractRequest, ExtractResponse, JobLogItem, JobStatusResponse

logger = logging.getLogger(__name__)


def _params_key(request: ExtractRequest) -> str:
    """같은 범위의 중복 수집을 판별하기 위한 정규화 키를 만든다."""
    return json.dumps(request.model_dump(), sort_keys=True, ensure_ascii=False)


class CatalogService:
    """수집 작업을 만들고, 백그라운드에서 실행하며, 현황을 조회한다."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        collector: EntryCollector,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._collector = collector

    async def start_extract(self, request: ExtractRequest) -> ExtractResponse:
        """수집 작업을 등록한다. 같은 범위가 진행 중이면 기존 작업을 돌려준다."""
        params_key = _params_key(request)

        async with self._sessionmaker() as session:
            jobs = JobRepository(session)
            existing = await jobs.find_active(params_key)
            if existing is not None:
                logger.info("이미 진행 중인 수집 작업을 재사용합니다: %s", existing.job_id)
                return ExtractResponse(job_id=existing.job_id, status=existing.status)

            job_id = uuid.uuid4().hex
            await jobs.create(job_id, request.model_dump(mode="json"), params_key)
            await jobs.add_log(job_id, "info", "수집 작업을 등록했습니다.")
            await session.commit()

        return ExtractResponse(job_id=job_id, status="pending")

    async def run_job(self, job_id: str, request: ExtractRequest) -> None:
        """백그라운드에서 실제 수집을 수행한다. 예외는 작업 상태로 기록한다."""
        async with self._sessionmaker() as session:
            jobs = JobRepository(session)
            await jobs.mark_running(job_id)
            await jobs.add_log(job_id, "info", "엔트리 수집을 시작합니다.")
            await session.commit()

        try:
            records = await self._collector.collect(request)
        except Exception as exc:  # 수집 실패는 작업 실패로 남기고 서버는 계속 동작한다.
            logger.exception("수집 작업 실패: %s", job_id)
            async with self._sessionmaker() as session:
                jobs = JobRepository(session)
                await jobs.mark_failed(job_id, str(exc))
                await jobs.add_log(job_id, "error", f"수집에 실패했습니다: {exc}")
                await session.commit()
            return

        async with self._sessionmaker() as session:
            jobs = JobRepository(session)
            saved = await EntryRepository(session).upsert_many(records)
            await jobs.mark_succeeded(job_id, total_entries=len(records), saved_entries=saved)
            await jobs.add_log(job_id, "info", f"엔트리 {saved}건을 카탈로그에 저장했습니다.")
            await session.commit()

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
            params=job.params,
            total_entries=job.total_entries,
            saved_entries=job.saved_entries,
            error_message=job.error_message,
            started_at=job.started_at,
            finished_at=job.finished_at,
            logs=[JobLogItem.model_validate(log) for log in logs],
        )
