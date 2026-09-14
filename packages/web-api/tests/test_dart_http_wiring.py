"""추출과 Viewer가 같은 DART HTML 클라이언트를 쓰는지."""

from __future__ import annotations

from unittest.mock import MagicMock

from starlette.requests import Request

from app.adapters.dart_http import DartHttpClient
from app.api.deps import get_extraction_service, get_viewer_service
from app.config import Settings, get_settings
from app.main import create_app


def _http_request(app) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("test", 50000),
            "server": ("test", 80),
            "app": app,
        }
    )


def test_extract_and_viewer_share_dart_http_and_viewer_is_serial() -> None:
    """deps가 같은 dart_http를 쓰고 Viewer 동시성은 1이다."""
    app = create_app()
    settings = Settings()
    dart_http = DartHttpClient(
        MagicMock(),
        min_interval_seconds=settings.dart_fetch_min_interval_seconds,
    )
    app.state.dart_http = dart_http
    app.state.sessionmaker = MagicMock()
    app.state.extraction_service = None
    request = _http_request(app)

    extraction = get_extraction_service(request, settings)
    viewer = get_viewer_service(request, entries=MagicMock())

    assert extraction._http is dart_http
    assert viewer._http is dart_http
    assert viewer._concurrency == 1
    assert dart_http._min_interval_seconds == settings.dart_fetch_min_interval_seconds


async def test_lifespan_attaches_paced_dart_http(monkeypatch) -> None:
    """기동 시 app.state.dart_http가 설정 간격으로 붙는다."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        http = app.state.dart_http
        assert isinstance(http, DartHttpClient)
        assert http._min_interval_seconds == get_settings().dart_fetch_min_interval_seconds
    get_settings.cache_clear()
