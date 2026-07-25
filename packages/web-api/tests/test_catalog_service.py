"""CatalogService 수집 실행·상태 조회 테스트."""

from __future__ import annotations

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import CatalogNotFound, SourceFetchError
from app.ports.entry_collector import CollectRequest, DisclosureListItem, DisclosureListResult
from app.schemas.catalog import ExtractRequest
from app.schemas.entry import EntryRecord
from app.services.catalog_service import CatalogService

REQUEST = ExtractRequest(report_type="F001", start_date="20260724", end_date="20260724")


class FakeCollector:
    """고정 목록·엔트리를 돌려주는 가짜 수집기."""

    def __init__(self) -> None:
        self.calls: list[CollectRequest] = []

    async def list_disclosures(self, request: CollectRequest) -> DisclosureListResult:
        self.calls.append(request)
        items = [
            DisclosureListItem(
                rcept_no="20260724000650",
                report_type="F001",
                corp_name="테스트",
                rcept_dt="20260724",
                url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260724000650",
            ),
            DisclosureListItem(
                rcept_no="20260725000001",
                report_type="F001",
                corp_name="다른회사",
                rcept_dt="20260725",
                url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260725000001",
            ),
        ]
        return DisclosureListResult(listed_count=len(items), items=items)

    async def extract_disclosure(
        self,
        disclosure: DisclosureListItem,
        *,
        include_attachments: bool = True,
    ) -> list[EntryRecord]:
        return [
            record
            for record in await self.collect(
                CollectRequest(report_type="F001", start_date="20260724", end_date="20260724")
            )
            if record.rcept_no == disclosure.rcept_no
        ]

    async def collect(self, request: CollectRequest) -> list[EntryRecord]:
        return [
            EntryRecord(
                entry_id="e_1",
                rcept_no="20260724000650",
                report_type="F001",
                corp_name="테스트",
                rcept_dt="20260724",
                source="body",
                section_name="재무상태표",
                path=["감사보고서", "재무상태표"],
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=1",
            ),
            EntryRecord(
                entry_id="e_2",
                rcept_no="20260724000650",
                report_type="F001",
                corp_name="테스트",
                rcept_dt="20260724",
                source="body",
                section_name="주석",
                path=["감사보고서", "주석"],
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=1",
            ),
            EntryRecord(
                entry_id="e_3",
                rcept_no="20260725000001",
                report_type="F001",
                corp_name="다른회사",
                rcept_dt="20260725",
                source="body",
                section_name="재무상태표",
                path=["감사보고서", "재무상태표"],
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=2",
            ),
        ]


class FailingCollector:
    """목록 조회부터 실패하는 가짜 수집기."""

    async def list_disclosures(self, request: CollectRequest) -> DisclosureListResult:
        raise SourceFetchError("엔트리 수집 프로세스가 비정상 종료했습니다(코드 1)")

    async def extract_disclosure(
        self,
        disclosure: DisclosureListItem,
        *,
        include_attachments: bool = True,
    ) -> list[EntryRecord]:
        raise SourceFetchError("상세 파싱에 실패했습니다.")

    async def collect(self, request: CollectRequest) -> list[EntryRecord]:
        raise SourceFetchError("엔트리 수집 프로세스가 비정상 종료했습니다(코드 1)")


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


async def test_start_extract_creates_pending_job(sessionmaker_fixture) -> None:
    service = CatalogService(sessionmaker_fixture, FakeCollector())

    response = await service.start_extract(REQUEST)

    assert response.status == "pending"
    assert response.job_id


async def test_start_extract_reuses_active_job(sessionmaker_fixture) -> None:
    service = CatalogService(sessionmaker_fixture, FakeCollector())

    first = await service.start_extract(REQUEST)
    second = await service.start_extract(REQUEST)

    assert first.job_id == second.job_id


async def test_run_job_saves_entries_and_marks_success(sessionmaker_fixture) -> None:
    collector = FakeCollector()
    service = CatalogService(sessionmaker_fixture, collector)
    response = await service.start_extract(REQUEST)

    await service.run_job(response.job_id, REQUEST)
    status = await service.get_status(response.job_id)

    assert status.status == "succeeded"
    assert (status.total_entries, status.saved_entries) == (3, 3)
    assert collector.calls[0].report_type == "F001"

    from app.repositories.disclosure_repository import DisclosureRepository

    async with sessionmaker_fixture() as session:
        d1 = await DisclosureRepository(session).get("20260724000650")
        d2 = await DisclosureRepository(session).get("20260725000001")

    assert d1 is not None and d1.entry_count == 2
    assert d2 is not None and d2.entry_count == 1
    assert any("수집" in log.message for log in status.logs)


async def test_run_job_reports_partial_when_slice_fails(sessionmaker_fixture) -> None:
    service = CatalogService(sessionmaker_fixture, FailingCollector())
    response = await service.start_extract(REQUEST)

    await service.run_job(response.job_id, REQUEST)
    status = await service.get_status(response.job_id)

    # 목록 수집이 실패해도 작업은 끝까지 돌고, 미완료 슬라이스만 남긴다.
    assert status.status == "partial"
    assert status.error_message is not None
    assert any(log.level == "error" for log in status.logs)


async def test_get_status_raises_for_unknown_job(sessionmaker_fixture) -> None:
    service = CatalogService(sessionmaker_fixture, FakeCollector())

    with pytest.raises(CatalogNotFound):
        await service.get_status("없는-작업")
