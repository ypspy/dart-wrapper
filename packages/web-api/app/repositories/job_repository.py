"""수집 작업(job)과 진행 로그 영속화."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog_job import CatalogJob, CatalogJobLog

ACTIVE_STATUSES = ("pending", "running")


def _now() -> datetime:
    """UTC 기준 현재 시각."""
    return datetime.now(timezone.utc)


class JobRepository:
    """수집 작업 상태 전이와 로그 기록을 담당한다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        job_id: str,
        params: dict[str, Any],
        params_key: str,
        mode: str = "collect",
    ) -> CatalogJob:
        """대기 상태의 새 작업을 만든다."""
        job = CatalogJob(
            job_id=job_id,
            params=params,
            params_key=params_key,
            status="pending",
            mode=mode,
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def find_active(self, params_key: str) -> CatalogJob | None:
        """같은 파라미터로 진행 중인 작업이 있으면 반환한다."""
        statement = (
            select(CatalogJob)
            .where(CatalogJob.params_key == params_key)
            .where(CatalogJob.status.in_(ACTIVE_STATUSES))
            .order_by(CatalogJob.created_at.desc())
        )
        result = await self._session.execute(statement)
        return result.scalars().first()

    async def find_any_active(self) -> CatalogJob | None:
        """파라미터와 무관하게 진행 중인 작업이 있으면 반환한다."""
        statement = (
            select(CatalogJob)
            .where(CatalogJob.status.in_(ACTIVE_STATUSES))
            .order_by(CatalogJob.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(statement)
        return result.scalars().first()

    async def list_active(self) -> list[CatalogJob]:
        """pending/running 상태인 작업을 모두 반환한다."""
        statement = (
            select(CatalogJob)
            .where(CatalogJob.status.in_(ACTIVE_STATUSES))
            .order_by(CatalogJob.created_at.desc())
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def abandon_orphans(
        self,
        *,
        reason: str = "서버가 재시작되어 진행 중이던 작업을 중단했습니다. 이어하기로 재개하세요.",
    ) -> list[str]:
        """프로세스에 워커가 없는 좀비 작업을 partial로 마감한다.

        uvicorn --reload나 프로세스 종료 시 BackgroundTasks 워커는 사라지지만
        DB 상태는 running으로 남을 수 있다. 기동 시 이를 정리한다.
        """
        abandoned: list[str] = []
        for job in await self.list_active():
            await self.mark_finished(
                job.job_id,
                "partial",
                total_entries=max(job.total_entries, job.saved_entries),
                saved_entries=job.saved_entries,
                error_message=reason,
            )
            await self.add_log(job.job_id, "warning", reason)
            abandoned.append(job.job_id)
        return abandoned

    async def get(self, job_id: str) -> CatalogJob | None:
        """작업을 조회한다. 없으면 None."""
        return await self._session.get(CatalogJob, job_id)

    async def latest(self) -> CatalogJob | None:
        """가장 최근에 만들어진 작업을 반환한다. 작업이 없으면 None."""
        statement = select(CatalogJob).order_by(CatalogJob.created_at.desc()).limit(1)
        result = await self._session.execute(statement)
        return result.scalars().first()

    async def mark_running(self, job_id: str) -> None:
        """작업을 실행 중으로 전환한다."""
        job = await self._require(job_id)
        job.status = "running"
        job.started_at = _now()

    async def update_progress(
        self,
        job_id: str,
        *,
        saved_entries: int,
        total_entries: int,
    ) -> None:
        """실행 중 진행 수치를 갱신한다. 화면 폴링이 바로 반영되도록 한다."""
        job = await self._require(job_id)
        job.saved_entries = max(0, saved_entries)
        job.total_entries = max(job.saved_entries, total_entries)

    async def mark_succeeded(self, job_id: str, total_entries: int, saved_entries: int) -> None:
        """작업을 성공으로 마감하고 수집 수치를 기록한다."""
        job = await self._require(job_id)
        job.status = "succeeded"
        job.total_entries = total_entries
        job.saved_entries = saved_entries
        job.finished_at = _now()

    async def mark_finished(
        self,
        job_id: str,
        status: str,
        *,
        total_entries: int,
        saved_entries: int,
        error_message: str | None = None,
    ) -> None:
        """작업을 마감한다. 미완료 슬라이스가 남으면 partial로 남긴다."""
        job = await self._require(job_id)
        job.status = status
        job.total_entries = total_entries
        job.saved_entries = saved_entries
        job.error_message = error_message
        job.finished_at = _now()

    async def mark_failed(self, job_id: str, error_message: str) -> None:
        """작업을 실패로 마감하고 원인을 기록한다."""
        job = await self._require(job_id)
        job.status = "failed"
        job.error_message = error_message
        job.finished_at = _now()

    async def add_log(self, job_id: str, level: str, message: str) -> None:
        """작업 진행 로그를 한 줄 남긴다."""
        self._session.add(CatalogJobLog(job_id=job_id, level=level, message=message))
        await self._session.flush()

    async def recent_logs(self, job_id: str, limit: int = 50) -> list[CatalogJobLog]:
        """최근 로그를 최신순으로 반환한다."""
        statement = (
            select(CatalogJobLog)
            .where(CatalogJobLog.job_id == job_id)
            .order_by(CatalogJobLog.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def _require(self, job_id: str) -> CatalogJob:
        """작업을 조회하고 없으면 예외를 발생시킨다."""
        job = await self.get(job_id)
        if job is None:
            raise ValueError(f"수집 작업을 찾을 수 없습니다: {job_id}")
        return job
