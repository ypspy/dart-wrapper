"""불연속 수집 오케스트레이션 테스트.

날짜 슬라이스와 공시 단위 체크포인트로 중복·누락 없이 재개되는지 확인한다.
"""

from __future__ import annotations

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import SourceFetchError
from app.ports.entry_collector import CollectRequest, DisclosureListItem, DisclosureListResult
from app.repositories.entry_repository import EntryRepository
from app.repositories.slice_repository import SliceRepository
from app.schemas.catalog import ExtractRequest, ResumeRequest
from app.schemas.entry import EntryRecord
from app.services.catalog_service import CatalogService

REQUEST = ExtractRequest(report_type="F001", start_date="20260724", end_date="20260724")


def _item(rcept_no: str) -> dict[str, str]:
    return {
        "rcept_no": rcept_no,
        "reportType": "F001",
        "corp_name": f"회사{rcept_no}",
        "report_nm": "감사보고서",
        "rcept_dt": "20260724",
        "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
    }


class ScriptedCollector:
    """목록은 고정, 상세는 지정한 접수번호에서 정해진 횟수만큼 실패하는 수집기."""

    def __init__(
        self,
        *,
        rcept_nos: tuple[str, ...] = ("1", "2", "3"),
        failing: dict[str, int] | None = None,
        list_error: Exception | None = None,
        error: Exception | None = None,
    ) -> None:
        self._rcept_nos = rcept_nos
        self._failing = dict(failing or {})
        self._list_error = list_error
        self._error = error
        self.list_calls: list[CollectRequest] = []
        self.extract_calls: list[str] = []

    async def collect(self, request: CollectRequest) -> list[EntryRecord]:
        raise NotImplementedError("오케스트레이터는 일괄 수집을 쓰지 않는다.")

    async def list_disclosures(self, request: CollectRequest) -> DisclosureListResult:
        self.list_calls.append(request)
        if self._list_error is not None:
            raise self._list_error
        items = [DisclosureListItem.model_validate(_item(no)) for no in self._rcept_nos]
        return DisclosureListResult(listed_count=len(items), items=items)

    async def extract_disclosure(
        self,
        disclosure: DisclosureListItem,
        *,
        include_attachments: bool = True,
    ) -> list[EntryRecord]:
        self.extract_calls.append(disclosure.rcept_no)
        remaining = self._failing.get(disclosure.rcept_no, 0)
        if remaining > 0:
            self._failing[disclosure.rcept_no] = remaining - 1
            raise self._error or SourceFetchError(
                f"상세 파싱에 실패했습니다: {disclosure.rcept_no}"
            )
        return [
            EntryRecord(
                entry_id=f"{disclosure.rcept_no}_1_5",
                rcept_no=disclosure.rcept_no,
                report_type="F001",
                corp_name=disclosure.corp_name,
                report_nm=disclosure.report_nm,
                rcept_dt=disclosure.rcept_dt,
                source="body",
                section_name="재무상태표",
                path=["감사보고서", "재무상태표"],
                viewer_url=f"https://dart.fss.or.kr/report/viewer.do?rcpNo={disclosure.rcept_no}",
            )
        ]


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def _service(sessionmaker, collector) -> CatalogService:
    """재시도·대기를 끄고 결정적으로 동작하게 만든 서비스."""
    return CatalogService(
        sessionmaker,
        collector,
        max_retries=1,
        retry_backoff_seconds=0.0,
        block_streak_threshold=99,
        block_wait_seconds=0.0,
    )


async def _slices(sessionmaker):
    async with sessionmaker() as session:
        return await SliceRepository(session).list_slices(report_type="F001")


async def test_partial_failure_keeps_succeeded_entries(sessionmaker_fixture) -> None:
    collector = ScriptedCollector(failing={"2": 1})
    service = _service(sessionmaker_fixture, collector)

    response = await service.start_extract(REQUEST)
    await service.run_job(response.job_id, REQUEST)

    rows = await _slices(sessionmaker_fixture)
    assert len(rows) == 1
    assert rows[0].status != "complete"
    assert (rows[0].listed_count, rows[0].succeeded, rows[0].failed_count) == (3, 2, 1)

    async with sessionmaker_fixture() as session:
        assert await EntryRepository(session).list_by_rcept_no("1")
        assert await EntryRepository(session).list_by_rcept_no("3")
        assert await EntryRepository(session).list_by_rcept_no("2") == []


