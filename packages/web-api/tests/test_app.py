"""앱 팩토리와 기본 설정 테스트."""

from __future__ import annotations

from app.config import Settings
from app.main import create_app


async def test_health_endpoint_returns_ok(client_factory) -> None:
    app = create_app()
    async with client_factory(app) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_default_settings_use_local_sqlite() -> None:
    settings = Settings()

    assert settings.database_url.startswith("sqlite+aiosqlite")
    assert settings.dart_fetch_concurrency == 4
    assert settings.entry_collector_script.name == "collect-entries.js"
