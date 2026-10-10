"""기동 스키마가 카탈로그 테이블만 다루는 지 확인한다."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.db.session import _COLUMN_PATCHES, ensure_schema, create_db_engine


def test_metadata_tables_are_catalog_only() -> None:
    """신선한 프로세스에서 app.models import 시 카탈로그 테이블만 등록되는지 확인한다."""
    root = Path(__file__).resolve().parents[1]
    script = """
from app.models import Base

expected = {
    "entries",
    "disclosures",
    "catalog_jobs",
    "catalog_job_logs",
    "slice_progress",
    "disclosure_attempts",
}
names = set(Base.metadata.tables)
if names != expected:
    extra = sorted(names - expected)
    missing = sorted(expected - names)
    raise SystemExit(f"mismatch extra={extra!r} missing={missing!r}")
raise SystemExit(0)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_column_patches_are_catalog_only() -> None:
    tables = {table for table, _column, _sqlite, _postgres in _COLUMN_PATCHES}
    assert tables <= {"catalog_jobs", "entries"}
    assert "audit_report_facts" not in tables


async def test_ensure_schema_does_not_create_research_tables() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await ensure_schema(engine)
    async with engine.begin() as connection:
        rows = (
            await connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        ).fetchall()
    await engine.dispose()
    names = {row[0] for row in rows}
    assert "audit_report_facts" not in names
    assert "corps" not in names
    assert "entries" in names
