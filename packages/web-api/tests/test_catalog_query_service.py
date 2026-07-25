"""CatalogQueryService cursor·목록·목차 테스트."""

from __future__ import annotations

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import BadRequest, CatalogNotFound
from app.models.disclosure import Disclosure
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.entry_repository import EntryRepository
from app.schemas.entry import EntryRecord
from app.services.catalog_query_service import (
    CatalogQueryService,
    decode_cursor,
    encode_cursor,
)


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def test_cursor_roundtrip() -> None:
    token = encode_cursor("20260724", "rcp1")
    assert decode_cursor(token) == ("20260724", "rcp1")


def test_decode_cursor_rejects_garbage() -> None:
    with pytest.raises(BadRequest):
        decode_cursor("!!!")


async def test_list_disclosures_paging(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repo = DisclosureRepository(session)
        await repo.upsert_many(
            [
                Disclosure(
                    rcept_no="r2",
                    rcept_dt="20260725",
                    report_type="F001",
                    entry_count=1,
                ),
                Disclosure(
                    rcept_no="r1",
                    rcept_dt="20260724",
                    report_type="F001",
                    entry_count=1,
                ),
            ]
        )
        await session.commit()

    async with sessionmaker_fixture() as session:
        service = CatalogQueryService(DisclosureRepository(session), EntryRepository(session))
        page1 = await service.list_disclosures(limit=1)
        assert [item.rcp_no for item in page1.items] == ["r2"]
        assert page1.next_cursor is not None

        page2 = await service.list_disclosures(limit=1, cursor=page1.next_cursor)
        assert [item.rcp_no for item in page2.items] == ["r1"]
        assert page2.next_cursor is None


async def test_list_entries_splits_primary(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        await DisclosureRepository(session).upsert_many(
            [
                Disclosure(
                    rcept_no="rcp1",
                    rcept_dt="20260724",
                    report_type="F001",
                    entry_count=2,
                )
            ]
        )
        await EntryRepository(session).upsert_many(
            [
                EntryRecord(
                    entry_id="e1",
                    rcept_no="rcp1",
                    source="body",
                    dcm_no="1",
                    ele_id="1",
                    section_name="재무상태표",
                    path=["감사보고서", "재무상태표"],
                    viewer_url="https://example.com/1",
                ),
                EntryRecord(
                    entry_id="e2",
                    rcept_no="rcp1",
                    source="body",
                    dcm_no="1",
                    ele_id="2",
                    section_name="감사인의 감사보고서",
                    path=["감사보고서"],
                    viewer_url="https://example.com/2",
                ),
            ]
        )
        await session.commit()

    async with sessionmaker_fixture() as session:
        service = CatalogQueryService(DisclosureRepository(session), EntryRepository(session))
        result = await service.list_entries("rcp1")

    assert [item.entry_id for item in result.primary_entries] == ["e1"]
    assert [item.entry_id for item in result.all_entries] == ["e1", "e2"]
    primary_ids = {item.entry_id for item in result.primary_entries}
    all_ids = {item.entry_id for item in result.all_entries}
    assert primary_ids <= all_ids


async def test_get_disclosure_missing(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        service = CatalogQueryService(DisclosureRepository(session), EntryRepository(session))
        with pytest.raises(CatalogNotFound):
            await service.get_disclosure("없는번호")
