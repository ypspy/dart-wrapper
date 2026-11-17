"""1층 쓰기 가드와 로컬 앱 기본 기동(스키마 보강·잡 정리)을 검증한다."""

from __future__ import annotations

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
from tests.catalog_db_helpers import (
    build_catalog,
    connect_ro,
    file_sha256,
    master_rows,
    pragma_columns,
    url_for,
)


def _ensure_corps_table(path: Path) -> None:
    """web-api create_all은 corps를 만들지 않으므로 존재 확인용 빈 테이블을 둔다."""
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS corps (corp_code VARCHAR(16) PRIMARY KEY)")
        connection.commit()
    finally:
        connection.close()


async def test_verify_catalog_schema_passes_without_ddl(tmp_path: Path) -> None:
    """정상 스키마는 통과하고 sqlite_master와 파일 바이트는 그대로다."""
    path = tmp_path / "catalog.db"
    await build_catalog(path)
    _ensure_corps_table(path)
    before_hash = file_sha256(path)
    before_master = master_rows(path)

    engine = create_db_engine(url_for(path))
    await verify_catalog_schema(engine)
    await engine.dispose()

    assert file_sha256(path) == before_hash
    assert master_rows(path) == before_master


async def test_verify_catalog_schema_missing_column_raises_without_alter(
    tmp_path: Path,
) -> None:
    """mode가 없는 예전 catalog_jobs는 고치지 않고 기동 확인이 실패한다."""
    path = tmp_path / "legacy.db"
    engine = create_db_engine(url_for(path))
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
    before_hash = file_sha256(path)
    before_master = master_rows(path)
    before_columns = pragma_columns(path, "catalog_jobs")

    engine = create_db_engine(url_for(path))
    with pytest.raises(CatalogSchemaError, match="catalog_jobs.mode") as caught:
        await verify_catalog_schema(engine)
    await engine.dispose()

    assert "만들지 않습니다" in str(caught.value)
    assert pragma_columns(path, "catalog_jobs") == before_columns
    assert master_rows(path) == before_master
    assert file_sha256(path) == before_hash


async def test_verify_catalog_schema_missing_table_raises(tmp_path: Path) -> None:
    """slice_progress가 없으면 실패하고 그 테이블을 만들지 않는다."""
    path = tmp_path / "missing-slice.db"
    await build_catalog(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("DROP TABLE IF EXISTS disclosure_attempts")
        connection.execute("DROP TABLE slice_progress")
        connection.commit()
    finally:
        connection.close()
    before_hash = file_sha256(path)
    before_master = master_rows(path)

    engine = create_db_engine(url_for(path))
    with pytest.raises(CatalogSchemaError, match="slice_progress"):
        await verify_catalog_schema(engine)
    await engine.dispose()

    assert master_rows(path) == before_master
    assert file_sha256(path) == before_hash
    assert all(name != "slice_progress" for _type, name, _sql in master_rows(path))


async def test_verify_catalog_schema_missing_corps_raises(tmp_path: Path) -> None:
    """corps가 없으면 기동 확인이 실패하고 파일은 그대로다. 열은 보지 않는다."""
    path = tmp_path / "no-corps.db"
    await build_catalog(path)
    _ensure_corps_table(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE corps")
        connection.commit()
    finally:
        connection.close()
    before_hash = file_sha256(path)
    before_master = master_rows(path)

    engine = create_db_engine(url_for(path))
    with pytest.raises(CatalogSchemaError, match="corps"):
        await verify_catalog_schema(engine)
    await engine.dispose()

    assert file_sha256(path) == before_hash
    assert master_rows(path) == before_master
    assert all(name != "corps" for _type, name, _sql in master_rows(path))


class _PresentRow:
    """있음/없음만 돌려주는 가짜 조회 결과."""

    def __init__(self, present: bool) -> None:
        self._present = present

    def first(self) -> tuple[int] | None:
        if self._present:
            return (1,)
        return None


class _PostgresConnection:
    """information_schema 질의만 기록하는 가짜 Postgres 연결."""

    def __init__(self, missing: set[str] | None = None) -> None:
        self.dialect = type("Dialect", (), {"name": "postgresql"})()
        self.statements: list[str] = []
        self._missing = missing or set()

    async def execute(self, statement: object, params: dict[str, str] | None = None) -> _PresentRow:
        sql = str(statement)
        self.statements.append(sql)
        name = ""
        if params:
            name = params.get("name") or params.get("table") or ""
        return _PresentRow(name not in self._missing)

    async def __aenter__(self) -> "_PostgresConnection":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _PostgresEngine:
    """connect()가 가짜 연결을 그대로 돌려주는 엔진."""

    def __init__(self, connection: _PostgresConnection) -> None:
        self._connection = connection

    def connect(self) -> _PostgresConnection:
        return self._connection


async def test_verify_catalog_schema_postgres_branch_reads_only() -> None:
    """Postgres 분기는 information_schema 읽기만 하고, 없는 테이블 이름을 오류에 담는다."""
    connection = _PostgresConnection()
    await verify_catalog_schema(_PostgresEngine(connection))  # type: ignore[arg-type]
    assert connection.statements
    for statement in connection.statements:
        assert statement.startswith("SELECT 1 FROM information_schema.")
        assert "table_schema = 'public'" in statement
        assert_no_first_layer_write(statement)

    missing = _PostgresConnection({"entries"})
    with pytest.raises(CatalogSchemaError, match="entries"):
        await verify_catalog_schema(_PostgresEngine(missing))  # type: ignore[arg-type]


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
        ("UPDATE ONLY entries SET x=1", "entries", "UPDATE"),
        ("DELETE FROM ONLY entries", "entries", "DELETE"),
        ("ALTER TABLE IF EXISTS entries ADD COLUMN x INT", "entries", "ALTER"),
        ("ALTER TABLE ONLY catalog_jobs ADD COLUMN x INT", "catalog_jobs", "ALTER"),
        (
            "WITH d AS (DELETE FROM entries RETURNING *) SELECT * FROM d",
            "entries",
            "DELETE",
        ),
        (
            "WITH u AS (UPDATE disclosures SET x=1 RETURNING *) SELECT 1",
            "disclosures",
            "UPDATE",
        ),
        ("SELECT * INTO corps FROM x", "corps", "CREATE TABLE"),
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
        "PRAGMA table_info(entries)",
        "PRAGMA read_uncommitted",
        "PRAGMA foreign_keys=OFF",
        "PRAGMA busy_timeout = 60000",
        "PRAGMA user_version",
        "UPDATE ONLY extraction_jobs SET status='x'",
        "WITH d AS (DELETE FROM extraction_job_logs RETURNING *) SELECT 1",
    ],
)
def test_assert_no_first_layer_write_allows(statement: str) -> None:
    """2층 쓰기와 1층 읽기, 이름이 다른 테이블은 통과한다."""
    assert_no_first_layer_write(statement)


