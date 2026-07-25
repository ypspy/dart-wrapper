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
from app.schemas.catalog import (
    ExtractRequest,
    JobLogItem,
    JobStatusResponse,
    ResumeRequest,
    SliceListResponse,
    YearSummaryResponse,
)
from app.services.catalog_service import CatalogService
from app.services.slice_query_service import SliceQueryService

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 지연 등록·정정 공시를 놓치지 않도록 기본 수집 범위는 최근 7일을 겹쳐 잡는다.
DEFAULT_RESCAN_DAYS = 7
# 로그 패널은 기본적으로 주의가 필요한 줄만 보여준다.
DEFAULT_LOG_LEVELS = "warn,error"
# 한 해는 최대 366일이므로 연도 슬라이스 조회 상한을 넉넉히 잡는다.
YEAR_SLICE_LIMIT = 400

router = APIRouter(prefix="/admin", tags=["Admin UI"], include_in_schema=False)


def _has_valid_token(request: Request, settings: Settings) -> bool:
    """쿠키에 담긴 Admin 토큰이 설정과 일치하는지 확인한다."""
    return request.cookies.get(ADMIN_TOKEN_COOKIE) == settings.admin_token


def _resolve_year(year: int | None, summary: YearSummaryResponse) -> int:
    """요청한 연도가 요약 범위 밖이면 기본 선택 연도로 되돌린다."""
    if year is not None and any(item.year == year for item in summary.items):
        return year
    return summary.selected_year


async def _list_year_slices(
    slices: SliceQueryService,
    report_type: str,
    year: int,
) -> SliceListResponse:
    """선택 연도 한 해의 슬라이스를 모두 가져온다."""
    return await slices.list_slices(
        report_type=report_type or None,
        start_date=f"{year}0101",
        end_date=f"{year}1231",
        limit=YEAR_SLICE_LIMIT,
    )


def _filter_logs(job: JobStatusResponse | None, levels: str) -> list[JobLogItem]:
    """작업 로그에서 요청한 레벨만 남긴다."""
    if job is None:
        return []

    allowed = {level.strip().lower() for level in levels.split(",") if level.strip()}
    if not allowed:
        return list(job.logs)
    return [log for log in job.logs if log.level.lower() in allowed]


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
    year: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    expand_form: bool = False,
    settings: Settings = Depends(get_settings_dep),
    slices: SliceQueryService = Depends(get_slice_query_service),
    service: CatalogService = Depends(get_catalog_service),
) -> HTMLResponse:
    """왼쪽 완전성 탐색과 오른쪽 실행 컨트롤을 함께 보여준다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    default_start, default_end = _default_range()
    summary = await slices.year_summary(report_type=report_type or None)
    selected_year = _resolve_year(year, summary)
    heatmap = await slices.heatmap(year=selected_year, report_type=report_type or None)
    listing = await _list_year_slices(slices, report_type, selected_year)
    job = await service.get_latest_status()
    return templates.TemplateResponse(
        request,
        "admin/index.html",
        {
            "report_type": report_type,
            "start_date": start_date or default_start,
            "end_date": end_date or default_end,
            "expand_form": expand_form,
            "year_summary": summary,
            "selected_year": selected_year,
            "heatmap": heatmap,
            "slices": listing.items,
            "problem_slices": [row for row in listing.items if row.status != "complete"],
            "job": job,
            "logs": _filter_logs(job, DEFAULT_LOG_LEVELS),
        },
    )


@router.get("/year-bar", response_class=HTMLResponse, summary="연도 요약 바 갱신")
async def year_bar_partial(
    request: Request,
    report_type: str = "F001",
    year: int | None = None,
    settings: Settings = Depends(get_settings_dep),
    slices: SliceQueryService = Depends(get_slice_query_service),
) -> HTMLResponse:
    """연도별 완전성 요약 막대를 반환한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    summary = await slices.year_summary(report_type=report_type or None)
    return templates.TemplateResponse(
        request,
        "admin/partials/year_bar.html",
        {
            "year_summary": summary,
            "selected_year": _resolve_year(year, summary),
            "report_type": report_type,
        },
    )


@router.get("/heatmap", response_class=HTMLResponse, summary="연간 완전성 히트맵 갱신")
async def heatmap_partial(
    request: Request,
    report_type: str = "F001",
    year: int | None = None,
    settings: Settings = Depends(get_settings_dep),
    slices: SliceQueryService = Depends(get_slice_query_service),
) -> HTMLResponse:
    """HTMX 요청에 선택 연도의 일별 완전성 히트맵을 반환한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    summary = await slices.year_summary(report_type=report_type or None)
    selected_year = _resolve_year(year, summary)
    heatmap = await slices.heatmap(year=selected_year, report_type=report_type or None)
    return templates.TemplateResponse(
        request,
        "admin/partials/heatmap.html",
        {"heatmap": heatmap, "selected_year": selected_year},
    )


@router.get("/slices-summary", response_class=HTMLResponse, summary="선택 연도 슬라이스 요약")
async def slices_summary_partial(
    request: Request,
    report_type: str = "F001",
    year: int | None = None,
    settings: Settings = Depends(get_settings_dep),
    slices: SliceQueryService = Depends(get_slice_query_service),
) -> HTMLResponse:
    """선택 연도의 미완료 슬라이스 요약과 전체 표를 반환한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    summary = await slices.year_summary(report_type=report_type or None)
    selected_year = _resolve_year(year, summary)
    listing = await _list_year_slices(slices, report_type, selected_year)
    return templates.TemplateResponse(
        request,
        "admin/partials/slices_summary.html",
        {
            "report_type": report_type,
            "slices": listing.items,
            "problem_slices": [row for row in listing.items if row.status != "complete"],
        },
    )


@router.get("/job-status", response_class=HTMLResponse, summary="최신 작업 상태 카드")
async def job_status_partial(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    service: CatalogService = Depends(get_catalog_service),
) -> HTMLResponse:
    """가장 최근 수집 작업의 상태 카드를 반환한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    job = await service.get_latest_status()
    return templates.TemplateResponse(
        request,
        "admin/partials/job_card.html",
        {"job": job},
    )


@router.get("/job-logs", response_class=HTMLResponse, summary="최신 작업 로그")
async def job_logs_partial(
    request: Request,
    levels: str = DEFAULT_LOG_LEVELS,
    settings: Settings = Depends(get_settings_dep),
    service: CatalogService = Depends(get_catalog_service),
) -> HTMLResponse:
    """가장 최근 작업의 로그를 지정한 레벨만 걸러 반환한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    job = await service.get_latest_status()
    return templates.TemplateResponse(
        request,
        "admin/partials/job_logs.html",
        {"logs": _filter_logs(job, levels)},
    )


@router.post("/jobs/{job_id}/soft-stop", summary="작업 중단 요청")
async def soft_stop_job(
    request: Request,
    job_id: str,
    settings: Settings = Depends(get_settings_dep),
    service: CatalogService = Depends(get_catalog_service),
) -> RedirectResponse:
    """진행 중인 작업을 다음 공시 경계에서 멈추도록 요청한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    await service.request_soft_stop(job_id)
    return RedirectResponse("/admin", status_code=303)


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
