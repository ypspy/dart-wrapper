"""interim_review_facts 저장소와 기동 스키마 제외 테스트."""

from __future__ import annotations

from sqlalchemy import text

from app.db.session import create_all, create_db_engine, create_sessionmaker, ensure_schema
from research.extracting.interim_review import INTERIM_EXTRACTOR_VERSION
from research.models.interim_review_fact import InterimReviewFact
from research.repositories.interim_fact_repository import InterimFactRepository
from research.schema import _COLUMN_PATCHES, ensure_research_schema


async def _sessionmaker():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    return engine, create_sessionmaker(engine)


def _fact(**overrides: object) -> InterimReviewFact:
    values: dict[str, object] = {
        "rcept_no": "20250814000001",
        "dcm_no": "90001",
        "source_report_type": "A002",
        "review_kind": "half",
        "fs_scope": "separate",
        "doc_kind": "review",
        "fetch_status": "ok",
        "conclusion_code": "unmodified",
        "conclusion_status": "ok",
        "conflicts": [],
        "review_report_date_candidates": [],
        "emphasis_of_matter": False,
        "going_concern": False,
        "extractor_version": INTERIM_EXTRACTOR_VERSION,
    }
    values.update(overrides)
    return InterimReviewFact(**values)


async def test_upsert_inserts_and_updates_without_operator_columns() -> None:
    """같은 키는 merge로 덮어 쓰고, 운영자 보정 열은 없다."""
    engine, sessionmaker = await _sessionmaker()
    async with sessionmaker() as session:
        repo = InterimFactRepository(session)
        await repo.upsert(_fact())
        await session.commit()

    async with sessionmaker() as session:
        repo = InterimFactRepository(session)
        await repo.upsert(_fact(conclusion_code="qualified", conclusion_status="ok"))
        await session.commit()

    async with sessionmaker() as session:
        loaded = await InterimFactRepository(session).get("20250814000001", "90001")
    assert loaded is not None
    assert loaded.conclusion_code == "qualified"
    assert loaded.extractor_version == "interim_review.v1"
    assert "audit_report_date_override" not in InterimReviewFact.__table__.columns
    await engine.dispose()


async def test_get_returns_none_when_missing() -> None:
    """없는 키는 None이다."""
    engine, sessionmaker = await _sessionmaker()
    async with sessionmaker() as session:
        missing = await InterimFactRepository(session).get("20250814000001", "90001")
    assert missing is None
    await engine.dispose()


async def test_ensure_schema_does_not_create_interim_table() -> None:
    """모델이 메타에 있어도 기동 스키마와 연구 열 보강은 테이블을 만들지 않는다."""
    import research.models  # noqa: F401

    assert all(table != "interim_review_facts" for table, *_rest in _COLUMN_PATCHES)
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await ensure_schema(engine)
    await ensure_research_schema(engine)
    async with engine.begin() as connection:
        names = {
            row[0]
            for row in (
                await connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'table'")
                )
            ).fetchall()
        }
    await engine.dispose()
    assert "interim_review_facts" not in names
    assert "entries" in names
