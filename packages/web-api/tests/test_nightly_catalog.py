"""야간 수집 계획: 어제 우선, 이어서 과거로, 한 프로세스에서 직렬."""

from __future__ import annotations

from datetime import date

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import SourceFetchError
from app.ports.entry_collector import CollectRequest, DisclosureListItem, DisclosureListResult
from app.repositories.entry_repository import EntryRepository
from app.repositories.slice_repository import SliceRepository
from app.schemas.entry import EntryRecord
from app.services.catalog_service import CatalogService
from app.services.nightly_catalog import (
    plan_nightly_targets,
    plan_recollect_targets,
    run_nightly,
    run_recollect,
)


def test_plan_puts_yesterday_before_backward_backfill() -> None:
    yesterday = date(2026, 7, 25)
    targets = plan_nightly_targets(
        report_types=("F001", "F004"),
        yesterday=yesterday,
        floor=date(2026, 7, 23),
        complete={("F001", "20260724")},
        backfill=True,
    )

    assert targets == [
        ("F001", "20260725"),
        ("F004", "20260725"),
        ("F004", "20260724"),
        ("F001", "20260723"),
        ("F004", "20260723"),
    ]


def test_plan_without_backfill_only_covers_yesterday() -> None:
    targets = plan_nightly_targets(
        report_types=("F001",),
        yesterday=date(2026, 7, 25),
        floor=date(1999, 1, 1),
        complete=set(),
        backfill=False,
    )
    assert targets == [("F001", "20260725")]


def test_recollect_includes_closed_days_and_clips_future() -> None:
    targets = plan_recollect_targets(
        report_type="F004",
        start=date(2026, 8, 14),
        end=date(2026, 8, 16),
        yesterday=date(2026, 8, 15),
    )
    assert targets == [("F004", "20260814"), ("F004", "20260815")]


