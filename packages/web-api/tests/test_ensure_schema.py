"""기존 DB에 새 ORM 컬럼이 없어도 기동 시 보강되는지 검증한다."""

from __future__ import annotations

from sqlalchemy import text

from app.db.session import (
    _COLUMN_PATCHES,
    create_db_engine,
    create_sessionmaker,
    ensure_schema,
)
from app.models.catalog_job import CatalogJob
from app.repositories.job_repository import JobRepository


async def test_ensure_schema_adds_mode_to_legacy_catalog_jobs() -> None:
    """예전 스키마(mode 없음) DB를 열어두면 기동 보강으로 mode가 생긴다."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as connection:
        await connection.execute(text("""
                CREATE TABLE catalog_jobs (
                    job_id VARCHAR(64) PRIMARY KEY,
                    status VARCHAR(16) NOT NULL,
                    params JSON NOT NULL,
                    params_key VARCHAR(512) NOT NULL,
                    total_entries INTEGER NOT NULL DEFAULT 0,
                    saved_entries INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    started_at DATETIME,
                    finished_at DATETIME,
                    created_at DATETIME
                )
                """))

    await ensure_schema(engine)

    async with engine.begin() as connection:
        columns = {
            row[1]
            for row in (
                await connection.execute(text("PRAGMA table_info(catalog_jobs)"))
            ).fetchall()
        }
    assert "mode" in columns

    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        jobs = JobRepository(session)
        await jobs.create("job-legacy", {"report_type": "A001"}, "key-1", mode="collect")
        await session.commit()
        loaded = await session.get(CatalogJob, "job-legacy")

    assert loaded is not None
    assert loaded.mode == "collect"
    await engine.dispose()


def test_column_patches_are_catalog_only() -> None:
    """기동 열 보정은 카탈로그 테이블만 다룬다."""
    tables = {table for table, _column, _sqlite, _postgres in _COLUMN_PATCHES}
    assert tables <= {"catalog_jobs", "entries"}
    assert "audit_report_facts" not in tables


async def test_ensure_schema_does_not_patch_audit_report_facts() -> None:
    """예전 감사 테이블이 있어도 기동 스키마는 연구 열을 보강하지 않는다."""
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

    await ensure_schema(engine)

    async with engine.begin() as connection:
        columns = {
            row[1]
            for row in (
                await connection.execute(text("PRAGMA table_info(audit_report_facts)"))
            ).fetchall()
        }
    await engine.dispose()
    assert "hours" not in columns


async def test_ensure_schema_skips_imported_research_tables() -> None:
    """연구 모델이 메타에 있어도 기동 스키마는 corps를 만들지 않는다."""
    from app.models.corp import Corp  # noqa: F401 — 메타에 올린 뒤에도 기동에서 빼는지 본다

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
