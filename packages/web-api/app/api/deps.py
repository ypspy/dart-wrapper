"""FastAPI 의존성 정의. 앱 상태(state)에 있는 자원을 요청 단위로 꺼내 쓴다."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.dart_http import DartHttpClient
from app.config import Settings, get_settings
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.entry_repository import EntryRepository
from app.services.catalog_query_service import CatalogQueryService
from app.services.catalog_service import CatalogService
from app.services.viewer_service import ViewerService


def get_settings_dep() -> Settings:
    """설정 객체를 반환한다."""
    return get_settings()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """요청 단위 DB 세션을 제공한다."""
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


def get_entry_repository(session: AsyncSession = Depends(get_session)) -> EntryRepository:
    """엔트리 저장소를 제공한다."""
    return EntryRepository(session)


def get_viewer_service(
    request: Request,
    entries: EntryRepository = Depends(get_entry_repository),
    settings: Settings = Depends(get_settings_dep),
) -> ViewerService:
    """Viewer 서비스를 제공한다. httpx 클라이언트는 앱 전체에서 재사용한다."""
    http = DartHttpClient(
        request.app.state.http_client,
        timeout_seconds=settings.dart_fetch_timeout_seconds,
        max_retries=settings.dart_fetch_max_retries,
    )
    return ViewerService(entries, http, concurrency=settings.dart_fetch_concurrency)


def get_catalog_service(request: Request) -> CatalogService:
    """Admin 카탈로그 서비스를 제공한다.

    백그라운드 작업이 요청 세션 수명에 묶이지 않도록 세션메이커를 직접 넘긴다.
    """
    return CatalogService(
        request.app.state.sessionmaker,
        request.app.state.entry_collector,
    )


def get_catalog_query_service(
    session: AsyncSession = Depends(get_session),
) -> CatalogQueryService:
    """Public 카탈로그 조회 서비스를 제공한다."""
    return CatalogQueryService(
        DisclosureRepository(session),
        EntryRepository(session),
    )
