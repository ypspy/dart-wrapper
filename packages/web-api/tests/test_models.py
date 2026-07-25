"""모델·세션·EntryRecord 스키마 테스트."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.models.entry import Entry
from app.schemas.entry import EntryRecord


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def test_entry_record_accepts_node_aliases() -> None:
    record = EntryRecord.model_validate(
        {
            "entry_id": "20260724000650_11495035_5",
            "rcept_no": "20260724000650",
            "reportType": "F001",
            "dcmNo": "11495035",
            "source": "body",
            "section_name": "재무상태표",
            "path": ["(첨부)재무제표", "재무상태표"],
            "viewer_url": "https://dart.fss.or.kr/report/viewer.do?rcpNo=1",
            "무시되는필드": "값",
        }
    )

    assert record.report_type == "F001"
    assert record.dcm_no == "11495035"
    assert record.path == ["(첨부)재무제표", "재무상태표"]


async def test_entry_table_roundtrip() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)

    async with sessionmaker() as session:
        session.add(
            Entry(
                entry_id="20260724000650_11495035_5",
                rcept_no="20260724000650",
                source="body",
                section_name="재무상태표",
                path=["(첨부)재무제표", "재무상태표"],
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=1",
            )
        )
        await session.commit()

    async with sessionmaker() as session:
        stored = (await session.execute(select(Entry))).scalars().all()

    assert len(stored) == 1
    assert stored[0].path == ["(첨부)재무제표", "재무상태표"]
    await engine.dispose()


async def test_disclosure_table_roundtrip(sessionmaker_fixture) -> None:
    from app.models.disclosure import Disclosure

    async with sessionmaker_fixture() as session:
        session.add(
            Disclosure(
                rcept_no="20260724000650",
                corp_code="00224628",
                corp_name="테스트",
                report_nm="감사보고서",
                report_type="F001",
                rcept_dt="20260724",
                entry_count=3,
                disclosure_url="https://example.com",
            )
        )
        await session.commit()

    async with sessionmaker_fixture() as session:
        row = await session.get(Disclosure, "20260724000650")

    assert row is not None
    assert row.entry_count == 3
    assert row.corp_name == "테스트"
