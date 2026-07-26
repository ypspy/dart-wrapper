"""Public Browse UI 라우터.

공시 목록 → leaf 목차 → 섹션 본문을 서버 렌더링으로 제공한다. 브라우저가 JSON API를
직접 호출하지 않고, 서버가 CatalogQueryService/ViewerService를 그대로 사용한다.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import get_catalog_query_service, get_settings_dep
from app.config import Settings
from app.errors import BadRequest
from app.report_types import report_type_label, report_type_options
from app.services.catalog_query_service import CatalogQueryService

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["report_type_label"] = report_type_label

router = APIRouter(prefix="/browse", tags=["Browse UI"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
async def browse_list(
    request: Request,
    corp_code: str | None = None,
    corp_name: str | None = None,
    report_nm: str | None = None,
    report_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
    catalog: CatalogQueryService = Depends(get_catalog_query_service),
    settings: Settings = Depends(get_settings_dep),
) -> HTMLResponse:
    """공시 목록을 필터·cursor와 함께 렌더링한다."""
    safe_limit = min(max(limit, 1), 100)
    query = {
        "corp_code": corp_code or None,
        "corp_name": corp_name or None,
        "report_nm": report_nm or None,
        "report_type": report_type or None,
        "start_date": start_date or None,
        "end_date": end_date or None,
        "limit": safe_limit,
    }

    cursor_error: str | None = None
    try:
        result = await catalog.list_disclosures(cursor=cursor, **query)
    except BadRequest as exc:
        # 손상된 cursor는 안내만 하고 첫 페이지로 되돌린다.
        cursor_error = str(exc)
        result = await catalog.list_disclosures(cursor=None, **query)

    filters = {
        "corp_code": corp_code or "",
        "corp_name": corp_name or "",
        "report_nm": report_nm or "",
        "report_type": report_type or "",
        "start_date": start_date or "",
        "end_date": end_date or "",
        "limit": safe_limit,
    }
    return templates.TemplateResponse(
        request,
        "browse/list.html",
        {
            "items": result.items,
            "next_cursor": result.next_cursor,
            "cursor_error": cursor_error,
            "filters": filters,
            "report_type_options": report_type_options(settings.heatmap_report_type_list),
        },
    )
