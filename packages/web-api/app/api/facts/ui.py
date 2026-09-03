"""Public 추출 결과 HTML 탐색 라우터."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import get_fact_query_service
from app.errors import BadRequest
from app.schemas.facts import LIST_COLUMNS
from app.services.fact_query_service import FactQueryService

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(prefix="/facts", tags=["Facts UI"], include_in_schema=False)


def fact_cell(value: Any) -> str:
    """facts 표 셀. JSON은 compact 한 줄, catalog path 조인을 쓰지 않는다."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        if value == [] or value == {}:
            return "—"
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = str(value)
    return text if text else "—"


def _attr(obj: Any, name: str) -> Any:
    """템플릿에서 동적 속성 조회."""
    return getattr(obj, name, None)


templates.env.globals["fact_cell"] = fact_cell
templates.env.globals["attr"] = _attr


@router.get("", response_class=HTMLResponse)
async def facts_list(
    request: Request,
    corp_code: str | None = None,
    corp_name: str | None = None,
    report_nm: str | None = None,
    report_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    service: FactQueryService = Depends(get_fact_query_service),
) -> HTMLResponse:
    """추출 문서 목록을 조인 메타 + 공개 컬럼 표로 렌더링한다."""
    cursor_error: str | None = None
    try:
        result = await service.list_page(
            corp_code=corp_code,
            corp_name=corp_name,
            report_nm=report_nm,
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            cursor=cursor,
        )
    except BadRequest as exc:
        cursor_error = str(exc)
        result = await service.list_page(
            corp_code=corp_code,
            corp_name=corp_name,
            report_nm=report_nm,
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            cursor=None,
        )
    next_href: str | None = None
    if result.next_cursor:
        params: dict[str, str | int] = {"limit": limit, "cursor": result.next_cursor}
        if corp_code:
            params["corp_code"] = corp_code
        if corp_name:
            params["corp_name"] = corp_name
        if report_nm:
            params["report_nm"] = report_nm
        if report_type:
            params["report_type"] = report_type
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        next_href = "/facts?" + urlencode(params)
    return templates.TemplateResponse(
        request,
        "facts/list.html",
        {
            "items": result.items,
            "columns": LIST_COLUMNS,
            "next_href": next_href,
            "cursor_error": cursor_error,
        },
    )
