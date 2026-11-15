"""로컬·공개 앱이 공유하는 팩토리."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.dart_http import DartHttpClient
from app.api.admin import catalog as admin_catalog
from app.api.admin import collect_ui
from app.api.catalog import ui as catalog_ui
from app.api.v1 import catalog as catalog_query
from app.api.v1 import viewer
from app.config import Settings, get_settings
from app.db.catalog_guard import block_first_layer_writes, verify_catalog_schema
from app.db.session import create_db_engine, create_sessionmaker, ensure_schema
from app.errors import register_exception_handlers

logger = logging.getLogger(__name__)

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
async def local_lifespan(app: FastAPI, *, catalog_writes: bool = True) -> AsyncIterator[None]:
    """수집용 Node 수집기와 열람용 DART 클라이언트를 연다.

    catalog_writes가 거짓이면 1층 스키마를 보강하지 않고 진행 중 수집 작업도 그대로 둔다.
    """
    from app.adapters.node_entry_collector import NodeEntryCollector
    from app.repositories.job_repository import JobRepository

    settings: Settings = app.state.settings
    engine = create_db_engine(settings.database_url)
    if not catalog_writes:
        await _prepare_readonly_catalog(app, engine, settings)
        try:
            yield
        finally:
            await app.state.http_client.aclose()
            await engine.dispose()
        return

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


async def _prepare_readonly_catalog(app: FastAPI, engine: AsyncEngine, settings: Settings) -> None:
    """1층은 읽기만 확인한다. 실패하면 엔진과 HTTP 클라이언트를 닫고 예외를 다시 올린다."""
    from app.adapters.node_entry_collector import NodeEntryCollector
    from app.repositories.job_repository import JobRepository

    http_client: httpx.AsyncClient | None = None
    try:
        with block_first_layer_writes(engine.sync_engine):
            await verify_catalog_schema(engine)
            sessionmaker = create_sessionmaker(engine)
            async with sessionmaker() as session:
                active = await JobRepository(session).list_active()
        if active:
            preview = ", ".join(job.job_id[:8] for job in active)
            logger.warning(
                "연구 추출 앱은 catalog_jobs를 바꾸지 않습니다. "
                "진행 중 수집 작업 %d건(%s)을 그대로 둡니다. "
                "정리는 수집 쪽에서 하세요.",
                len(active),
                preview,
            )
        logger.warning(
            "연구 추출 앱: 1층 테이블 쓰기를 막았습니다"
            "(RESEARCH_ALLOW_CATALOG_WRITES=false). "
            "스키마 보강과 작업 정리는 하지 않습니다."
        )
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
    except Exception:
        if http_client is not None:
            await http_client.aclose()
        await engine.dispose()
        raise


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


def create_local_app(*, catalog_writes: bool = True) -> FastAPI:
    """수집 Admin과 열람을 제공하는 앱을 만든다.

    catalog_writes 기본값은 참이다. 연구 추출 앱만 거짓으로 넘겨 1층 쓰기를 막는다.
    """
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        async with local_lifespan(app, catalog_writes=catalog_writes):
            yield

    app = FastAPI(title="DART 공시 수집", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(admin_catalog.router)
    app.include_router(collect_ui.router)
    _read_routers(app)
    return app
