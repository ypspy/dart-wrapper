"""FastAPI 의존성 정의. 앱 상태(state)에 있는 자원을 요청 단위로 꺼내 쓴다."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.dart_http import DartHttpClient
from app.adapters.llm_date_resolver import LlmDateResolver
from app.config import Settings, get_settings
from app.errors import Unauthorized
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.entry_repository import EntryRepository
from app.repositories.fact_repository import FactRepository
from app.repositories.slice_repository import SliceRepository
from app.services.catalog_query_service import CatalogQueryService
from app.services.catalog_service import CatalogService
from app.services.completeness_service import CompletenessService
from app.services.date_resolver_service import DateResolverService
from app.services.extraction_service import ExtractionService
from app.services.slice_query_service import SliceQueryService
from app.services.viewer_service import ViewerService

ADMIN_TOKEN_HEADER = "X-Admin-Token"
ADMIN_TOKEN_COOKIE = "admin_token"


def get_settings_dep() -> Settings:
    """설정 객체를 반환한다."""
    return get_settings()


def require_admin(request: Request, settings: Settings = Depends(get_settings_dep)) -> None:
    """Admin 요청을 공유 토큰으로 확인한다.

    JSON 호출은 헤더를, 브라우저 화면은 쿠키를 쓴다. 1인 운영을 전제로 계정 체계는 두지 않는다.

    :raises Unauthorized: 토큰이 없거나 일치하지 않는 경우
    """
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


def get_fact_repository(session: AsyncSession = Depends(get_session)) -> FactRepository:
    """감사 추출 결과 저장소를 제공한다."""
    return FactRepository(session)


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


def get_catalog_service(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> CatalogService:
    """Admin 카탈로그 서비스를 제공한다.

    백그라운드 작업이 요청 세션 수명에 묶이지 않도록 세션메이커를 직접 넘긴다.
    중단 요청 상태를 공유해야 하므로 앱 상태에 인스턴스를 하나만 둔다.
    """
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
    return CatalogQueryService(
        DisclosureRepository(session),
        EntryRepository(session),
    )


def get_extraction_service(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> ExtractionService:
    """Admin 감사 추출 서비스를 제공한다.

    백그라운드 작업이 요청 세션 수명에 묶이지 않도록 세션메이커를 직접 넘긴다.
    HTTP 클라이언트를 재사용하므로 앱 상태에 인스턴스를 하나만 둔다.
    """
    service = getattr(request.app.state, "extraction_service", None)
    if service is None:
        http = DartHttpClient(
            request.app.state.http_client,
            timeout_seconds=settings.dart_fetch_timeout_seconds,
            max_retries=settings.dart_fetch_max_retries,
        )
        service = ExtractionService(request.app.state.sessionmaker, http)
        request.app.state.extraction_service = service
    return service


def get_completeness_service(
    session: AsyncSession = Depends(get_session),
) -> CompletenessService:
    """감사 추출 완전성 조회·날짜 보정 서비스를 제공한다."""
    return CompletenessService(session)


def get_date_resolver_service(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> DateResolverService:
    """날짜 LLM 해소 서비스를 제공한다.

    백그라운드 작업이 요청 세션 수명에 묶이지 않도록 세션메이커를 직접 넘긴다.
    """
    service = getattr(request.app.state, "date_resolver_service", None)
    if service is None:
        resolver = LlmDateResolver(
            request.app.state.http_client,
            api_key=settings.date_resolver_api_key,
            model=settings.date_resolver_model,
            prompt_version=settings.date_resolver_prompt_version,
        )
        service = DateResolverService(
            request.app.state.sessionmaker,
            resolver,
            model=settings.date_resolver_model,
            prompt_version=settings.date_resolver_prompt_version,
        )
        request.app.state.date_resolver_service = service
    return service
