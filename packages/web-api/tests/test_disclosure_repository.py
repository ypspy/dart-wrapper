"""DisclosureRepository upsert·keyset·필터·backfill 테스트."""

from __future__ import annotations

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.models.disclosure import Disclosure
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.entry_repository import EntryRepository
from app.schemas.entry import EntryRecord


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def _disclosure(
    rcept_no: str,
    rcept_dt: str,
    *,
    corp_name: str = "회사",
    report_type: str = "F001",
    entry_count: int = 1,
) -> Disclosure:
    return Disclosure(
        rcept_no=rcept_no,
        corp_code="001",
        corp_name=corp_name,
        report_nm="감사보고서",
        report_type=report_type,
        rcept_dt=rcept_dt,
        entry_count=entry_count,
        disclosure_url="https://example.com",
    )


async def test_upsert_updates_entry_count(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repo = DisclosureRepository(session)
        await repo.upsert_many([_disclosure("r1", "20260724", entry_count=2)])
        await session.commit()

    async with sessionmaker_fixture() as session:
        repo = DisclosureRepository(session)
        await repo.upsert_many([_disclosure("r1", "20260724", entry_count=5)])
        await session.commit()

    async with sessionmaker_fixture() as session:
        row = await DisclosureRepository(session).get("r1")

    assert row is not None
    assert row.entry_count == 5


async def test_list_page_orders_and_cursor_tie(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repo = DisclosureRepository(session)
        await repo.upsert_many(
            [
                _disclosure("b", "20260724"),
                _disclosure("a", "20260724"),
                _disclosure("c", "20260723"),
            ]
        )
        await session.commit()

    async with sessionmaker_fixture() as session:
        repo = DisclosureRepository(session)
        first = await repo.list_page(limit=2)
        assert [row.rcept_no for row in first] == ["b", "a"]

        page2 = await repo.list_page(limit=2, cursor_rcept_dt="20260724", cursor_rcept_no="a")
        assert [row.rcept_no for row in page2] == ["c"]


async def test_list_page_filters(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repo = DisclosureRepository(session)
        await repo.upsert_many(
            [
                _disclosure("r1", "20260720", corp_name="삼성전자", report_type="F001"),
                _disclosure("r2", "20260725", corp_name="LG전자", report_type="A001"),
            ]
        )
        await session.commit()

    async with sessionmaker_fixture() as session:
        repo = DisclosureRepository(session)
        by_name = await repo.list_page(limit=10, corp_name="삼성")
        by_type = await repo.list_page(limit=10, report_type="A001")
        by_date = await repo.list_page(limit=10, start_date="20260724", end_date="20260730")

    assert [row.rcept_no for row in by_name] == ["r1"]
    assert [row.rcept_no for row in by_type] == ["r2"]
    assert [row.rcept_no for row in by_date] == ["r2"]


async def test_backfill_from_entries_is_idempotent(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        await EntryRepository(session).upsert_many(
            [
                EntryRecord(
                    entry_id="e1",
                    rcept_no="rcp1",
                    report_type="F001",
                    corp_name="테스트",
                    rcept_dt="20260724",
                    source="body",
                    section_name="재무상태표",
                    path=["감사보고서", "재무상태표"],
                    viewer_url="https://example.com/1",
                ),
                EntryRecord(
                    entry_id="e2",
                    rcept_no="rcp1",
                    report_type="F001",
                    corp_name="테스트",
                    rcept_dt="20260724",
                    source="body",
                    section_name="주석",
                    path=["감사보고서", "주석"],
                    viewer_url="https://example.com/2",
                ),
            ]
        )
        await session.commit()

    async with sessionmaker_fixture() as session:
        repo = DisclosureRepository(session)
        first = await repo.backfill_from_entries()
        await session.commit()
        second = await repo.backfill_from_entries()
        await session.commit()
        row = await repo.get("rcp1")

    assert first == 1
    assert second == 1
    assert row is not None
    assert row.entry_count == 2
    assert row.corp_name == "테스트"
