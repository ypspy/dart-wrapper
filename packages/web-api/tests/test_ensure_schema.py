"""기존 DB에 새 ORM 컬럼이 없어도 기동 시 보강되는지 검증한다."""

from __future__ import annotations

from sqlalchemy import text

from app.db.session import create_db_engine, create_sessionmaker, ensure_schema
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


async def test_ensure_schema_adds_hours_to_legacy_audit_report_facts() -> None:
    """예전 스키마(실시내용 컬럼 없음) DB를 열어두면 hours가 생긴다."""
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
    assert "hours" in columns
    assert "accounts" in columns
    assert "accounts_status" in columns
    assert "bs_entry_id" in columns
    assert "is_entry_id" in columns
    assert "fs_parent_entry_id" in columns
    await engine.dispose()
