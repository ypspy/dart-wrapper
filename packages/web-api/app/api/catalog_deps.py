"""수집·카탈로그·Viewer 의존성. 연구 모듈을 불러오지 않는다."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.errors import Unauthorized
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.entry_repository import EntryRepository
from app.repositories.slice_repository import SliceRepository
from app.services.catalog_query_service import CatalogQueryService
from app.services.catalog_service import CatalogService
from app.services.slice_query_service import SliceQueryService
from app.services.viewer_service import ViewerService

ADMIN_TOKEN_HEADER = "X-Admin-Token"
ADMIN_TOKEN_COOKIE = "admin_token"


def get_settings_dep() -> Settings:
    """설정 객체를 반환한다."""
    return get_settings()


def require_admin(request: Request, settings: Settings = Depends(get_settings_dep)) -> None:
    """Admin 요청을 공유 토큰으로 확인한다."""
    provided = request.headers.get(ADMIN_TOKEN_HEADER) or request.cookies.get(ADMIN_TOKEN_COOKIE)
    if not provided:
        raise Unauthorized("Admin 토큰이 필요합니다. X-Admin-Token 헤더를 확인해 주세요.")
    if provided != settings.admin_token:
        raise Unauthorized("Admin 토큰이 올바르지 않습니다.")


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
) -> ViewerService:
    """Viewer 서비스를 제공한다. 섹션은 한 번에 하나씩 가져온다."""
    return ViewerService(entries, request.app.state.dart_http, concurrency=1)


def get_catalog_service(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> CatalogService:
    """Admin 카탈로그 서비스를 제공한다."""
    service = getattr(request.app.state, "catalog_service", None)
    if service is None:
        service = CatalogService(
            request.app.state.sessionmaker,
            request.app.state.entry_collector,
            max_retries=settings.disclosure_max_retries,
            block_streak_threshold=settings.block_streak_threshold,
            block_wait_seconds=settings.block_wait_seconds,
        )
        request.app.state.catalog_service = service
    return service


def get_slice_query_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
) -> SliceQueryService:
    """슬라이스 완전성 조회 서비스를 제공한다."""
    return SliceQueryService(
        SliceRepository(session),
        settings.heatmap_report_type_list,
    )


def get_catalog_query_service(
    session: AsyncSession = Depends(get_session),
) -> CatalogQueryService:
    """Public 카탈로그 조회 서비스를 제공한다."""
    return CatalogQueryService(DisclosureRepository(session), EntryRepository(session))
