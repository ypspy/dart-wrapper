"""FactQueryService cursor·목록 테스트."""

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import BadRequest
from app.extracting.constants import EXTRACTOR_VERSION
from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
from app.repositories.fact_repository import FactRepository
from app.services.fact_query_service import (
    FactQueryService,
    decode_fact_cursor,
    encode_fact_cursor,
)


def test_fact_cursor_roundtrip() -> None:
    token = encode_fact_cursor("2026.06.01", "20260601000466", "11411460")
    assert decode_fact_cursor(token) == (
        "2026.06.01",
        "20260601000466",
        "11411460",
    )


def test_decode_fact_cursor_rejects_garbage() -> None:
    with pytest.raises(BadRequest, match="커서 값이 올바르지 않습니다"):
        decode_fact_cursor("!!!")


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


async def test_list_page_sets_next_cursor_and_maps_join(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all(
            [
                Disclosure(
                    rcept_no="r2",
                    rcept_dt="2024.03.31",
                    corp_name="을",
                    correction_type="최초공시",
                    year_end="(2023.12)",
                    entry_count=1,
                ),
                Disclosure(
                    rcept_no="r1",
                    rcept_dt="2024.03.31",
                    corp_name="갑",
                    correction_type="기재정정",
                    year_end="(2023.12)",
                    entry_count=1,
                ),
                AuditReportFact(
                    rcept_no="r2",
                    dcm_no="2",
                    source_report_type="F001",
                    fs_scope="separate",
                    fetch_status="ok",
                    extractor_version=EXTRACTOR_VERSION,
                ),
                AuditReportFact(
                    rcept_no="r1",
                    dcm_no="1",
                    source_report_type="F001",
                    fs_scope="separate",
                    fetch_status="section_missing",
                    extractor_version=EXTRACTOR_VERSION,
                ),
            ]
        )
        await session.commit()
        service = FactQueryService(FactRepository(session))
        page1 = await service.list_page(limit=1)
        assert len(page1.items) == 1
        assert page1.items[0].rcept_no == "r2"
        assert page1.items[0].corp_name == "을"
        assert page1.next_cursor is not None
        page2 = await service.list_page(limit=1, cursor=page1.next_cursor)
        assert [item.rcept_no for item in page2.items] == ["r1"]
        assert page2.items[0].fetch_status == "section_missing"
        assert page2.next_cursor is None
