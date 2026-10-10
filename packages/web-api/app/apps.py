"""로컬·공개 앱이 공유하는 팩토리."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.adapters.dart_http import DartHttpClient
from app.api.admin import catalog as admin_catalog
from app.api.admin import collect_ui
from app.api.catalog import ui as catalog_ui
from app.api.v1 import catalog as catalog_query
from app.api.v1 import viewer
from app.config import Settings, get_settings
from app.db.session import create_db_engine, create_sessionmaker, ensure_schema
from app.errors import register_exception_handlers

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://dart.fss.or.kr/",
}


def require_postgres_url(database_url: str) -> None:
    """공개 프로세스는 PostgreSQL URL만 받는다."""
    if not database_url.startswith("postgresql+asyncpg://"):
        raise RuntimeError("공개 서버의 DATABASE_URL은 postgresql+asyncpg:// 로 시작해야 합니다.")


def _read_routers(app: FastAPI) -> None:
    app.include_router(catalog_ui.router)
    app.include_router(catalog_query.router)
    app.include_router(viewer.router)

    @app.get("/health", tags=["시스템"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}


def _dart_client(settings: Settings) -> tuple[httpx.AsyncClient, DartHttpClient]:
    http_client = httpx.AsyncClient(headers=_DEFAULT_HEADERS, follow_redirects=True)
    dart_http = DartHttpClient(
        http_client,
        timeout_seconds=settings.dart_fetch_timeout_seconds,
        max_retries=settings.dart_fetch_max_retries,
        min_interval_seconds=settings.dart_fetch_min_interval_seconds,
    )
    return http_client, dart_http


@asynccontextmanager
async def public_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """DB와 열람용 DART 클라이언트만 연다."""
    settings: Settings = app.state.settings
    engine = create_db_engine(settings.database_url)
    await ensure_schema(engine)
    http_client, dart_http = _dart_client(settings)
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.http_client = http_client
    app.state.dart_http = dart_http
    try:
        yield
    finally:
        await http_client.aclose()
        await engine.dispose()


@asynccontextmanager
async def local_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """수집용 Node 수집기와 열람용 DART 클라이언트를 연다."""
    from app.adapters.node_entry_collector import NodeEntryCollector
    from app.repositories.job_repository import JobRepository

    settings: Settings = app.state.settings
    engine = create_db_engine(settings.database_url)
    await ensure_schema(engine)
    http_client, dart_http = _dart_client(settings)
    sessionmaker = create_sessionmaker(engine)
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.http_client = http_client
    app.state.dart_http = dart_http
    app.state.entry_collector = NodeEntryCollector(
        settings.node_executable,
        settings.entry_collector_script,
        timeout_seconds=settings.collector_timeout_seconds,
    )
    async with sessionmaker() as session:
        await JobRepository(session).abandon_orphans()
        await session.commit()
    try:
        yield
    finally:
        await http_client.aclose()
        await engine.dispose()


def create_public_app(settings: Settings) -> FastAPI:
    """카탈로그 조회와 Viewer만 제공하는 앱을 만든다."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        async with public_lifespan(app):
            yield

    app = FastAPI(title="DART 공시 열람", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)
    _read_routers(app)
    return app


def create_local_app() -> FastAPI:
    """수집 Admin과 열람을 제공하는 앱을 만든다."""
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        async with local_lifespan(app):
            yield

    app = FastAPI(title="DART 공시 수집", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(admin_catalog.router)
    app.include_router(collect_ui.router)
    _read_routers(app)
    return app
