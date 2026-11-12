"""SQLite 엔진의 busy timeout이 연결까지 전달되는지 확인한다."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

from app.db.session import create_db_engine


def test_sqlite_engine_passes_busy_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """sqlite+aiosqlite URL은 connect_args.timeout 60으로 엔진을 만든다."""
    captured: dict[str, Any] = {}

    def fake_create_async_engine(url: str, **kwargs: Any) -> object:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("app.db.session.create_async_engine", fake_create_async_engine)

    create_db_engine("sqlite+aiosqlite:///:memory:")

    assert captured["url"] == "sqlite+aiosqlite:///:memory:"
    assert captured["kwargs"]["future"] is True
    assert captured["kwargs"]["connect_args"] == {"timeout": 60}


def test_plain_sqlite_url_passes_busy_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """sqlite 스킴도 같은 busy timeout을 받는다."""
    captured: dict[str, Any] = {}

    def fake_create_async_engine(url: str, **kwargs: Any) -> object:
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("app.db.session.create_async_engine", fake_create_async_engine)

    create_db_engine("sqlite:///./dart_catalog.db")

    assert captured["kwargs"]["connect_args"] == {"timeout": 60}


def test_non_sqlite_engine_omits_connect_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """SQLite가 아닌 URL에는 connect_args를 넣지 않는다."""
    captured: dict[str, Any] = {}

    def fake_create_async_engine(url: str, **kwargs: Any) -> object:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("app.db.session.create_async_engine", fake_create_async_engine)

    create_db_engine("postgresql+asyncpg://localhost/dart")

    assert captured["url"] == "postgresql+asyncpg://localhost/dart"
    assert captured["kwargs"] == {"future": True}
    assert "connect_args" not in captured["kwargs"]


async def test_sqlite_busy_timeout_reaches_connection() -> None:
    """만든 SQLite 연결의 busy_timeout이 60초(60000ms)다."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as connection:
        timeout_ms = (await connection.execute(text("PRAGMA busy_timeout"))).scalar()
    await engine.dispose()
    assert timeout_ms == 60_000
