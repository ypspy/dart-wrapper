"""FastAPI 앱 생성, 자원 수명주기 관리, 라우터 등록."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.adapters.node_entry_collector import NodeEntryCollector
from app.api.admin import catalog
from app.api.admin import ui as admin_ui
from app.api.v1 import catalog as catalog_query
from app.api.v1 import viewer
from app.config import get_settings
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import register_exception_handlers

# DART는 일반 브라우저 요청과 유사한 헤더를 기대한다.
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://dart.fss.or.kr/",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """DB 엔진, HTTP 클라이언트, 수집 어댑터를 앱 수명 동안 공유한다."""
    settings = get_settings()

    engine = create_db_engine(settings.database_url)
    await create_all(engine)

    http_client = httpx.AsyncClient(headers=_DEFAULT_HEADERS, follow_redirects=True)

    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.http_client = http_client
    app.state.entry_collector = NodeEntryCollector(
        settings.node_executable,
        settings.entry_collector_script,
        timeout_seconds=settings.collector_timeout_seconds,
    )

    try:
        yield
    finally:
        await http_client.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    """DART 공시 파이프라인 API 앱을 생성한다."""
    app = FastAPI(
        title="DART 공시 파이프라인 API",
        description="Admin 카탈로그 수집과 Public Viewer(Lazy Retrieval)를 제공합니다.",
        version="0.1.0",
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.include_router(catalog.router)
    app.include_router(admin_ui.router)
    app.include_router(catalog_query.router)
    app.include_router(viewer.router)

    @app.get("/health", tags=["시스템"])
    async def health() -> dict[str, str]:
        """서비스 생존 여부를 반환한다."""
        return {"status": "ok"}

    return app


app = create_app()
