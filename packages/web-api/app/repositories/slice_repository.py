"""날짜 슬라이스·공시 시도 체크포인트 영속화."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.slice_progress import DisclosureAttempt, SliceProgress

# 재개(resume) 대상이 되는 슬라이스 상태
RESUMABLE_STATUSES = ("pending", "running", "blocked", "failed")


def _now() -> datetime:
    """UTC 기준 현재 시각."""
    return datetime.now(timezone.utc)


class SliceRepository:
    """슬라이스 진행 상황과 공시별 시도 결과를 기록·집계한다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_slice(self, report_type: str, slice_date: str) -> SliceProgress:
        """`report_type × 날짜` 슬라이스를 가져오고 없으면 만든다."""
        statement = (
            select(SliceProgress)
            .where(SliceProgress.report_type == report_type)
            .where(SliceProgress.slice_date == slice_date)
        )
        existing = (await self._session.execute(statement)).scalars().first()
        if existing is not None:
            return existing

        slice_row = SliceProgress(
            slice_id=uuid.uuid4().hex,
            report_type=report_type,
            slice_date=slice_date,
            status="pending",
        )
        self._session.add(slice_row)
        await self._session.flush()
        return slice_row

    async def get_slice(self, slice_id: str) -> SliceProgress | None:
        """슬라이스를 조회한다. 없으면 None."""
        return await self._session.get(SliceProgress, slice_id)

    async def set_listed(self, slice_id: str, listed_count: int, job_id: str) -> None:
        """원천 목록 총건수를 확정하고 처리 중인 작업을 기록한다."""
        slice_row = await self._require_slice(slice_id)
        slice_row.listed_count = listed_count
        slice_row.last_job_id = job_id

    async def mark_slice_status(self, slice_id: str, status: str) -> None:
        """슬라이스 상태를 바꾼다. running으로 바꿀 때 시도 횟수를 올린다."""
        slice_row = await self._require_slice(slice_id)
        if status == "running" and slice_row.status != "running":
            slice_row.attempt += 1
            slice_row.started_at = _now()
            slice_row.finished_at = None
        slice_row.status = status
        slice_row.updated_at = _now()

    async def upsert_attempt(
        self,
        *,
        rcept_no: str,
        slice_id: str,
        report_type: str | None,
        status: str,
        entry_count: int | None = None,
        last_error: str | None = None,
    ) -> DisclosureAttempt:
        """공시 1건의 처리 결과를 기록한다. 재기록 시 시도 횟수를 올린다."""
        attempt = await self._session.get(DisclosureAttempt, rcept_no)
        if attempt is None:
            attempt = DisclosureAttempt(
                rcept_no=rcept_no,
                slice_id=slice_id,
                report_type=report_type,
                status=status,
                attempt=1,
                entry_count=entry_count or 0,
                last_error=last_error,
            )
            self._session.add(attempt)
        else:
            attempt.slice_id = slice_id
            attempt.report_type = report_type
            attempt.status = status
            attempt.attempt += 1
            if entry_count is not None:
                attempt.entry_count = entry_count
            attempt.last_error = last_error
            attempt.updated_at = _now()
        await self._session.flush()
        return attempt

    async def reassign_attempt(self, rcept_no: str, slice_id: str) -> None:
        """이미 성공한 공시를 현재 슬라이스 소속으로 옮긴다.

        같은 접수번호가 다른 날짜 목록에 나타나도 슬라이스 완전성 계산이 어긋나지 않게 한다.
        재파싱은 하지 않으므로 시도 횟수는 올리지 않는다.
        """
        attempt = await self._session.get(DisclosureAttempt, rcept_no)
        if attempt is None or attempt.slice_id == slice_id:
            return
        attempt.slice_id = slice_id
        attempt.updated_at = _now()
        await self._session.flush()

    async def get_attempt(self, rcept_no: str) -> DisclosureAttempt | None:
        """공시 1건의 마지막 처리 결과를 조회한다."""
        return await self._session.get(DisclosureAttempt, rcept_no)

    async def list_attempts(self, slice_id: str) -> list[DisclosureAttempt]:
        """슬라이스에 속한 공시 시도 기록을 접수번호 순으로 반환한다."""
        statement = (
            select(DisclosureAttempt)
            .where(DisclosureAttempt.slice_id == slice_id)
            .order_by(DisclosureAttempt.rcept_no)
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def count_succeeded_in(self, slice_id: str, rcept_nos: Sequence[str]) -> int:
        """주어진 접수번호 중 이미 성공한 건수를 센다."""
        if not rcept_nos:
            return 0
        statement = (
            select(func.count())
            .select_from(DisclosureAttempt)
            .where(DisclosureAttempt.slice_id == slice_id)
            .where(DisclosureAttempt.status == "succeeded")
            .where(DisclosureAttempt.rcept_no.in_(list(rcept_nos)))
        )
        return int((await self._session.execute(statement)).scalar_one())

    async def recompute_counts(self, slice_id: str) -> SliceProgress:
        """공시 시도 기록에서 attempted·succeeded·failed_count를 다시 계산한다."""
        slice_row = await self._require_slice(slice_id)
        statement = (
            select(DisclosureAttempt.status, func.count())
            .where(DisclosureAttempt.slice_id == slice_id)
            .group_by(DisclosureAttempt.status)
        )
        counts = {status: count for status, count in (await self._session.execute(statement)).all()}

        slice_row.attempted = sum(counts.values())
        slice_row.succeeded = counts.get("succeeded", 0)
        slice_row.failed_count = counts.get("failed", 0) + counts.get("blocked", 0)
        slice_row.updated_at = _now()
        await self._session.flush()
        return slice_row

    async def evaluate_complete(self, slice_id: str) -> SliceProgress:
        """완전성 조건을 만족하면 슬라이스를 complete로 마감한다.

        조건은 `listed_count`가 확정되고, 성공 건수가 그와 같으며, 실패가 없을 때다.
        여기서 성공 건수에는 이번 실행에서 건너뛴(이미 성공한) 공시도 포함된다.
        """
        slice_row = await self.recompute_counts(slice_id)
        is_complete = (
            slice_row.listed_count is not None
            and slice_row.succeeded == slice_row.listed_count
            and slice_row.failed_count == 0
        )
        if is_complete:
            slice_row.status = "complete"
            slice_row.finished_at = _now()
        elif slice_row.status == "running":
            slice_row.status = "failed" if slice_row.failed_count else "pending"
        slice_row.updated_at = _now()
        await self._session.flush()
        return slice_row

    async def list_slices(
        self,
        *,
        report_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
    ) -> list[SliceProgress]:
        """슬라이스 목록을 최신 날짜순으로 반환한다."""
        statement = select(SliceProgress)
        if report_type:
            statement = statement.where(SliceProgress.report_type == report_type)
        if start_date:
            statement = statement.where(SliceProgress.slice_date >= start_date)
        if end_date:
            statement = statement.where(SliceProgress.slice_date <= end_date)
        statement = statement.order_by(SliceProgress.slice_date.desc()).limit(limit)
        return list((await self._session.execute(statement)).scalars().all())

    async def list_incomplete(
        self,
        *,
        report_type: str | None = None,
        slice_id: str | None = None,
    ) -> list[SliceProgress]:
        """재개해야 할 슬라이스를 오래된 날짜순으로 반환한다."""
        statement = select(SliceProgress).where(SliceProgress.status != "complete")
        if report_type:
            statement = statement.where(SliceProgress.report_type == report_type)
        if slice_id:
            statement = statement.where(SliceProgress.slice_id == slice_id)
        statement = statement.order_by(SliceProgress.slice_date)
        return list((await self._session.execute(statement)).scalars().all())

    async def _require_slice(self, slice_id: str) -> SliceProgress:
        """슬라이스를 조회하고 없으면 예외를 발생시킨다."""
        slice_row = await self.get_slice(slice_id)
        if slice_row is None:
            raise ValueError(f"수집 슬라이스를 찾을 수 없습니다: {slice_id}")
        return slice_row
