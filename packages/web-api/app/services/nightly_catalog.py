"""야간 수집 계획과 실행.

스케줄러(cron, Windows 작업 스케줄러)는 앱 밖에 둔다.
이 모듈은 한 프로세스에서 어제 수집을 먼저 하고, 시간이 남으면 1999년 쪽으로
하루씩 거슬러 올라간다. 수집은 직렬이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.errors import CatalogConflict
from app.repositories.job_repository import JobRepository
from app.repositories.slice_repository import SliceRepository
from app.services.catalog_service import CatalogService, iter_dates


@dataclass(frozen=True)
class NightlyOutcome:
    """야간 실행 한 번의 결과."""

    status: str
    stopped: str | None
    job_id: str | None
    message: str


def plan_nightly_targets(
    *,
    report_types: Sequence[str],
    yesterday: date,
    floor: date,
    complete: set[tuple[str, str]],
    backfill: bool,
) -> list[tuple[str, str]]:
    """어제 유형들을 앞에 두고, 나머지는 어제 전날부터 과거로 붙인다.

    `complete`에 있는 날은 넣지 않는다. 키는 `(report_type, YYYYMMDD)`다.
    """
    if floor > yesterday:
        floor = yesterday
    targets: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(report_type: str, day: date) -> None:
        key = (report_type, day.strftime("%Y%m%d"))
        if key in seen or key in complete:
            return
        if day < floor or day > yesterday:
            return
        seen.add(key)
        targets.append(key)

    for report_type in report_types:
        add(report_type, yesterday)
    if not backfill:
        return targets

    cursor = yesterday - timedelta(days=1)
    while cursor >= floor:
        for report_type in report_types:
            add(report_type, cursor)
        cursor -= timedelta(days=1)
    return targets


def plan_recollect_targets(
    *,
    report_type: str,
    start: date,
    end: date,
    yesterday: date,
) -> list[tuple[str, str]]:
    """이미 완료된 날을 포함해 구간을 다시 수집한다. 오늘은 넣지 않는다."""
    last = min(end, yesterday)
    if last < start:
        return []
    days = iter_dates(start.strftime("%Y%m%d"), last.strftime("%Y%m%d"))
    return [(report_type, day) for day in days]


async def run_nightly(
    catalog: CatalogService,
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    report_types: Sequence[str],
    yesterday: date,
    floor: date,
    budget_seconds: float | None,
    backfill: bool = True,
    idle_seconds: float = 3600,
    now: datetime | None = None,
) -> NightlyOutcome:
    """어제를 먼저 채우고, 시간이 남으면 과거 공백을 직렬로 메운다."""
    await _abandon_idle(sessionmaker, idle_seconds=idle_seconds, now=now)
    complete = await _load_complete(sessionmaker, report_types, floor, yesterday)
    targets = plan_nightly_targets(
        report_types=report_types,
        yesterday=yesterday,
        floor=floor,
        complete=complete,
        backfill=backfill,
    )
    return await _execute(
        catalog,
        mode="nightly",
        params={
            "report_types": list(report_types),
            "yesterday": yesterday.strftime("%Y%m%d"),
            "floor": floor.strftime("%Y%m%d"),
            "backfill": backfill,
        },
        targets=targets,
        budget_seconds=budget_seconds,
        skip_complete=True,
    )


async def run_recollect(
    catalog: CatalogService,
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    report_type: str,
    start: date,
    end: date,
    yesterday: date,
    budget_seconds: float | None = None,
    idle_seconds: float = 3600,
    now: datetime | None = None,
) -> NightlyOutcome:
    """완료로 닫힌 날을 포함해 구간을 다시 목록부터 받는다."""
    await _abandon_idle(sessionmaker, idle_seconds=idle_seconds, now=now)
    targets = plan_recollect_targets(
        report_type=report_type,
        start=start,
        end=end,
        yesterday=yesterday,
    )
    return await _execute(
        catalog,
        mode="recollect",
        params={
            "report_type": report_type,
            "start_date": start.strftime("%Y%m%d"),
            "end_date": min(end, yesterday).strftime("%Y%m%d"),
        },
        targets=targets,
        budget_seconds=budget_seconds,
        skip_complete=False,
    )


async def _execute(
    catalog: CatalogService,
    *,
    mode: str,
    params: dict[str, object],
    targets: list[tuple[str, str]],
    budget_seconds: float | None,
    skip_complete: bool,
) -> NightlyOutcome:
    """잡 하나를 만들고 계획된 슬라이스만 직렬로 돈다."""
    try:
        response = await catalog._start_job(params, mode=mode)
    except CatalogConflict as exc:
        return NightlyOutcome(status="busy", stopped="busy", job_id=None, message=str(exc))
    if response.status != "pending":
        return NightlyOutcome(
            status="busy",
            stopped="busy",
            job_id=response.job_id,
            message="이미 진행 중인 수집이 있어 이번 실행은 시작하지 않았습니다.",
        )

    deadline = None
    if budget_seconds is not None:
        deadline = catalog._monotonic() + budget_seconds
    stopped = await catalog.run_planned(
        response.job_id,
        targets,
        include_attachments=True,
        deadline=deadline,
        skip_complete=skip_complete,
    )
    status = await catalog.get_status(response.job_id)
    return NightlyOutcome(
        status=status.status,
        stopped=stopped,
        job_id=status.job_id,
        message=status.error_message or "",
    )


async def _abandon_idle(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    idle_seconds: float,
    now: datetime | None,
) -> None:
    """멈춰 있는 야간·재수집 잡만 풀어 다음 실행이 이어 가게 한다."""
    async with sessionmaker() as session:
        await JobRepository(session).abandon_idle(idle_seconds=idle_seconds, now=now)
        await session.commit()


async def _load_complete(
    sessionmaker: async_sessionmaker[AsyncSession],
    report_types: Sequence[str],
    floor: date,
    yesterday: date,
) -> set[tuple[str, str]]:
    """기간 안에서 이미 완료된 (유형, 날짜)를 모은다."""
    if floor > yesterday:
        floor = yesterday
    async with sessionmaker() as session:
        rows = await SliceRepository(session).list_slices_between(
            floor.strftime("%Y%m%d"),
            yesterday.strftime("%Y%m%d"),
        )
    wanted = set(report_types)
    return {
        (row.report_type, row.slice_date)
        for row in rows
        if row.report_type in wanted and row.status == "complete"
    }