async def test_resume_retries_only_failed_disclosure(sessionmaker_fixture) -> None:
    collector = ScriptedCollector(failing={"2": 1})
    service = _service(sessionmaker_fixture, collector)

    first = await service.start_extract(REQUEST)
    await service.run_job(first.job_id, REQUEST)
    collector.extract_calls.clear()

    resume = await service.start_resume(ResumeRequest(report_type="F001"))
    await service.run_resume_job(resume.job_id, ResumeRequest(report_type="F001"))

    assert collector.extract_calls == ["2"]

    rows = await _slices(sessionmaker_fixture)
    assert rows[0].status == "complete"
    assert (rows[0].succeeded, rows[0].failed_count) == (3, 0)

    async with sessionmaker_fixture() as session:
        assert await EntryRepository(session).list_by_rcept_no("2")


async def test_rescan_skips_already_succeeded(sessionmaker_fixture) -> None:
    collector = ScriptedCollector()
    service = _service(sessionmaker_fixture, collector)

    first = await service.start_extract(REQUEST)
    await service.run_job(first.job_id, REQUEST)
    assert sorted(collector.extract_calls) == ["1", "2", "3"]
    collector.extract_calls.clear()

    second = await service.start_extract(
        ExtractRequest(report_type="F001", start_date="20260724", end_date="20260724")
    )
    await service.run_job(second.job_id, REQUEST)

    assert collector.extract_calls == []
    rows = await _slices(sessionmaker_fixture)
    assert rows[0].status == "complete"


async def test_multi_day_range_creates_one_slice_per_day(sessionmaker_fixture) -> None:
    collector = ScriptedCollector(rcept_nos=("1",))
    service = _service(sessionmaker_fixture, collector)
    request = ExtractRequest(report_type="F001", start_date="20260723", end_date="20260725")

    response = await service.start_extract(request)
    await service.run_job(response.job_id, request)

    rows = await _slices(sessionmaker_fixture)
    assert [row.slice_date for row in rows] == ["20260725", "20260724", "20260723"]
    assert {row.status for row in rows} == {"complete"}
    assert [call.start_date for call in collector.list_calls] == [
        "20260723",
        "20260724",
        "20260725",
    ]


async def test_list_failure_marks_slice_failed_but_job_finishes(sessionmaker_fixture) -> None:
    collector = ScriptedCollector(list_error=SourceFetchError("목록 수집 실패"))
    service = _service(sessionmaker_fixture, collector)

    response = await service.start_extract(REQUEST)
    await service.run_job(response.job_id, REQUEST)
    status = await service.get_status(response.job_id)

    # 슬라이스 하나가 실패해도 작업은 끝까지 돌고, 미완료 사실만 남긴다.
    assert status.status == "partial"
    rows = await _slices(sessionmaker_fixture)
    assert rows[0].status == "failed"
    assert rows[0].listed_count is None
    assert any(log.level == "error" for log in status.logs)


async def test_transient_failure_retries_then_succeeds(sessionmaker_fixture) -> None:
    collector = ScriptedCollector(rcept_nos=("1",), failing={"1": 1})
    service = CatalogService(
        sessionmaker_fixture,
        collector,
        max_retries=3,
        retry_backoff_seconds=0.0,
        block_streak_threshold=99,
        block_wait_seconds=0.0,
    )

    response = await service.start_extract(REQUEST)
    await service.run_job(response.job_id, REQUEST)

    assert collector.extract_calls == ["1", "1"]
    rows = await _slices(sessionmaker_fixture)
    assert rows[0].status == "complete"


