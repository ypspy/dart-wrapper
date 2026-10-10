"""FastAPI 의존성 정의. 앱 상태(state)에 있는 자원을 요청 단위로 꺼내 쓴다."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm_date_resolver import LlmDateResolver
from app.adapters.opendart_company import OpenDartCompanyClient
from app.config import Settings, get_settings
from app.ksic import load_ksic_tables
from app.repositories.fact_repository import FactRepository
from app.services.fact_query_service import FactQueryService
from app.services.completeness_service import CompletenessService
from app.services.corp_industry_service import CorpIndustryService
from app.services.date_resolver_service import DateResolverService
from app.services.extraction_service import ExtractionService

from app.api.catalog_deps import (
    ADMIN_TOKEN_COOKIE,
    ADMIN_TOKEN_HEADER,
    get_catalog_query_service,
    get_catalog_service,
    get_entry_repository,
    get_session,
    get_settings_dep,
    get_slice_query_service,
    get_viewer_service,
    require_admin,
)


def get_fact_repository(session: AsyncSession = Depends(get_session)) -> FactRepository:
    """감사 추출 결과 저장소를 제공한다."""
    return FactRepository(session)


def get_fact_query_service(
    session: AsyncSession = Depends(get_session),
) -> FactQueryService:
    """Public 추출 목록 조회 서비스를 제공한다."""
    return FactQueryService(FactRepository(session))


def get_extraction_service(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> ExtractionService:
    """Admin 감사 추출 서비스를 제공한다.

    백그라운드 작업이 요청 세션 수명에 묶이지 않도록 세션메이커를 직접 넘긴다.
    DART HTML 클라이언트는 앱 수명 동안 하나다.
    """
    service = getattr(request.app.state, "extraction_service", None)
    if service is None:
        service = ExtractionService(
            request.app.state.sessionmaker,
            request.app.state.dart_http,
            block_streak_threshold=settings.block_streak_threshold,
            block_wait_seconds=settings.block_wait_seconds,
        )
        request.app.state.extraction_service = service
    return service


def get_completeness_service(
    session: AsyncSession = Depends(get_session),
) -> CompletenessService:
    """감사 추출 완전성 조회·날짜 보정 서비스를 제공한다."""
    return CompletenessService(session)


def get_corp_industry_service(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> CorpIndustryService:
    """OpenDART 기업개황으로 회사 업종을 채우는 서비스를 제공한다."""
    service = getattr(request.app.state, "corp_industry_service", None)
    if service is None:
        client = OpenDartCompanyClient(
            request.app.state.opendart_http_client,
            timeout_seconds=settings.opendart_timeout_seconds,
            max_retries=settings.opendart_max_retries,
            max_per_minute=settings.opendart_max_per_minute,
        )
        service = CorpIndustryService(
            request.app.state.sessionmaker,
            client,
            load_ksic_tables(),
            api_keys=settings.opendart_api_keys,
            concurrency=settings.opendart_concurrency,
        )
        request.app.state.corp_industry_service = service
    return service


def get_date_resolver_service(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> DateResolverService:
    """날짜 LLM 해소 서비스를 제공한다.

    백그라운드 작업이 요청 세션 수명에 묶이지 않도록 세션메이커를 직접 넘긴다.
    """
    service = getattr(request.app.state, "date_resolver_service", None)
    if service is None:
        llm_client = getattr(request.app.state, "llm_http_client", None)
        if llm_client is None:
            llm_client = request.app.state.http_client
        resolver = LlmDateResolver(
            llm_client,
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
