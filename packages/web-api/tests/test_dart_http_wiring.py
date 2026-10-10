"""로컬 앱의 Viewer가 공유 DART HTML 클라이언트를 쓰는지."""

from __future__ import annotations

from unittest.mock import MagicMock

from starlette.requests import Request

from app.adapters.dart_http import DartHttpClient
from app.api.deps import get_viewer_service
from app.config import Settings, get_settings
from app.local import create_local_app


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


def test_viewer_uses_shared_dart_http_and_is_serial() -> None:
    """deps가 앱의 dart_http를 쓰고 Viewer 동시성은 1이다."""
    app = create_local_app()
    settings = Settings()
    dart_http = DartHttpClient(
        MagicMock(),
        min_interval_seconds=settings.dart_fetch_min_interval_seconds,
    )
    app.state.dart_http = dart_http
    app.state.sessionmaker = MagicMock()
    request = _http_request(app)

    viewer = get_viewer_service(request, entries=MagicMock())

    assert viewer._http is dart_http
    assert viewer._concurrency == 1
    assert dart_http._min_interval_seconds == settings.dart_fetch_min_interval_seconds


async def test_lifespan_attaches_paced_dart_http(monkeypatch) -> None:
    """기동 시 로컬 앱에 설정 간격의 dart_http와 수집기만 붙는다."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    get_settings.cache_clear()
    app = create_local_app()
    async with app.router.lifespan_context(app):
        http = app.state.dart_http
        assert isinstance(http, DartHttpClient)
        assert http._min_interval_seconds == get_settings().dart_fetch_min_interval_seconds
        assert hasattr(app.state, "entry_collector")
        assert not hasattr(app.state, "opendart_http_client")
        assert not hasattr(app.state, "llm_http_client")
    get_settings.cache_clear()
