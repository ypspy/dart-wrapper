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
