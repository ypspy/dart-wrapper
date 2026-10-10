"""세션 모듈 import만으로 카탈로그 ORM 메타가 등록되는지."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_session_import_registers_catalog_tables_without_research() -> None:
    """app.db.session만 불러도 카탈로그 테이블 메타가 생기고 연구 모듈은 로드되지 않는다."""
    root = Path(__file__).resolve().parents[1]
    script = """
import sys
import app.db.session
from app.models import Base

required = (
    "entries",
    "disclosures",
    "catalog_jobs",
    "catalog_job_logs",
    "slice_progress",
    "disclosure_attempts",
)
missing = [name for name in required if name not in Base.metadata.tables]
if missing:
    raise SystemExit("missing tables " + ",".join(missing))

banned = (
    "research",
)
loaded = [name for name in sys.modules if name.startswith(banned)]
raise SystemExit(0 if not loaded else "loaded " + ",".join(loaded))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
