"""1층 쓰기 가드와 로컬 앱 기본 기동(스키마 보강·잡 정리)을 검증한다."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db.catalog_guard import (
    CatalogSchemaError,
    CatalogWriteBlocked,
    assert_no_first_layer_write,
    block_first_layer_writes,
    verify_catalog_schema,
)
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.local import create_local_app
from app.models.catalog_job import CatalogJob


def _url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _master_rows(path: Path) -> list[tuple[str, str, str | None]]:
    connection = _connect_ro(path)
    try:
        rows = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
    finally:
        connection.close()
    return [(row[0], row[1], row[2]) for row in rows]


def _pragma_columns(path: Path, table: str) -> list[tuple[object, ...]]:
    connection = _connect_ro(path)
    try:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    finally:
        connection.close()
    return [tuple(row) for row in rows]


async def _build_catalog(path: Path) -> None:
    engine = create_db_engine(_url(path))
    await create_all(engine)
    await engine.dispose()


async def test_verify_catalog_schema_passes_without_ddl(tmp_path: Path) -> None:
    """정상 스키마는 통과하고 sqlite_master와 파일 바이트는 그대로다."""
    path = tmp_path / "catalog.db"
    await _build_catalog(path)
    before_hash = _file_sha256(path)
    before_master = _master_rows(path)

    engine = create_db_engine(_url(path))
    await verify_catalog_schema(engine)
    await engine.dispose()

    assert _file_sha256(path) == before_hash
    assert _master_rows(path) == before_master


async def test_verify_catalog_schema_missing_column_raises_without_alter(
    tmp_path: Path,
) -> None:
    """mode가 없는 예전 catalog_jobs는 고치지 않고 기동 확인이 실패한다."""
    path = tmp_path / "legacy.db"
    engine = create_db_engine(_url(path))
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
    await engine.dispose()
    before_hash = _file_sha256(path)
    before_master = _master_rows(path)
    before_columns = _pragma_columns(path, "catalog_jobs")

    engine = create_db_engine(_url(path))
    with pytest.raises(CatalogSchemaError, match="catalog_jobs.mode") as caught:
        await verify_catalog_schema(engine)
    await engine.dispose()

    assert "만들지 않습니다" in str(caught.value)
    assert _pragma_columns(path, "catalog_jobs") == before_columns
    assert _master_rows(path) == before_master
    assert _file_sha256(path) == before_hash


async def test_verify_catalog_schema_missing_table_raises(tmp_path: Path) -> None:
    """slice_progress가 없으면 실패하고 그 테이블을 만들지 않는다."""
    path = tmp_path / "missing-slice.db"
    await _build_catalog(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("DROP TABLE IF EXISTS disclosure_attempts")
        connection.execute("DROP TABLE slice_progress")
        connection.commit()
    finally:
        connection.close()
    before_hash = _file_sha256(path)
    before_master = _master_rows(path)

    engine = create_db_engine(_url(path))
    with pytest.raises(CatalogSchemaError, match="slice_progress"):
        await verify_catalog_schema(engine)
    await engine.dispose()

    assert _master_rows(path) == before_master
    assert _file_sha256(path) == before_hash
    assert all(name != "slice_progress" for _type, name, _sql in _master_rows(path))


@pytest.mark.parametrize(
    ("statement", "table", "operation"),
    [
        ("INSERT INTO entries", "entries", "INSERT"),
        ("UPDATE catalog_jobs SET status='partial'", "catalog_jobs", "UPDATE"),
        ("DELETE FROM disclosures", "disclosures", "DELETE"),
        (
            "ALTER TABLE slice_progress ADD COLUMN x INTEGER",
            "slice_progress",
            "ALTER",
        ),
        (
            "CREATE TABLE IF NOT EXISTS corps (corp_code VARCHAR(16))",
            "corps",
            "CREATE TABLE",
        ),
        ('INSERT INTO "catalog_job_logs"', "catalog_job_logs", "INSERT"),
        (
            "update Main.disclosure_attempts set status='failed'",
            "disclosure_attempts",
            "UPDATE",
        ),
        ("CREATE INDEX ix ON entries (rcept_no)", "entries", "CREATE INDEX"),
    ],
)
def test_assert_no_first_layer_write_blocks(statement: str, table: str, operation: str) -> None:
    """1층 쓰기 문장은 테이블과 동작 종류를 밝혀 막는다."""
    with pytest.raises(CatalogWriteBlocked, match=rf"{table} \({operation}\)"):
        assert_no_first_layer_write(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM catalog_jobs",
        "INSERT INTO audit_report_facts",
        "UPDATE extraction_jobs",
        "ALTER TABLE audit_report_facts ADD COLUMN hours TEXT",
        "CREATE TABLE extraction_firm_remediation",
        (
            "UPDATE extraction_firm_remediation SET rcept_dt = "
            "(SELECT rcept_dt FROM disclosures WHERE rcept_no = '1')"
        ),
        "INSERT INTO entries_backup (entry_id) VALUES ('x')",
    ],
)
def test_assert_no_first_layer_write_allows(statement: str) -> None:
    """2층 쓰기와 1층 읽기, 이름이 다른 테이블은 통과한다."""
    assert_no_first_layer_write(statement)


async def test_block_first_layer_writes_raises_inside_and_releases_after() -> None:
    """가드 안에서는 catalog_jobs 변경이 막히고, 밖에서는 같은 문이 실행된다."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        session.add(
            CatalogJob(
                job_id="job-w6",
                status="running",
                mode="collect",
                params={},
                params_key="k",
            )
        )
        await session.commit()
    statement = "UPDATE catalog_jobs SET status = 'partial' WHERE job_id = 'job-w6'"

    with block_first_layer_writes(engine.sync_engine):
        with pytest.raises(CatalogWriteBlocked):
            async with engine.begin() as connection:
                await connection.execute(text(statement))

    async with engine.connect() as connection:
        status = (
            await connection.execute(
                text("SELECT status FROM catalog_jobs WHERE job_id = 'job-w6'")
            )
        ).scalar_one()
    assert status == "running"

    async with engine.begin() as connection:
        await connection.execute(text(statement))
    async with engine.connect() as connection:
        status = (
            await connection.execute(
                text("SELECT status FROM catalog_jobs WHERE job_id = 'job-w6'")
            )
        ).scalar_one()
    await engine.dispose()
    assert status == "partial"


