"""연구 스키마 열 보정. web-api 기동 경로는 호출하지 않는다."""

from __future__ import annotations

from sqlalchemy import text

from app.db.session import create_db_engine
from research.schema import ensure_research_schema


async def test_ensure_research_schema_adds_hours_to_legacy_audit_report_facts() -> None:
    """예전 감사 테이블이 있으면 연구 스키마가 빠진 열을 보강한다."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as connection:
        await connection.execute(text("""
                CREATE TABLE audit_report_facts (
                    rcept_no VARCHAR(32) NOT NULL,
                    dcm_no VARCHAR(32) NOT NULL,
                    source_report_type VARCHAR(16) NOT NULL,
                    fs_scope VARCHAR(16) NOT NULL,
                    fetch_status VARCHAR(32) NOT NULL,
                    conflicts TEXT NOT NULL DEFAULT '[]',
                    extractor_version VARCHAR(32) NOT NULL,
                    PRIMARY KEY (rcept_no, dcm_no)
                )
                """))

    await ensure_research_schema(engine)

    async with engine.begin() as connection:
        columns = {
            row[1]
            for row in (
                await connection.execute(text("PRAGMA table_info(audit_report_facts)"))
            ).fetchall()
        }
    await engine.dispose()
    assert "hours" in columns
    assert "accounts" in columns
    assert "accounts_status" in columns
    assert "bs_entry_id" in columns
    assert "is_entry_id" in columns
    assert "fs_parent_entry_id" in columns
    assert "icfr_entry_id" in columns
    assert "icfr_engagement" in columns
    assert "icfr_opinion_raw" in columns
    assert "icfr_opinion_code" in columns
    assert "icfr_status" in columns
    assert "going_concern" in columns
    assert "going_concern_status" in columns
    assert "going_concern_raw" in columns
    assert "going_concern_source" in columns
    assert "subsidiary_count" in columns
    assert "subsidiary_status" in columns
    assert "subsidiary_source" in columns
    assert "notes_entry_id" in columns
    assert "a001_affiliate_entry_id" in columns
