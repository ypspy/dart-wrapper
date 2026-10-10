"""로컬·공개 앱의 라우트와 Postgres 가드."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from app.apps import create_public_app, require_postgres_url
from app.config import Settings
from app.local import create_local_app

PUBLIC_PREFIXES = (
    "/health",
    "/catalog",
    "/api/v1/catalog/disclosures",
    "/api/v1/viewer/{rcp_no}",
)
FORBIDDEN = (
    "/admin",
    "/admin/extract",
    "/admin/reviews",
    "/admin/cycle",
    "/admin/corps",
    "/facts",
    "/api/v1/facts",
)


def _paths(app) -> set[str]:
    paths: set[str] = set()

    def walk(routes) -> None:
        for route in routes:
            path = getattr(route, "path", "") or ""
            if path:
                paths.add(path)
            original_router = getattr(route, "original_router", None)
            if original_router is not None:
                walk(original_router.routes)
            elif getattr(route, "routes", None):
                walk(route.routes)

    walk(app.routes)
    return paths


def test_require_postgres_url_rejects_sqlite() -> None:
    with pytest.raises(RuntimeError):
        require_postgres_url("sqlite+aiosqlite:///./dart_catalog.db")


def test_require_postgres_url_accepts_asyncpg() -> None:
    require_postgres_url("postgresql+asyncpg://user:pass@host/db")


def test_public_app_routes_are_read_only() -> None:
    app = create_public_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
    paths = _paths(app)
    assert "/health" in paths
    assert "/catalog" in paths
    assert "/api/v1/catalog/disclosures" in paths
    assert "/api/v1/viewer/{rcp_no}" in paths
    for path in paths:
        assert not path.startswith(FORBIDDEN)


def test_local_app_has_collect_and_read_routes() -> None:
    app = create_local_app()
    paths = _paths(app)
    assert "/admin" in paths
    assert "/admin/catalog/extract" in paths
    assert "/health" in paths
    assert "/api/v1/viewer/{rcp_no}" in paths
    assert "/admin/extract" not in paths
    assert "/admin/reviews" not in paths
    assert "/facts" not in paths


def test_main_app_matches_local_routes() -> None:
    from app.main import create_app

    local_paths = _paths(create_local_app())
    main_paths = _paths(create_app())
    assert main_paths == local_paths


def test_role_apps_do_not_import_research_modules() -> None:
    root = Path(__file__).resolve().parents[1]
    script = """
import sys
from app.apps import create_public_app
from app.config import Settings
from app.local import create_local_app
create_local_app()
create_public_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
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
