"""연구 추출 앱 기동이 1층에 쓰지 않는지, 추출 잡은 2층만 쓰는지 고정한다."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
from sqlalchemy import event, text

from app.adapters.dart_http import DartHttpClient

from app.config import get_settings
from app.db.catalog_guard import (
    FIRST_LAYER_TABLES,
    CatalogSchemaError,
    CatalogWriteBlocked,
    assert_no_first_layer_write,
    block_first_layer_writes,
)
from app.db.session import (
    _CATALOG_TABLES,
    create_db_engine,
    create_sessionmaker,
)
from app.models.base import Base
from research.config import get_research_settings
from research.local_app import create_app
from research.models.audit_report_fact import AuditReportFact
from research.models.extraction_job import ExtractionJob, ExtractionJobLog
from research.models.extraction_review import ExtractionReview
from research.models.firm_remediation import (
    ExtractionFirmMatchReview,
    ExtractionFirmRemediation,
    ExtractionFirmRemediationDocument,
    ExtractionFirmRemediationNote,
)
from catalog_db_helpers import (
    build_catalog,
    connect_ro,
    file_sha256,
    master_rows,
    pragma_columns,
    url_for,
)
from research.schema import ensure_research_schema
from test_extraction_service import _f001_leaves, _seed_entries, _service

_RESEARCH_TABLES = {
    AuditReportFact.__tablename__,
    ExtractionJob.__tablename__,
    ExtractionJobLog.__tablename__,
    ExtractionReview.__tablename__,
    ExtractionFirmRemediation.__tablename__,
    ExtractionFirmRemediationNote.__tablename__,
    ExtractionFirmRemediationDocument.__tablename__,
    ExtractionFirmMatchReview.__tablename__,
}
_LEGACY_FACT_DDL = """
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
"""


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """유료 키를 비우고 설정 캐시가 다른 테스트로 새지 않게 한다."""
    monkeypatch.setenv("OPENDART_API_KEY", "")
    monkeypatch.setenv("OPENDART_API_KEY_2", "")
    monkeypatch.setenv("DATE_RESOLVER_API_KEY", "")
    monkeypatch.setenv("DART_LLM_ENABLED", "false")
    get_settings.cache_clear()
    get_research_settings.cache_clear()
    yield
    get_settings.cache_clear()
    get_research_settings.cache_clear()


def _first_layer_master(path: Path) -> list[tuple[str, str, str | None]]:
    kept: list[tuple[str, str, str | None]] = []
    for type_, name, sql in master_rows(path):
        if name in FIRST_LAYER_TABLES:
            kept.append((type_, name, sql))
            continue
        if type_ == "index" and _index_on_first_layer(name, sql):
            kept.append((type_, name, sql))
    return kept


def _index_on_first_layer(name: str, sql: str | None) -> bool:
    folded = name.casefold()
    for table in FIRST_LAYER_TABLES:
        if folded.startswith(f"sqlite_autoindex_{table}_"):
            return True
    if not sql:
        return False
    upper = sql.casefold()
    return any(f" on {table}" in upper or f' on "{table}"' in upper for table in FIRST_LAYER_TABLES)


def _column_names(path: Path, table: str) -> set[str]:
    return {str(row[1]) for row in pragma_columns(path, table)}


def _table_rows(path: Path, table: str) -> list[tuple[object, ...]]:
    connection = connect_ro(path)
    try:
        rows = connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
    finally:
        connection.close()
    return [tuple(row) for row in rows]


def _prepare_app(monkeypatch: pytest.MonkeyPatch, path: Path, *, allow_writes: bool) -> object:
    monkeypatch.setenv("DATABASE_URL", url_for(path))
    monkeypatch.setenv("RESEARCH_ALLOW_CATALOG_WRITES", "true" if allow_writes else "false")
    get_settings.cache_clear()
    get_research_settings.cache_clear()
    return create_app()


async def test_startup_leaves_active_catalog_job_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """진행 중 수집 잡은 연구 앱을 켜고 꺼도 행·파일·로그가 그대로다."""
    path = tmp_path / "active.db"
    engine = await build_catalog(path, keep_engine=True)
    async with engine.begin() as connection:
        await connection.execute(text("""
                INSERT INTO catalog_jobs (
                    job_id, status, mode, params, params_key,
                    total_entries, saved_entries, created_at
                ) VALUES
                (
                    'running-job-0001', 'running', 'collect', '{}', 'k-run',
                    0, 0, '2020-01-01'
                ),
                (
                    'pending-job-0001', 'pending', 'collect', '{}', 'k-pend',
                    0, 0, '2020-01-02'
                )
                """))
    await engine.dispose()
    before_hash = file_sha256(path)
    before_jobs = _table_rows(path, "catalog_jobs")
    before_logs = _table_rows(path, "catalog_job_logs")
    app = _prepare_app(monkeypatch, path, allow_writes=False)

    with caplog.at_level(logging.WARNING, logger="app.apps"):
        async with app.router.lifespan_context(app):
            pass

    assert "그대로 둡니다" in caplog.text
    assert _table_rows(path, "catalog_jobs") == before_jobs
    assert _table_rows(path, "catalog_job_logs") == before_logs
    assert file_sha256(path) == before_hash


async def test_extract_post_conflicts_while_catalog_job_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """진행 중 수집 잡이 있으면 추출 POST는 409이고 1층 행과 DART 호출은 그대로다."""
    path = tmp_path / "active-extract.db"
    engine = await build_catalog(path, keep_engine=True)
    async with engine.begin() as connection:
        await connection.execute(text("""
                INSERT INTO catalog_jobs (
                    job_id, status, mode, params, params_key,
                    total_entries, saved_entries, created_at
                ) VALUES
                (
                    'running-job-0001', 'running', 'collect', '{}', 'k-run',
                    0, 0, '2020-01-01'
                ),
                (
                    'pending-job-0001', 'pending', 'collect', '{}', 'k-pend',
                    0, 0, '2020-01-02'
                )
                """))
    await engine.dispose()
    before = {table: _table_rows(path, table) for table in (*_CATALOG_TABLES, "corps")}
    app = _prepare_app(monkeypatch, path, allow_writes=False)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="호출되면 안 됩니다")

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as dart_client:
            app.state.dart_http = DartHttpClient(
                dart_client, max_retries=0, retry_backoff_seconds=0.0
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/admin/extract/audit-opinion",
                    json={
                        "start_date": "20200301",
                        "end_date": "20200331",
                        "report_types": ["F001"],
                        "mode": "extract",
                    },
                    headers={"X-Admin-Token": "dev-admin-token"},
                )
    assert response.status_code == 409
    assert "다른 수집 작업이 이미 진행 중입니다" in response.json()["detail"]
    assert calls["n"] == 0
    assert _table_rows(path, "extraction_jobs") == []
    assert _table_rows(path, "audit_report_facts") == []
    for table, rows in before.items():
        assert _table_rows(path, table) == rows


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("catalog_jobs", "mode"),
        ("slice_progress", "empty_confirmations"),
        ("entries", "ordinal"),
    ],
)
async def test_startup_missing_first_layer_column_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: str, column: str
) -> None:
    """빠진 1층 열이 있으면 기동이 실패하고 ALTER도 하지 않는다."""
    path = tmp_path / f"missing-{column}.db"
    engine = await build_catalog(path, keep_engine=True)
    async with engine.begin() as connection:
        await connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
    await engine.dispose()
    before_hash = file_sha256(path)
    before_master = master_rows(path)
    before_columns = pragma_columns(path, table)
    app = _prepare_app(monkeypatch, path, allow_writes=False)

    with pytest.raises(CatalogSchemaError, match=f"{table}.{column}"):
        async with app.router.lifespan_context(app):
            pass

    assert master_rows(path) == before_master
    assert pragma_columns(path, table) == before_columns
    assert file_sha256(path) == before_hash


async def test_guarded_manual_second_layer_migration_keeps_first_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """연구 앱 기동은 2층 스키마를 만들거나 보강하지 않는다(master와 같음).

    가드 아래 수동 create_all·ensure_research_schema는 1층 정의를 바꾸지 않고 2층을 보강한다.
    """
    path = tmp_path / "second.db"
    engine = await build_catalog(path, keep_engine=True)
    async with engine.begin() as connection:
        await connection.execute(text("PRAGMA foreign_keys=OFF"))
        await connection.execute(text("DROP TABLE IF EXISTS extraction_job_logs"))
        await connection.execute(text("DROP TABLE IF EXISTS extraction_jobs"))
        await connection.execute(text("DROP TABLE IF EXISTS audit_report_facts"))
        await connection.execute(text(_LEGACY_FACT_DDL))
    await engine.dispose()
    app = _prepare_app(monkeypatch, path, allow_writes=False)
    async with app.router.lifespan_context(app):
        pass
    assert "hours" not in _column_names(path, "audit_report_facts")
    before_first = _first_layer_master(path)

    engine = create_db_engine(url_for(path))
    tables = [
        AuditReportFact.__table__,
        ExtractionJob.__table__,
        ExtractionJobLog.__table__,
    ]
    with block_first_layer_writes(engine.sync_engine):
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables)
            )
        await ensure_research_schema(engine)
    await engine.dispose()

    assert "hours" in _column_names(path, "audit_report_facts")
    assert _first_layer_master(path) == before_first


async def test_extraction_job_path_writes_only_second_layer(tmp_path: Path) -> None:
    """추출 start·run_job의 SQL은 1층 쓰기가 아니고 1층 행 수도 그대로다."""
    path = tmp_path / "extract.db"
    engine = await build_catalog(path, keep_engine=True)
    sessionmaker = create_sessionmaker(engine)
    await _seed_entries(sessionmaker, _f001_leaves())

    async def _counts() -> dict[str, int]:
        counts: dict[str, int] = {}
        async with sessionmaker() as session:
            for table in (*_CATALOG_TABLES, "corps"):
                result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                counts[table] = int(result.scalar_one())
        return counts

    before = await _counts()
    captured: list[str] = []

    def _capture(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        captured.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _capture)
    try:
        service, client = _service(sessionmaker)
        async with client:
            job_id = await service.start("20200301", "20200331", ["F001"], "extract")
            await service.run_job(job_id)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _capture)

    for statement in captured:
        try:
            assert_no_first_layer_write(statement)
        except CatalogWriteBlocked as exc:
            pytest.fail(f"{exc}\nSQL: {statement}")
    assert await _counts() == before
    async with sessionmaker() as session:
        facts = int(
            (await session.execute(text("SELECT COUNT(*) FROM audit_report_facts"))).scalar_one()
        )
        jobs = int(
            (await session.execute(text("SELECT COUNT(*) FROM extraction_jobs"))).scalar_one()
        )
    await engine.dispose()
    assert facts >= 1
    assert jobs == 1


async def test_allow_catalog_writes_opt_in_restores_previous_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RESEARCH_ALLOW_CATALOG_WRITES=true면 열 보강과 활성 잡 마감이 돌아온다."""
    path = tmp_path / "opt-in.db"
    engine = await build_catalog(path, keep_engine=True)
    async with engine.begin() as connection:
        await connection.execute(text("""
                INSERT INTO catalog_jobs (
                    job_id, status, mode, params, params_key,
                    total_entries, saved_entries, created_at
                ) VALUES
                (
                    'running-job-0001', 'running', 'collect', '{}', 'k-run',
                    0, 0, '2020-01-01'
                ),
                (
                    'pending-job-0001', 'pending', 'collect', '{}', 'k-pend',
                    0, 0, '2020-01-02'
                )
                """))
        await connection.execute(text("ALTER TABLE catalog_jobs DROP COLUMN mode"))
        await connection.execute(text("ALTER TABLE slice_progress DROP COLUMN empty_confirmations"))
        await connection.execute(text("ALTER TABLE entries DROP COLUMN ordinal"))
    await engine.dispose()
    app = _prepare_app(monkeypatch, path, allow_writes=True)

    async with app.router.lifespan_context(app):
        pass

    assert "mode" in _column_names(path, "catalog_jobs")
    assert "empty_confirmations" in _column_names(path, "slice_progress")
    assert "ordinal" in _column_names(path, "entries")
    jobs = _table_rows(path, "catalog_jobs")
    assert len(jobs) == 2
    connection = connect_ro(path)
    try:
        statuses = {
            row[0] for row in connection.execute("SELECT status FROM catalog_jobs").fetchall()
        }
        logs = connection.execute("SELECT level FROM catalog_job_logs").fetchall()
    finally:
        connection.close()
    assert statuses == {"partial"}
    assert len(logs) == 2
    assert {row[0] for row in logs} == {"warning"}


def test_first_layer_tables_cover_catalog_tables_and_corps() -> None:
    """1층 목록은 카탈로그 6개와 corps이고 연구 테이블과 겹치지 않는다."""
    assert FIRST_LAYER_TABLES == set(_CATALOG_TABLES) | {"corps"}
    assert FIRST_LAYER_TABLES.isdisjoint(_RESEARCH_TABLES)
