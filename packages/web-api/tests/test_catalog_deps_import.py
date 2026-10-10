"""카탈로그 라우터 import가 연구 모듈을 불러오지 않는지."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_catalog_routers_do_not_import_research() -> None:
    """공개 읽기 라우터를 열어도 추출·OpenDART·LLM 모듈이 로드되지 않는다."""
    root = Path(__file__).resolve().parents[1]
    script = """
import sys
import app.api.v1.catalog
import app.api.v1.viewer
import app.api.catalog.ui
import app.api.admin.catalog
banned = (
    "app.extracting",
    "app.reviewing",
    "app.services.extraction_service",
    "app.adapters.opendart_company",
    "app.adapters.llm_date_resolver",
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


def test_collect_ui_does_not_import_research() -> None:
    """수집 화면 모듈은 추출·업종 서비스를 불러오지 않는다."""
    root = Path(__file__).resolve().parents[1]
    script = """
import sys
import app.api.admin.collect_ui
banned = (
    "app.services.extraction_service",
    "app.services.corp_industry_service",
    "app.services.completeness_service",
    "app.extracting",
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
