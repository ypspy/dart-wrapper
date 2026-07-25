"""Admin 운영 화면. 수집 시작·재개와 슬라이스 완전성 모니터를 제공한다.

1인 운영을 전제로 계정 체계 대신 공유 토큰 쿠키만 사용한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import (
    ADMIN_TOKEN_COOKIE,
    get_catalog_service,
    get_settings_dep,
    get_slice_query_service,
)
from app.config import Settings
from app.schemas.catalog import ExtractRequest, ResumeRequest
from app.services.catalog_service import CatalogService
from app.services.slice_query_service import SliceQueryService

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 지연 등록·정정 공시를 놓치지 않도록 기본 수집 범위는 최근 7일을 겹쳐 잡는다.
DEFAULT_RESCAN_DAYS = 7

router = APIRouter(prefix="/admin", tags=["Admin UI"], include_in_schema=False)


def _has_valid_token(request: Request, settings: Settings) -> bool:
    """쿠키에 담긴 Admin 토큰이 설정과 일치하는지 확인한다."""
    return request.cookies.get(ADMIN_TOKEN_COOKIE) == settings.admin_token


def _default_range() -> tuple[str, str]:
    """기본 수집 기간(최근 7일)을 YYYYMMDD로 만든다."""
    today = date.today()
    start = today - timedelta(days=DEFAULT_RESCAN_DAYS - 1)
    return start.strftime("%Y%m%d"), today.strftime("%Y%m%d")


def _to_token_page() -> RedirectResponse:
    """토큰 입력 화면으로 보낸다."""
    return RedirectResponse("/admin/token")


@router.get("/token", response_class=HTMLResponse, summary="Admin 토큰 입력")
async def token_form(request: Request) -> HTMLResponse:
    """토큰 입력 화면을 보여준다."""
    return templates.TemplateResponse(request, "admin/token.html", {"error": None})


@router.post("/token", response_class=HTMLResponse, summary="Admin 토큰 저장")
async def submit_token(
    request: Request,
    token: str = Form(),
    settings: Settings = Depends(get_settings_dep),
) -> HTMLResponse:
    """토큰이 맞으면 쿠키에 담고 대시보드로 보낸다."""
    if token != settings.admin_token:
        return templates.TemplateResponse(
            request,
            "admin/token.html",
            {"error": "토큰이 올바르지 않습니다. 다시 입력해 주세요."},
        )

    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(ADMIN_TOKEN_COOKIE, token, httponly=True, samesite="lax")
    return response


@router.get("", response_class=HTMLResponse, summary="Admin 대시보드")
async def dashboard(
    request: Request,
    report_type: str = "F001",
    settings: Settings = Depends(get_settings_dep),
    slices: SliceQueryService = Depends(get_slice_query_service),
) -> HTMLResponse:
    """수집 폼과 날짜 슬라이스 완전성 현황을 보여준다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    start_date, end_date = _default_range()
    listing = await slices.list_slices(report_type=report_type or None)
    return templates.TemplateResponse(
        request,
        "admin/index.html",
        {
            "report_type": report_type,
            "start_date": start_date,
            "end_date": end_date,
            "slices": listing.items,
        },
    )


@router.get("/slices", response_class=HTMLResponse, summary="슬라이스 표 부분 갱신")
async def slices_partial(
    request: Request,
    report_type: str = "F001",
    settings: Settings = Depends(get_settings_dep),
    slices: SliceQueryService = Depends(get_slice_query_service),
) -> HTMLResponse:
    """HTMX 폴링으로 표만 다시 그린다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    listing = await slices.list_slices(report_type=report_type or None)
    return templates.TemplateResponse(
        request,
        "admin/partials/slices_table.html",
        {"slices": listing.items},
    )


@router.get("/slices/{slice_id}", response_class=HTMLResponse, summary="슬라이스 상세")
async def slice_detail(
    request: Request,
    slice_id: str,
    settings: Settings = Depends(get_settings_dep),
    slices: SliceQueryService = Depends(get_slice_query_service),
) -> HTMLResponse:
    """슬라이스 요약과 공시별 처리 결과를 보여준다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    detail = await slices.get_slice(slice_id)
    return templates.TemplateResponse(
        request,
        "admin/slice_detail.html",
        {"slice": detail.slice, "attempts": detail.attempts},
    )


@router.post("/collect", summary="수집 시작")
async def start_collect(
    request: Request,
    background_tasks: BackgroundTasks,
    report_type: str = Form(),
    start_date: str = Form(),
    end_date: str = Form(),
    include_attachments: bool = Form(default=False),
    settings: Settings = Depends(get_settings_dep),
    service: CatalogService = Depends(get_catalog_service),
) -> RedirectResponse:
    """폼 입력으로 수집 작업을 시작한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    payload = ExtractRequest(
        report_type=report_type,
        start_date=start_date,
        end_date=end_date,
        include_attachments=include_attachments,
    )
    response = await service.start_extract(payload)
    if response.status == "pending":
        background_tasks.add_task(service.run_job, response.job_id, payload)
    return RedirectResponse(f"/admin?report_type={report_type}", status_code=303)


@router.post("/resume", summary="미완료 슬라이스 이어하기")
async def resume_all(
    request: Request,
    background_tasks: BackgroundTasks,
    report_type: str = Form(),
    settings: Settings = Depends(get_settings_dep),
    service: CatalogService = Depends(get_catalog_service),
) -> RedirectResponse:
    """완료되지 않은 슬라이스를 모두 이어서 처리한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    payload = ResumeRequest(report_type=report_type)
    response = await service.start_resume(payload)
    if response.status == "pending":
        background_tasks.add_task(service.run_resume_job, response.job_id, payload)
    return RedirectResponse(f"/admin?report_type={report_type}", status_code=303)


@router.post("/slices/{slice_id}/retry", summary="슬라이스 실패분 재시도")
async def retry_slice(
    request: Request,
    slice_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings_dep),
    service: CatalogService = Depends(get_catalog_service),
) -> RedirectResponse:
    """해당 슬라이스에서 아직 성공하지 못한 공시만 다시 처리한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    payload = ResumeRequest(slice_id=slice_id)
    response = await service.start_resume(payload)
    if response.status == "pending":
        background_tasks.add_task(service.run_resume_job, response.job_id, payload)
    return RedirectResponse(f"/admin/slices/{slice_id}", status_code=303)
