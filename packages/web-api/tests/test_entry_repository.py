"""EntryRepository upsert·조회 테스트."""

from __future__ import annotations

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.repositories.entry_repository import EntryRepository
from app.schemas.entry import EntryRecord


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def _record(entry_id: str, section_name: str) -> EntryRecord:
    return EntryRecord(
        entry_id=entry_id,
        rcept_no="20260724000650",
        source="body",
        dcm_no="11495035",
        ele_id=entry_id.rsplit("_", 1)[-1],
        section_name=section_name,
        path=["감사보고서", section_name],
        viewer_url=f"https://dart.fss.or.kr/report/viewer.do?rcpNo={entry_id}",
    )


async def test_upsert_many_inserts_then_updates(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = EntryRepository(session)
        saved = await repository.upsert_many([_record("a_1", "재무상태표")])
        await session.commit()

    assert saved == 1

    async with sessionmaker_fixture() as session:
        repository = EntryRepository(session)
        saved = await repository.upsert_many([_record("a_1", "손익계산서")])
        await session.commit()

    async with sessionmaker_fixture() as session:
        repository = EntryRepository(session)
        entries = await repository.list_by_rcept_no("20260724000650")

    assert saved == 1
    assert len(entries) == 1
    assert entries[0].section_name == "손익계산서"


async def test_list_by_rcept_no_and_get_by_entry_id(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = EntryRepository(session)
        await repository.upsert_many([_record("a_2", "주석"), _record("a_1", "재무상태표")])
        await session.commit()

    async with sessionmaker_fixture() as session:
        repository = EntryRepository(session)
        entries = await repository.list_by_rcept_no("20260724000650")
        found = await repository.get_by_entry_id("a_2")
        missing = await repository.get_by_entry_id("없는값")

    assert [entry.entry_id for entry in entries] == ["a_1", "a_2"]
    assert found is not None and found.section_name == "주석"
    assert missing is None


async def test_list_extraction_document_rows_is_one_query_candidates(
    sessionmaker_fixture,
) -> None:
    """기간·유형 문서 후보를 접수마다 다시 읽지 않고 한 번에 돌려준다."""
    async with sessionmaker_fixture() as session:
        repository = EntryRepository(session)
        await repository.upsert_many(
            [
                EntryRecord(
                    entry_id="f1-cover",
                    rcept_no="20200331000001",
                    report_type="F001",
                    rcept_dt="2020.03.31",
                    source="body",
                    dcm_no="11111",
                    document_name="감사보고서",
                    section_name="표지",
                    path=["감사보고서", "표지"],
                ),
                EntryRecord(
                    entry_id="f1-opinion",
                    rcept_no="20200331000001",
                    report_type="F001",
                    rcept_dt="2020.03.31",
                    source="body",
                    dcm_no="11111",
                    document_name="감사보고서",
                    section_name="의견",
                    path=["감사보고서", "의견"],
                ),
                EntryRecord(
                    entry_id="a1-other",
                    rcept_no="20200331000002",
                    report_type="A001",
                    rcept_dt="2020.03.31",
                    source="attachment",
                    dcm_no="22222",
                    document_name="정관",
                    section_name="정관",
                    path=["정관"],
                ),
            ]
        )
        await session.commit()

    async with sessionmaker_fixture() as session:
        repository = EntryRepository(session)
        rows = await repository.list_extraction_document_rows(
            "20200301", "20200331", ["F001", "A001"]
        )

    pairs = {(row[0], row[1], row[4]) for row in rows}
    assert ("20200331000001", "11111", "감사보고서") in pairs
    assert ("20200331000002", "22222", "정관") in pairs


async def test_list_toc_orders_by_ordinal(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = EntryRepository(session)
        await repository.upsert_many(
            [
                EntryRecord(
                    entry_id="att_1",
                    rcept_no="20260724000650",
                    source="attachment",
                    dcm_no="999",
                    ele_id="1",
                    section_name="첨부",
                    path=["첨부"],
                    ordinal=0,
                    viewer_url="https://example.com/att",
                ),
                EntryRecord(
                    entry_id="body_2",
                    rcept_no="20260724000650",
                    source="body",
                    dcm_no="100",
                    ele_id="2",
                    section_name="주석",
                    path=["감사보고서", "주석"],
                    ordinal=2,
                    viewer_url="https://example.com/2",
                ),
                EntryRecord(
                    entry_id="body_1",
                    rcept_no="20260724000650",
                    source="body",
                    dcm_no="100",
                    ele_id="1",
                    section_name="재무상태표",
                    path=["감사보고서", "재무상태표"],
                    ordinal=1,
                    viewer_url="https://example.com/1",
                ),
            ]
        )
        await session.commit()

    async with sessionmaker_fixture() as session:
        toc = await EntryRepository(session).list_toc_by_rcept_no("20260724000650")

    assert [entry.entry_id for entry in toc] == ["att_1", "body_1", "body_2"]
    assert [entry.ordinal for entry in toc] == [0, 1, 2]