async def test_block_streak_marks_slice_blocked(sessionmaker_fixture) -> None:
    collector = ScriptedCollector(
        rcept_nos=("1", "2", "3"),
        failing={"1": 9, "2": 9, "3": 9},
        error=SourceFetchError("요청이 차단되었습니다(HTTP 429)"),
    )
    service = CatalogService(
        sessionmaker_fixture,
        collector,
        max_retries=1,
        retry_backoff_seconds=0.0,
        block_streak_threshold=2,
        block_wait_seconds=0.0,
    )

    response = await service.start_extract(REQUEST)
    await service.run_job(response.job_id, REQUEST)

    rows = await _slices(sessionmaker_fixture)
    assert rows[0].status == "blocked"
    # 차단이 감지되면 남은 공시는 시도하지 않고 슬라이스를 접는다.
    assert collector.extract_calls == ["1", "2"]

    status = await service.get_status(response.job_id)
    assert status.status == "partial"
    assert any("차단" in log.message for log in status.logs)


async def test_soft_stop_keeps_succeeded_and_allows_resume(sessionmaker_fixture) -> None:
    collector = ScriptedCollector(rcept_nos=("1", "2", "3"))
    service = _service(sessionmaker_fixture, collector)
    response = await service.start_extract(REQUEST)

    # 첫 공시를 처리한 직후 중단을 요청한다.
    original = service._process_disclosure

    async def stopping(job_id, slice_id, item, include_attachments):
        saved = await original(job_id, slice_id, item, include_attachments)
        await service.request_soft_stop(job_id)
        return saved

    service._process_disclosure = stopping
    await service.run_job(response.job_id, REQUEST)
    service._process_disclosure = original

    assert collector.extract_calls == ["1"]
    rows = await _slices(sessionmaker_fixture)
    assert rows[0].status != "complete"
    assert rows[0].succeeded == 1

    collector.extract_calls.clear()
    resume = await service.start_resume(ResumeRequest(report_type="F001"))
    await service.run_resume_job(resume.job_id, ResumeRequest(report_type="F001"))

    assert collector.extract_calls == ["2", "3"]
    rows = await _slices(sessionmaker_fixture)
    assert rows[0].status == "complete"


async def test_soft_stop_halts_remaining_slices(sessionmaker_fixture) -> None:
    """소프트 스톱은 현재 날짜뿐 아니라 이후 날짜 슬라이스도 건너뛴다."""
    collector = ScriptedCollector(rcept_nos=("1",))
    service = _service(sessionmaker_fixture, collector)
    request = ExtractRequest(report_type="F001", start_date="20260724", end_date="20260726")
    response = await service.start_extract(request)

    original = service._process_disclosure

    async def stop_after_first(job_id, slice_id, item, include_attachments):
        saved = await original(job_id, slice_id, item, include_attachments)
        await service.request_soft_stop(job_id)
        return saved

    service._process_disclosure = stop_after_first
    await service.run_job(response.job_id, request)
    service._process_disclosure = original

    status = await service.get_status(response.job_id)
    assert status.status == "partial"
    assert len(collector.list_calls) == 1
    assert any("남은 슬라이스" in log.message for log in status.logs)


class EmptyListCollector(ScriptedCollector):
    """총건수 확인 여부를 지정할 수 있는 빈 목록 수집기."""

    def __init__(self, *, total_known: bool) -> None:
        super().__init__(rcept_nos=())
        self._total_known = total_known

    async def list_disclosures(self, request: CollectRequest) -> DisclosureListResult:
        self.list_calls.append(request)
        return DisclosureListResult(
            listed_count=0,
            total_known=self._total_known,
            items=[],
        )


async def test_future_dates_are_not_collected(sessionmaker_fixture) -> None:
    """오늘과 미래는 슬라이스를 만들지 않는다."""
    from datetime import date

    collector = ScriptedCollector(rcept_nos=("1",))
    service = CatalogService(
        sessionmaker_fixture,
        collector,
        max_retries=1,
        retry_backoff_seconds=0.0,
        block_streak_threshold=99,
        block_wait_seconds=0.0,
        clock=lambda: date(2026, 7, 25),
    )
    request = ExtractRequest(report_type="F001", start_date="20260724", end_date="20260726")

    response = await service.start_extract(request)
    await service.run_job(response.job_id, request)

    assert [call.start_date for call in collector.list_calls] == ["20260724"]
    rows = await _slices(sessionmaker_fixture)
    assert [row.slice_date for row in rows] == ["20260724"]
    status = await service.get_status(response.job_id)
    assert any("오늘" in log.message for log in status.logs)


