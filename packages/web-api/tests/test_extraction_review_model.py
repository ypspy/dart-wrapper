"""extraction_reviews 테이블 왕복."""

from __future__ import annotations

from sqlalchemy import select

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.models.extraction_review import ExtractionReview


async def test_extraction_review_roundtrip() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        session.add(
            ExtractionReview(
                rcept_no="20200331000001",
                dcm_no="11111",
                bundle="accounts",
                signal="iqr_high",
                subject="total_asset",
                extractor_version="audit_opinion.v19",
                in_research_panel=True,
                stratum="F001|separate|total_asset",
                tail="high",
                queue_order=1,
                raw_value="1000",
                active=True,
                verdict="hold",
                tag="",
                note="",
            )
        )
        await session.commit()
    async with sessionmaker() as session:
        stored = (await session.execute(select(ExtractionReview))).scalar_one()
    assert stored.verdict == "hold"
    assert stored.queue_order == 1
    await engine.dispose()