async def test_local_lifespan_default_keeps_catalog_maintenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """인자 없는 로컬 앱은 mode 열을 보강하고 진행 중 잡을 partial로 마감한다."""
    path = tmp_path / "local.db"
    engine = create_db_engine(_url(path))
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
        await connection.execute(text("""
                INSERT INTO catalog_jobs (
                    job_id, status, params, params_key, total_entries, saved_entries
                ) VALUES (
                    'job-running-1', 'running', '{}', 'key-1', 0, 0
                )
                """))
    await engine.dispose()

    monkeypatch.setenv("DATABASE_URL", _url(path))
    monkeypatch.setenv("DART_LLM_ENABLED", "false")
    monkeypatch.setenv("OPENDART_API_KEY", "")
    monkeypatch.setenv("OPENDART_API_KEY_2", "")
    monkeypatch.setenv("DATE_RESOLVER_API_KEY", "")
    get_settings.cache_clear()
    try:
        app = create_local_app()
        async with app.router.lifespan_context(app):
            pass
    finally:
        get_settings.cache_clear()

    connection = _connect_ro(path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(catalog_jobs)")}
        status = connection.execute("SELECT status FROM catalog_jobs").fetchone()
        logs = connection.execute("SELECT level FROM catalog_job_logs").fetchall()
    finally:
        connection.close()
    assert "mode" in columns
    assert status is not None
    assert status[0] == "partial"
    assert [row[0] for row in logs] == ["warning"]