async def test_unknown_total_zero_is_not_complete(sessionmaker_fixture) -> None:
    """총건수 문구가 없는 0건은 완료로 닫지 않는다."""
    collector = EmptyListCollector(total_known=False)
    service = _service(sessionmaker_fixture, collector)

    response = await service.start_extract(REQUEST)
    await service.run_job(response.job_id, REQUEST)

    rows = await _slices(sessionmaker_fixture)
    assert rows[0].status == "failed"
    assert rows[0].status != "complete"
    assert rows[0].listed_count is None


async def test_confirmed_zero_on_business_day_needs_second_look(sessionmaker_fixture) -> None:
    """영업일의 확인된 0건은 한 번 더 보기 전에는 완료가 아니다."""
    collector = EmptyListCollector(total_known=True)
    service = _service(sessionmaker_fixture, collector)

    first = await service.start_extract(REQUEST)
    await service.run_job(first.job_id, REQUEST)
    rows = await _slices(sessionmaker_fixture)
    assert rows[0].slice_date == "20260724"
    assert rows[0].status == "pending"
    assert rows[0].listed_count == 0
    assert rows[0].empty_confirmations == 1

    second = await service.start_extract(REQUEST)
    await service.run_job(second.job_id, REQUEST)
    rows = await _slices(sessionmaker_fixture)
    assert rows[0].status == "complete"
    assert rows[0].empty_confirmations == 2


async def test_confirmed_zero_on_weekend_is_complete(sessionmaker_fixture) -> None:
    """주말에 총 0건이 확인되면 바로 완료한다."""
    from datetime import date

    collector = EmptyListCollector(total_known=True)
    service = CatalogService(
        sessionmaker_fixture,
        collector,
        max_retries=1,
        retry_backoff_seconds=0.0,
        block_streak_threshold=99,
        block_wait_seconds=0.0,
        clock=lambda: date(2026, 7, 26),
    )
    request = ExtractRequest(report_type="F001", start_date="20260725", end_date="20260725")

    response = await service.start_extract(request)
    await service.run_job(response.job_id, request)

    rows = await _slices(sessionmaker_fixture)
    assert rows[0].slice_date == "20260725"
    assert rows[0].status == "complete"


async def test_block_streak_stops_following_dates(sessionmaker_fixture) -> None:
    """연속 차단이면 다음 날짜로 넘어가지 않고 작업을 부분 완료로 끝낸다."""
    collector = ScriptedCollector(
        rcept_nos=("1", "2"),
        failing={"1": 9, "2": 9},
        error=SourceFetchError("요청이 차단되었습니다(HTTP 429)"),
    )
    service = CatalogService(
        sessionmaker_fixture,
        collector,
        max_retries=1,
        retry_backoff_seconds=0.0,
        block_streak_threshold=2,
        block_wait_seconds=60.0,
    )
    request = ExtractRequest(report_type="F001", start_date="20260723", end_date="20260725")

    response = await service.start_extract(request)
    await service.run_job(response.job_id, request)

    assert [call.start_date for call in collector.list_calls] == ["20260723"]
    rows = await _slices(sessionmaker_fixture)
    assert [row.slice_date for row in rows] == ["20260723"]
    assert rows[0].status == "blocked"
    status = await service.get_status(response.job_id)
    assert status.status == "partial"


async def test_job_records_disclosure_progress_counts(sessionmaker_fixture) -> None:
    collector = ScriptedCollector()
    service = _service(sessionmaker_fixture, collector)

    response = await service.start_extract(REQUEST)
    await service.run_job(response.job_id, REQUEST)
    status = await service.get_status(response.job_id)

    assert status.status == "succeeded"
    # ScriptedCollector는 공시당 엔트리 1건 → 해당일 입수/대상 = (3, 3)
    assert (status.total_entries, status.saved_entries) == (3, 3)
    assert status.params["report_type"] == "F001"
