"""추출 작업(job)과 진행 로그 영속화."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.extraction_job import ExtractionJob, ExtractionJobLog

ACTIVE_STATUSES = ("pending", "running")


def _now() -> datetime:
    """UTC 기준 현재 시각."""
    return datetime.now(timezone.utc)


class ExtractionJobRepository:
    """추출 작업 상태 전이와 로그 기록을 담당한다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        job_id: str,
        extractor_id: str,
        params: dict[str, Any] | None = None,
        mode: str = "extract",
    ) -> ExtractionJob:
        """대기 상태의 새 추출 작업을 만든다."""
        job = ExtractionJob(
            job_id=job_id,
            extractor_id=extractor_id,
            params=params or {},
            status="pending",
            mode=mode,
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def get(self, job_id: str) -> ExtractionJob | None:
        """작업 단건. 없으면 None."""
        return await self._session.get(ExtractionJob, job_id)

    async def find_latest(self, extractor_id: str) -> ExtractionJob | None:
        """해당 추출기의 가장 최근 잡."""
        statement = (
            select(ExtractionJob)
            .where(ExtractionJob.extractor_id == extractor_id)
            .order_by(
                ExtractionJob.created_at.desc(),
                ExtractionJob.job_id.desc(),
            )
            .limit(1)
        )
        result = await self._session.execute(statement)
        return result.scalars().first()

    async def update_params(self, job_id: str, params: dict[str, Any]) -> None:
        """잡 params JSON을 통째로 교체한다."""
        job = await self._require(job_id)
        job.params = params
        flag_modified(job, "params")

    async def find_any_active(
        self, extractor_id: str | None = None
    ) -> ExtractionJob | None:
        """진행 중인 추출 작업이 있으면 반환한다.

        extractor_id를 주면 해당 추출기만 본다. 감사 추출 잠금은
        `audit_opinion`만 DART로 취급하고 `resolve_dates`는 제외한다.
        """
        statement = select(ExtractionJob).where(
            ExtractionJob.status.in_(ACTIVE_STATUSES)
        )
        if extractor_id is not None:
            statement = statement.where(ExtractionJob.extractor_id == extractor_id)
        statement = statement.order_by(ExtractionJob.created_at.desc()).limit(1)
        result = await self._session.execute(statement)
        return result.scalars().first()

    async def add_log(self, job_id: str, level: str, message: str) -> None:
        """작업 진행 로그를 한 줄 남긴다."""
        self._session.add(ExtractionJobLog(job_id=job_id, level=level, message=message))
        await self._session.flush()

    async def set_status(
        self,
        job_id: str,
        status: str,
        *,
        error_message: str | None = None,
    ) -> None:
        """작업 상태를 바꾸고, 종료 시 시각과 오류 메시지를 기록한다."""
        job = await self._require(job_id)
        job.status = status
        if status == "running":
            job.started_at = _now()
        if status not in ACTIVE_STATUSES:
            job.finished_at = _now()
        if error_message is not None:
            job.error_message = error_message

    async def recent_logs(self, job_id: str, limit: int = 50) -> list[ExtractionJobLog]:
        """최근 로그를 최신순으로 반환한다."""
        statement = (
            select(ExtractionJobLog)
            .where(ExtractionJobLog.job_id == job_id)
            .order_by(ExtractionJobLog.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def _require(self, job_id: str) -> ExtractionJob:
        """작업을 조회하고 없으면 예외를 발생시킨다."""
        job = await self._session.get(ExtractionJob, job_id)
        if job is None:
            raise ValueError(f"추출 작업을 찾을 수 없습니다: {job_id}")
        return job