class Clock:
    """테스트가 슬라이스마다 흐르는 시간을 흉내 낸다."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class DayCollector:
    """날짜마다 공시 1건을 주고, 목록 호출 시각을 앞으로 민다."""

    def __init__(self, clock: Clock, *, step: float = 100.0) -> None:
        self.clock = clock
        self.step = step
        self.list_calls: list[str] = []

    async def collect(self, request: CollectRequest) -> list[EntryRecord]:
        raise NotImplementedError

    async def list_disclosures(self, request: CollectRequest) -> DisclosureListResult:
        self.clock.now += self.step
        self.list_calls.append(request.start_date)
        item = DisclosureListItem.model_validate(
            {
                "rcept_no": request.start_date + "000001",
                "reportType": request.report_type,
                "corp_name": "회사",
                "report_nm": "보고서",
                "rcept_dt": request.start_date,
                "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={request.start_date}",
            }
        )
        return DisclosureListResult(listed_count=1, total_known=True, items=[item])

    async def extract_disclosure(
        self,
        disclosure: DisclosureListItem,
        *,
        include_attachments: bool = True,
    ) -> list[EntryRecord]:
        return [
            EntryRecord(
                entry_id=f"{disclosure.rcept_no}_1_1",
                rcept_no=disclosure.rcept_no,
                report_type=disclosure.report_type,
                source="body",
                section_name="본문",
                path=["본문"],
                viewer_url="https://dart.fss.or.kr/report/viewer.do",
            )
        ]


class BlockingCollector(DayCollector):
    """상세가 항상 차단이다. 연속 차단 임계를 넘기도록 목록은 2건이다."""

    async def list_disclosures(self, request: CollectRequest) -> DisclosureListResult:
        self.list_calls.append(request.start_date)
        items = [
            DisclosureListItem.model_validate(
                {
                    "rcept_no": f"{request.start_date}{suffix}",
                    "reportType": request.report_type,
                    "corp_name": "회사",
                    "report_nm": "보고서",
                    "rcept_dt": request.start_date,
                    "url": (
                        "https://dart.fss.or.kr/dsaf001/main.do"
                        f"?rcpNo={request.start_date}{suffix}"
                    ),
                }
            )
            for suffix in ("000001", "000002")
        ]
        return DisclosureListResult(listed_count=2, total_known=True, items=items)

    async def extract_disclosure(
        self,
        disclosure: DisclosureListItem,
        *,
        include_attachments: bool = True,
    ) -> list[EntryRecord]:
        raise SourceFetchError("요청이 차단되었습니다(HTTP 429)")


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def _service(sessionmaker, collector, clock: Clock) -> CatalogService:
    return CatalogService(
        sessionmaker,
        collector,
        max_retries=1,
        retry_backoff_seconds=0.0,
        block_streak_threshold=2,
        block_wait_seconds=60.0,
        clock=lambda: date(2026, 7, 26),
        monotonic=clock.monotonic,
    )


async def test_nightly_runs_yesterday_then_backfill_until_budget(sessionmaker_fixture) -> None:
    clock = Clock()
    collector = DayCollector(clock)
    service = _service(sessionmaker_fixture, collector, clock)

    outcome = await run_nightly(
        service,
        sessionmaker_fixture,
        report_types=("F001",),
        yesterday=date(2026, 7, 25),
        floor=date(2026, 7, 23),
        budget_seconds=150,
    )

    assert collector.list_calls == ["20260725", "20260724"]
    assert outcome.status == "partial"
    assert outcome.stopped == "budget"


async def test_nightly_stops_on_block_before_older_dates(sessionmaker_fixture) -> None:
    clock = Clock()
    collector = BlockingCollector(clock, step=0)
    service = _service(sessionmaker_fixture, collector, clock)

    outcome = await run_nightly(
        service,
        sessionmaker_fixture,
        report_types=("F001",),
        yesterday=date(2026, 7, 25),
        floor=date(2026, 7, 23),
        budget_seconds=None,
    )

    assert collector.list_calls == ["20260725"]
    assert outcome.stopped == "blocked"
    assert outcome.status == "partial"


async def test_recollect_revisits_complete_slice(sessionmaker_fixture) -> None:
    clock = Clock()
    collector = DayCollector(clock, step=0)
    service = _service(sessionmaker_fixture, collector, clock)
    await run_nightly(
        service,
        sessionmaker_fixture,
        report_types=("F004",),
        yesterday=date(2026, 7, 24),
        floor=date(2026, 7, 24),
        budget_seconds=None,
        backfill=False,
    )
    collector.list_calls.clear()

    outcome = await run_recollect(
        service,
        sessionmaker_fixture,
        report_type="F004",
        start=date(2026, 7, 24),
        end=date(2026, 7, 25),
        yesterday=date(2026, 7, 25),
    )

    assert collector.list_calls == ["20260724", "20260725"]
    assert outcome.status == "succeeded"


class TimedDisclosureCollector:
    """날짜마다 공시 여러 건을 주고, 상세를 받을 때마다 시계를 앞으로 민다.

    목록 조회는 시간을 쓰지 않는다. 한도가 공시 경계에서 걸리는지 보려면
    시간이 상세 처리 중에만 흘러야 한다.
    """

    def __init__(self, clock: Clock, *, per_day: int, step: float) -> None:
        self.clock = clock
        self.per_day = per_day
        self.step = step
        self.list_calls: list[str] = []
        self.extract_calls: list[str] = []

    async def collect(self, request: CollectRequest) -> list[EntryRecord]:
        raise NotImplementedError

    async def list_disclosures(self, request: CollectRequest) -> DisclosureListResult:
        self.list_calls.append(request.start_date)
        items = [
            DisclosureListItem.model_validate(
                {
                    "rcept_no": f"{request.start_date}{index:06d}",
                    "reportType": request.report_type,
                    "corp_name": "회사",
                    "report_nm": "보고서",
                    "rcept_dt": request.start_date,
                    "url": (
                        "https://dart.fss.or.kr/dsaf001/main.do"
                        f"?rcpNo={request.start_date}{index:06d}"
                    ),
                }
            )
            for index in range(1, self.per_day + 1)
        ]
        return DisclosureListResult(listed_count=self.per_day, total_known=True, items=items)

    async def extract_disclosure(
        self,
        disclosure: DisclosureListItem,
        *,
        include_attachments: bool = True,
    ) -> list[EntryRecord]:
        self.clock.now += self.step
        self.extract_calls.append(disclosure.rcept_no)
        return [
            EntryRecord(
                entry_id=f"{disclosure.rcept_no}_1_1",
                rcept_no=disclosure.rcept_no,
                report_type=disclosure.report_type,
                source="body",
                section_name="본문",
                path=["본문"],
                viewer_url="https://dart.fss.or.kr/report/viewer.do",
            )
        ]


def _rcept_nos(slice_date: str, start: int, end: int) -> list[str]:
    """하루 목록에서 start 이상 end 이하 순번의 접수번호를 만든다."""
    return [f"{slice_date}{index:06d}" for index in range(start, end + 1)]


async def test_budget_stops_inside_large_slice_after_current_disclosure(
    sessionmaker_fixture,
) -> None:
    """큰 날짜 슬라이스도 공시를 시작하기 전에 한도를 넘기면 그 공시 앞에서 멈춘다.

    시계는 상세 1건마다 100초. 한도 250초이면 3건째를 끝낸 뒤 4건째는
    시작하지 않는다. 다음 날짜도 열지 않고, 멈춘 이유는 budget이다.
    잘라낸 슬라이스는 완료로 닫지 않는다.
    """
    clock = Clock()
    collector = TimedDisclosureCollector(clock, per_day=5, step=100.0)
    service = _service(sessionmaker_fixture, collector, clock)

    outcome = await run_nightly(
        service,
        sessionmaker_fixture,
        report_types=("F001",),
        yesterday=date(2026, 7, 25),
        floor=date(2026, 7, 24),
        budget_seconds=250,
    )

    assert outcome.stopped == "budget"
    assert outcome.status == "partial"
    assert collector.list_calls == ["20260725"]
    assert collector.extract_calls == _rcept_nos("20260725", 1, 3)
    assert outcome.job_id is not None

    async with sessionmaker_fixture() as session:
        row = await SliceRepository(session).find_slice("F001", "20260725")
        entries = EntryRepository(session)
        saved = [
            await entries.list_by_rcept_no(rcept_no) for rcept_no in _rcept_nos("20260725", 1, 3)
        ]
        not_saved = await entries.list_by_rcept_no("20260725000004")
    assert row is not None
    assert row.status != "complete"
    assert row.succeeded == 3
    assert row.listed_count == 5
    assert all(saved)
    assert not_saved == []

    status = await service.get_status(outcome.job_id)
    assert any(
        log.message == "시간 한도에 도달해 남은 슬라이스를 다음 실행으로 넘깁니다."
        for log in status.logs
    )


async def test_next_night_resumes_partial_slice_and_skips_succeeded(
    sessionmaker_fixture,
) -> None:
    """다음 실행은 잘린 슬라이스를 다시 열고, 이미 성공한 접수번호는 다시 받지 않는다."""
    clock = Clock()
    collector = TimedDisclosureCollector(clock, per_day=5, step=100.0)
    service = _service(sessionmaker_fixture, collector, clock)
    common = {
        "report_types": ("F001",),
        "yesterday": date(2026, 7, 25),
        "floor": date(2026, 7, 25),
        "backfill": False,
    }

    first = await run_nightly(
        service,
        sessionmaker_fixture,
        budget_seconds=250,
        **common,
    )
    assert first.stopped == "budget"
    assert collector.extract_calls == _rcept_nos("20260725", 1, 3)

    # 다음 밤은 새 프로세스다. 단조 시계를 되감아 새 시간 한도를 만든다.
    clock.now = 0.0
    collector.extract_calls.clear()
    collector.list_calls.clear()

    second = await run_nightly(
        service,
        sessionmaker_fixture,
        budget_seconds=1_000,
        **common,
    )

    assert second.stopped is None
    assert second.status == "succeeded"
    assert collector.list_calls == ["20260725"]
    assert collector.extract_calls == _rcept_nos("20260725", 4, 5)
    async with sessionmaker_fixture() as session:
        row = await SliceRepository(session).find_slice("F001", "20260725")
    assert row is not None
    assert row.status == "complete"
    assert row.succeeded == 5


async def test_no_budget_still_finishes_large_slice(sessionmaker_fixture) -> None:
    """예산이 없으면 공시가 많고 시계가 흘러도 슬라이스를 끝까지 완료한다."""
    clock = Clock()
    collector = TimedDisclosureCollector(clock, per_day=5, step=100.0)
    service = _service(sessionmaker_fixture, collector, clock)

    outcome = await run_nightly(
        service,
        sessionmaker_fixture,
        report_types=("F001",),
        yesterday=date(2026, 7, 25),
        floor=date(2026, 7, 24),
        budget_seconds=None,
    )

    assert outcome.stopped is None
    assert outcome.status == "succeeded"
    assert collector.list_calls == ["20260725", "20260724"]
    assert collector.extract_calls == [
        *_rcept_nos("20260725", 1, 5),
        *_rcept_nos("20260724", 1, 5),
    ]
    async with sessionmaker_fixture() as session:
        rows = await SliceRepository(session).list_slices(report_type="F001")
    assert {row.slice_date: row.status for row in rows} == {
        "20260724": "complete",
        "20260725": "complete",
    }


async def test_second_night_skips_complete_yesterday(sessionmaker_fixture) -> None:
    """재시작·다음 실행은 이미 완료된 날을 다시 받지 않고 남은 과거로 간다."""
    clock = Clock()
    collector = DayCollector(clock, step=0)
    service = _service(sessionmaker_fixture, collector, clock)
    await run_nightly(
        service,
        sessionmaker_fixture,
        report_types=("F001",),
        yesterday=date(2026, 7, 25),
        floor=date(2026, 7, 24),
        budget_seconds=None,
    )
    collector.list_calls.clear()

    await run_nightly(
        service,
        sessionmaker_fixture,
        report_types=("F001",),
        yesterday=date(2026, 7, 25),
        floor=date(2026, 7, 23),
        budget_seconds=None,
    )

    assert collector.list_calls == ["20260723"]
    async with sessionmaker_fixture() as session:
        rows = await SliceRepository(session).list_slices(report_type="F001")
    assert {row.slice_date for row in rows if row.status == "complete"} == {
        "20260723",
        "20260724",
        "20260725",
    }
