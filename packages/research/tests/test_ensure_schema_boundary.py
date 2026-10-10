"""연구 모델이 메타에 올라와 있어도 web-api 기동 스키마가 연구 테이블을 만들지 않는지 검증한다."""

from __future__ import annotations

from sqlalchemy import text

from app.db.session import create_db_engine, ensure_schema
from research.models.corp import Corp  # noqa: F401 — 메타에 올린 뒤에도 기동에서 빼는지 본다


async def test_ensure_schema_skips_imported_research_tables() -> None:
    """연구 모델이 메타에 있어도 기동 스키마는 corps를 만들지 않는다."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await ensure_schema(engine)
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
    assert "corps" not in names
    assert "entries" in names