@pytest.mark.parametrize(
    ("statement", "name"),
    [
        ("PRAGMA writable_schema=1", "writable_schema"),
        ("PRAGMA user_version=5", "user_version"),
        ("PRAGMA main.user_version = 5", "user_version"),
        ("PRAGMA journal_mode=WAL", "journal_mode"),
        ("PRAGMA optimize", "optimize"),
        ("PRAGMA wal_checkpoint", "wal_checkpoint"),
        ("PRAGMA wal_checkpoint(TRUNCATE)", "wal_checkpoint"),
        ("PRAGMA incremental_vacuum", "incremental_vacuum"),
        ('PRAGMA "user_version"=5', "user_version"),
        ('PRAGMA main."user_version"=5', "user_version"),
    ],
)
def test_assert_no_first_layer_write_blocks_file_pragmas(statement: str, name: str) -> None:
    """파일을 바꾸거나 허용 목록 밖인 PRAGMA는 값 없는 형태까지 막는다."""
    with pytest.raises(CatalogWriteBlocked, match="허용 목록 밖의 PRAGMA") as caught:
        assert_no_first_layer_write(statement)
    assert f": {name}." in str(caught.value)


@pytest.mark.parametrize(
    "statement",
    [
        "DROP INDEX IF EXISTS ix_entries_rcept_no",
        "DROP INDEX ix_extraction_jobs_status",
    ],
)
def test_drop_index_always_blocked(statement: str) -> None:
    """1층이든 2층이든 DROP INDEX는 인덱스 이름으로 막는다."""
    with pytest.raises(CatalogWriteBlocked, match=r"\(DROP INDEX\)"):
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
    engine = create_db_engine(url_for(path))
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

    monkeypatch.setenv("DATABASE_URL", url_for(path))
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

    connection = connect_ro(path)
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


_SHARED_STATE = ("engine", "sessionmaker", "http_client", "dart_http", "entry_collector")


async def test_local_and_readonly_lifespan_set_shared_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기본 분기와 읽기 전용 분기 모두 세션·HTTP·수집기 상태를 붙인다."""
    default_path = tmp_path / "default.db"
    readonly_path = tmp_path / "readonly.db"
    await build_catalog(readonly_path)
    _ensure_corps_table(readonly_path)
    monkeypatch.setenv("DART_LLM_ENABLED", "false")
    monkeypatch.setenv("OPENDART_API_KEY", "")
    monkeypatch.setenv("OPENDART_API_KEY_2", "")
    monkeypatch.setenv("DATE_RESOLVER_API_KEY", "")
    monkeypatch.setenv("DATABASE_URL", url_for(default_path))
    get_settings.cache_clear()
    try:
        app = create_local_app()
        async with app.router.lifespan_context(app):
            for name in _SHARED_STATE:
                assert getattr(app.state, name) is not None
        monkeypatch.setenv("DATABASE_URL", url_for(readonly_path))
        get_settings.cache_clear()
        readonly = create_local_app(catalog_writes=False)
        async with readonly.router.lifespan_context(readonly):
            for name in _SHARED_STATE:
                assert getattr(readonly.state, name) is not None
    finally:
        get_settings.cache_clear()
