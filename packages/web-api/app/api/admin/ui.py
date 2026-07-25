"""Admin 운영 화면. 수집 시작·재개와 슬라이스 완전성 모니터를 제공한다.

1인 운영을 전제로 계정 체계 대신 공유 토큰 쿠키만 사용한다.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

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
from app.errors import CatalogConflict
from app.schemas.catalog import (
    ExtractRequest,
    JobLogItem,
    JobStatusResponse,
    ResumeRequest,
    SliceListResponse,
    YearSummaryResponse,
)
from app.services.catalog_service import CatalogService
from app.services.slice_query_service import SliceQueryService, kst_today, last_closed_date

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 지연 등록·정정 공시를 놓치지 않도록 기본 수집 범위는 최근 7일(마감일 기준)을 겹쳐 잡는다.
DEFAULT_RESCAN_DAYS = 7
# 대기 중일 때는 경고·오류만, 실행 중에는 진행 로그(info)도 보여준다.
IDLE_LOG_LEVELS = "warn,error"
ACTIVE_LOG_LEVELS = "info,warn,error"
ACTIVE_JOB_STATUSES = frozenset({"pending", "running"})
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


def _log_levels_for(job: JobStatusResponse | None) -> str:
    """실행 중이면 진행 로그를 포함하고, 아니면 경고·오류만 보여준다."""
    if job is not None and job.status in ACTIVE_JOB_STATUSES:
        return ACTIVE_LOG_LEVELS
    return IDLE_LOG_LEVELS


def _default_range() -> tuple[str, str]:
    """기본 수집 기간(마감일 기준 최근 7일)을 YYYYMMDD로 만든다."""
    closed = last_closed_date(as_of=kst_today())
    start = closed - timedelta(days=DEFAULT_RESCAN_DAYS - 1)
    return start.strftime("%Y%m%d"), closed.strftime("%Y%m%d")


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
    notice: str | None = None,
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
    job_busy = job is not None and job.status in ACTIVE_JOB_STATUSES
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
            "logs": _filter_logs(job, _log_levels_for(job)),
            "report_types": settings.heatmap_report_type_list,
            "job_busy": job_busy,
            "notice": notice,
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


@router.get("/slices-chips", response_class=HTMLResponse, summary="선택 연도 미완료 칩")
async def slices_chips_partial(
    request: Request,
    report_type: str = "F001",
    year: int | None = None,
    settings: Settings = Depends(get_settings_dep),
    slices: SliceQueryService = Depends(get_slice_query_service),
) -> HTMLResponse:
    """미완료 슬라이스 칩만 갱신한다. 전체 보기·이어하기는 페이지에 고정한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    summary = await slices.year_summary(report_type=report_type or None)
    selected_year = _resolve_year(year, summary)
    listing = await _list_year_slices(slices, report_type, selected_year)
    return templates.TemplateResponse(
        request,
        "admin/partials/slices_chips.html",
        {
            "problem_slices": [row for row in listing.items if row.status != "complete"],
        },
    )


@router.get("/slices-summary", response_class=HTMLResponse, summary="선택 연도 슬라이스 요약")
async def slices_summary_partial(
    request: Request,
    report_type: str = "F001",
    year: int | None = None,
    settings: Settings = Depends(get_settings_dep),
    slices: SliceQueryService = Depends(get_slice_query_service),
) -> HTMLResponse:
    """호환용: 칩·이어하기·전체 보기를 함께 반환한다."""
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


@router.get("/collect-form", response_class=HTMLResponse, summary="수집 폼 갱신")
async def collect_form_partial(
    request: Request,
    report_type: str = "F001",
    start_date: str | None = None,
    end_date: str | None = None,
    expand_form: bool = False,
    settings: Settings = Depends(get_settings_dep),
    service: CatalogService = Depends(get_catalog_service),
) -> HTMLResponse:
    """진행 중 여부에 따라 수집 폼 활성/비활성 상태를 갱신한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    default_start, default_end = _default_range()
    job = await service.get_latest_status()
    return templates.TemplateResponse(
        request,
        "admin/partials/collect_form.html",
        {
            "report_type": report_type,
            "start_date": start_date or default_start,
            "end_date": end_date or default_end,
            "expand_form": expand_form,
            "job_busy": job is not None and job.status in ACTIVE_JOB_STATUSES,
        },
    )


@router.get("/resume-controls", response_class=HTMLResponse, summary="이어하기 버튼 갱신")
async def resume_controls_partial(
    request: Request,
    report_type: str = "F001",
    settings: Settings = Depends(get_settings_dep),
    service: CatalogService = Depends(get_catalog_service),
) -> HTMLResponse:
    """진행 중 여부에 따라 이어하기 버튼 활성/비활성 상태를 갱신한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    job = await service.get_latest_status()
    return templates.TemplateResponse(
        request,
        "admin/partials/resume_controls.html",
        {
            "report_type": report_type,
            "job_busy": job is not None and job.status in ACTIVE_JOB_STATUSES,
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
    levels: str | None = None,
    settings: Settings = Depends(get_settings_dep),
    service: CatalogService = Depends(get_catalog_service),
) -> HTMLResponse:
    """가장 최근 작업의 로그를 보여준다. 실행 중이면 info도 포함한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    job = await service.get_latest_status()
    selected = levels or _log_levels_for(job)
    return templates.TemplateResponse(
        request,
        "admin/partials/job_logs.html",
        {"logs": _filter_logs(job, selected), "job": job},
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
    try:
        response = await service.start_extract(payload)
    except CatalogConflict as exc:
        return RedirectResponse(
            f"/admin?report_type={report_type}&notice={quote(str(exc))}",
            status_code=303,
        )
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
    try:
        response = await service.start_resume(payload)
    except CatalogConflict as exc:
        return RedirectResponse(
            f"/admin?report_type={report_type}&notice={quote(str(exc))}",
            status_code=303,
        )
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
    try:
        response = await service.start_resume(payload)
    except CatalogConflict as exc:
        return RedirectResponse(
            f"/admin/slices/{slice_id}?notice={quote(str(exc))}",
            status_code=303,
        )
    if response.status == "pending":
        background_tasks.add_task(service.run_resume_job, response.job_id, payload)
    return RedirectResponse(f"/admin/slices/{slice_id}", status_code=303)
