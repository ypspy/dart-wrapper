"""Public Browse UI 라우터.

공시 목록 → leaf 목차 → 섹션 본문을 서버 렌더링으로 제공한다. 브라우저가 JSON API를
직접 호출하지 않고, 서버가 CatalogQueryService/ViewerService를 그대로 사용한다.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import (
    get_catalog_query_service,
    get_entry_repository,
    get_settings_dep,
    get_viewer_service,
)
from app.config import Settings
from app.errors import BadRequest, CatalogNotFound, ParseError, SourceFetchError
from app.report_types import report_type_label, report_type_options
from app.repositories.entry_repository import EntryRepository
from app.services.catalog_query_service import CatalogQueryService
from app.services.viewer_service import ViewerService

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["report_type_label"] = report_type_label

router = APIRouter(prefix="/browse", tags=["Browse UI"], include_in_schema=False)


def _is_htmx(request: Request) -> bool:
    """HTMX가 보낸 부분 갱신 요청인지 확인한다."""
    return request.headers.get("HX-Request", "").lower() == "true"


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


@router.get("/{rcp_no}", response_class=HTMLResponse)
async def browse_disclosure(
    request: Request,
    rcp_no: str,
    catalog: CatalogQueryService = Depends(get_catalog_query_service),
) -> HTMLResponse:
    """공시 상세를 목차|본문 2열로 렌더링한다."""
    try:
        summary = await catalog.get_disclosure(rcp_no)
        toc = await catalog.list_entries(rcp_no)
    except CatalogNotFound as exc:
        return templates.TemplateResponse(
            request,
            "browse/404.html",
            {"message": str(exc)},
            status_code=404,
        )

    # primary가 없으면 처음부터 전체 목차를 펼친다.
    show_all = len(toc.primary_entries) == 0
    entries = toc.all_entries if show_all else toc.primary_entries
    first_entry_id = entries[0].entry_id if entries else None

    return templates.TemplateResponse(
        request,
        "browse/disclosure.html",
        {
            "rcp_no": rcp_no,
            "summary": summary,
            "toc": toc,
            "show_all": show_all,
            "first_entry_id": first_entry_id,
        },
    )


@router.get("/{rcp_no}/sections/{entry_id}", response_class=HTMLResponse)
async def browse_section(
    request: Request,
    rcp_no: str,
    entry_id: str,
    viewer: ViewerService = Depends(get_viewer_service),
    entries: EntryRepository = Depends(get_entry_repository),
) -> HTMLResponse:
    """섹션 본문을 정제해 반환한다.

    HTMX 요청이면 패널 partial만, 직접 접근이면 전체 페이지로 감싼다. 원문 수집·정제
    실패는 페이지 오류가 아니라 패널 안 오류 카드로 처리한다.
    """
    entry = await entries.get_by_entry_id(entry_id)
    viewer_url = entry.viewer_url if entry is not None and entry.rcept_no == rcp_no else None
    htmx = _is_htmx(request)

    try:
        section = await viewer.get_section(rcp_no, entry_id)
    except CatalogNotFound as exc:
        return templates.TemplateResponse(
            request,
            "browse/404.html",
            {"message": str(exc)},
            status_code=404,
        )
    except (SourceFetchError, ParseError) as exc:
        context = {
            "rcp_no": rcp_no,
            "entry_id": entry_id,
            "error": str(exc),
            "viewer_url": viewer_url,
            "panel_template": "browse/partials/section_error.html",
        }
        if htmx:
            return templates.TemplateResponse(request, context["panel_template"], context)
        return templates.TemplateResponse(request, "browse/section_page.html", context)

    context = {
        "rcp_no": rcp_no,
        "entry_id": entry_id,
        "section": section,
        "viewer_url": viewer_url,
        "panel_template": "browse/partials/section.html",
    }
    if htmx:
        return templates.TemplateResponse(request, context["panel_template"], context)
    return templates.TemplateResponse(request, "browse/section_page.html", context)
