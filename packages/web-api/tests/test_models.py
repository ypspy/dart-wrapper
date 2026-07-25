"""모델·세션·EntryRecord 스키마 테스트."""

from __future__ import annotations

from sqlalchemy import select

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.models.entry import Entry
from app.schemas.entry import EntryRecord


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
