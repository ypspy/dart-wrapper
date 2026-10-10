"""FastAPI 의존성 정의. 앱 상태(state)에 있는 자원을 요청 단위로 꺼내 쓴다."""

from __future__ import annotations

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

__all__ = [
    "ADMIN_TOKEN_COOKIE",
    "ADMIN_TOKEN_HEADER",
    "get_catalog_query_service",
    "get_catalog_service",
    "get_entry_repository",
    "get_session",
    "get_settings_dep",
    "get_slice_query_service",
    "get_viewer_service",
    "require_admin",
]
