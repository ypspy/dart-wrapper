"""Public Catalog HTML 탐색 라우터.

공시 목록과 leaf 전 컬럼 표를 서버 렌더링한다. 본문 Viewer는 포함하지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import get_catalog_query_service
from app.errors import BadRequest, CatalogNotFound
from app.services.catalog_query_service import CatalogQueryService

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/catalog", tags=["Catalog UI"], include_in_schema=False)

DISCLOSURE_COLUMNS: tuple[str, ...] = (
    "rcp_no",
    "corp_code",
    "corp_name",
    "report_nm",
    "report_type",
    "correction_type",
    "submitter",
    "rcept_dt",
    "year_end",
    "bsns_year",
    "entry_count",
    "disclosure_url",
)

ENTRY_COLUMNS: tuple[str, ...] = (
    "ordinal",
    "entry_id",
    "rcept_no",
    "report_type",
    "correction_type",
    "report_nm",
    "year_end",
    "corp_code",
    "corp_name",
    "submitter",
    "rcept_dt",
    "bsns_year",
    "disclosure_url",
    "source",
    "dcm_no",
    "document_name",
    "section_name",
    "section_original_name",
    "depth",
    "is_leaf",
    "parent_ele_id",
    "ele_id",
    "offset",
    "length",
    "dtd",
    "path",
    "viewer_url",
)


def _cell(value: Any) -> str:
    """표 셀용 문자열. 빈 값은 —."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return " › ".join(str(item) for item in value) if value else "—"
    text = str(value)
    return text if text else "—"


def _attr(obj: Any, name: str) -> Any:
    """템플릿에서 동적 속성 조회."""
    return getattr(obj, name, None)


templates.env.globals["catalog_cell"] = _cell
templates.env.globals["attr"] = _attr


@router.get("", response_class=HTMLResponse)
async def catalog_list(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    catalog: CatalogQueryService = Depends(get_catalog_query_service),
) -> HTMLResponse:
    """공시 목록을 DisclosureSummary 전 컬럼 표로 렌더링한다."""
    cursor_error: str | None = None
    try:
        result = await catalog.list_disclosures(limit=limit, cursor=cursor)
    except BadRequest as exc:
        cursor_error = str(exc)
        result = await catalog.list_disclosures(limit=limit, cursor=None)

    next_href: str | None = None
    if result.next_cursor:
        next_href = "/catalog?" + urlencode(
            {"limit": limit, "cursor": result.next_cursor}
        )

    return templates.TemplateResponse(
        request,
        "catalog/list.html",
        {
            "items": result.items,
            "columns": DISCLOSURE_COLUMNS,
            "limit": limit,
            "next_href": next_href,
            "cursor_error": cursor_error,
        },
    )


@router.get("/{rcp_no}", response_class=HTMLResponse)
async def catalog_entries(
    request: Request,
    rcp_no: str,
    catalog: CatalogQueryService = Depends(get_catalog_query_service),
) -> HTMLResponse:
    """공시 메타와 leaf 전 컬럼 표를 렌더링한다."""
    try:
        payload = await catalog.list_entries(rcp_no)
    except CatalogNotFound as exc:
        return templates.TemplateResponse(
            request,
            "catalog/404.html",
            {"message": str(exc)},
            status_code=404,
        )

    return templates.TemplateResponse(
        request,
        "catalog/entries.html",
        {
            "disclosure": payload.disclosure,
            "disclosure_columns": DISCLOSURE_COLUMNS,
            "entries": payload.all_entries,
            "entry_columns": ENTRY_COLUMNS,
        },
    )
