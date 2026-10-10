"""추출·회사 업종 Admin 운영 화면."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.admin.collect_ui import (
    _filter_logs,
    _has_valid_token,
    _job_busy,
    _log_levels_for,
    _to_token_page,
)
from app.api.deps import (
    get_catalog_service,
    get_completeness_service,
    get_corp_industry_service,
    get_extraction_service,
    get_settings_dep,
)
from app.config import Settings
from app.errors import BadRequest, CatalogConflict, CatalogNotFound
from app.extracting.field_bundles import BUNDLE_LABELS
from app.report_types import report_type_options
from app.schemas.extract import (
    CompletenessItem,
    CompletenessResponse,
    FieldBundleCountsResponse,
    FieldBundleFailItem,
)
from app.services.catalog_service import CatalogService
from app.services.completeness_service import CompletenessService
from app.services.corp_industry_service import CorpIndustryService
from app.services.extraction_service import ExtractionService

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 연구 창 추출 화면의 기본 기간·유형. 수집 히트맵 유형(A002 등)은 넣지 않는다.
RESEARCH_EXTRACT_START_DATE = "20160101"
RESEARCH_EXTRACT_END_DATE = "20260909"
RESEARCH_EXTRACT_REPORT_TYPES = ("F001", "F002", "A001")
_YYYYMMDD_RE = re.compile(r"^\d{8}$")
_INVALID_EXTRACT_DATES = "시작일과 종료일은 YYYYMMDD 형식이어야 합니다."

router = APIRouter(prefix="/admin", tags=["Admin UI"], include_in_schema=False)


def _extract_dashboard_url(*, notice: str | None = None) -> str:
    """추출 화면으로 돌아갈 때 안내 문구를 유지한다."""
    if notice:
        return f"/admin/extract?notice={quote(notice)}"
    return "/admin/extract"


def _require_extract_dates(start_date: str, end_date: str) -> None:
    """추출 화면 기간이 YYYYMMDD인지 확인한다.

    :raises BadRequest: 형식이 아니면 폼을 리셋하지 않고 notice로 보여 준다.
    """
    if not (_YYYYMMDD_RE.fullmatch(start_date) and _YYYYMMDD_RE.fullmatch(end_date)):
        raise BadRequest(_INVALID_EXTRACT_DATES)


async def _extract_completeness_rows(
    service: CompletenessService,
    start_date: str,
    end_date: str,
) -> list[tuple[str, CompletenessResponse]]:
    """연구 창 세 유형을 한 번의 기간 스캔으로 집계한다."""
    summaries = await service.summarize_many(
        start_date=start_date,
        end_date=end_date,
        report_types=list(RESEARCH_EXTRACT_REPORT_TYPES),
    )
    return [(report_type, summaries[report_type]) for report_type in RESEARCH_EXTRACT_REPORT_TYPES]


def _resolve_extract_window(
    start_date: str | None,
    end_date: str | None,
) -> tuple[str, str, str | None]:
    """쿼리 기간을 유지하고, 형식이 아니면 notice만 붙인다."""
    resolved_start = start_date or RESEARCH_EXTRACT_START_DATE
    resolved_end = end_date or RESEARCH_EXTRACT_END_DATE
    try:
        _require_extract_dates(resolved_start, resolved_end)
    except BadRequest as exc:
        return resolved_start, resolved_end, str(exc)
    return resolved_start, resolved_end, None


async def _extract_completeness_page(
    service: CompletenessService,
    start_date: str | None,
    end_date: str | None,
) -> tuple[
    str,
    str,
    str | None,
    list[tuple[str, CompletenessResponse]],
    FieldBundleCountsResponse | None,
]:
    """쿼리 기간을 유지하고, 형식이 맞으면 세 카드와 12묶음 집계를 채운다."""
    resolved_start, resolved_end, date_notice = _resolve_extract_window(start_date, end_date)
    if date_notice:
        return resolved_start, resolved_end, date_notice, [], None
    rows = await _extract_completeness_rows(service, resolved_start, resolved_end)
    field_bundles = await service.summarize_field_bundles(
        start_date=resolved_start,
        end_date=resolved_end,
    )
    return resolved_start, resolved_end, None, rows, field_bundles


async def _extract_ops_context(
    extraction: ExtractionService,
    catalog: CatalogService,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    report_types: list[str] | None = None,
    mode: str | None = None,
    notice: str | None = None,
    completeness_rows: list[tuple[str, CompletenessResponse]] | None = None,
) -> dict[str, object]:
    """추출 화면과 HTMX 조각이 공유하는 컨텍스트를 만든다."""
    extract_job = await extraction.get_latest_status()
    catalog_job = await catalog.get_latest_status()
    selected_types = (
        [code.strip().upper() for code in report_types if code.strip()]
        if report_types is not None
        else list(RESEARCH_EXTRACT_REPORT_TYPES)
    )
    selected_mode = (mode or "extract").strip() or "extract"
    return {
        "ops_section": "extract",
        "start_date": start_date or RESEARCH_EXTRACT_START_DATE,
        "end_date": end_date or RESEARCH_EXTRACT_END_DATE,
        "report_types": selected_types,
        "extract_report_type_options": report_type_options(RESEARCH_EXTRACT_REPORT_TYPES),
        "mode": selected_mode,
        "job": extract_job,
        "extract_job": extract_job,
        "catalog_job": catalog_job,
        "extract_busy": _job_busy(extract_job),
        "catalog_busy": _job_busy(catalog_job),
        "logs": _filter_logs(extract_job, _log_levels_for(extract_job)),
        "notice": notice,
        "completeness_rows": completeness_rows or [],
        "bundle_labels": list(BUNDLE_LABELS.items()),
    }


async def _corp_panel_context(
    settings: Settings,
    service: CorpIndustryService,
) -> dict[str, object]:
    """회사 업종 요약과 최신 작업을 패널 컨텍스트로 만든다."""
    summary = await service.summarize()
    try:
        job, logs = await service.get_status(None)
    except CatalogNotFound:
        job, logs = None, []
    return {
        "corps_summary": summary,
        "corps_job": job,
        "corps_logs": logs,
        "corps_stop_requested": (
            job is not None and job.job_id in getattr(service, "_stop_requested", set())
        ),
        "opendart_ready": bool(settings.opendart_api_keys),
    }


@router.get("/extract", response_class=HTMLResponse, summary="추출 Admin 화면")
async def extract_dashboard(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    notice: str | None = None,
    settings: Settings = Depends(get_settings_dep),
    extraction: ExtractionService = Depends(get_extraction_service),
    catalog: CatalogService = Depends(get_catalog_service),
) -> HTMLResponse:
    """유형별 완전성 카드와 잡 카드를 보여 준다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    resolved_start, resolved_end, date_notice = _resolve_extract_window(start_date, end_date)
    context = await _extract_ops_context(
        extraction,
        catalog,
        start_date=resolved_start,
        end_date=resolved_end,
        notice=notice,
        completeness_rows=[],
    )
    context["date_notice"] = date_notice
    return templates.TemplateResponse(
        request,
        "admin/extract.html",
        context,
    )


@router.get(
    "/extract/completeness-cards",
    response_class=HTMLResponse,
    summary="추출 완전성 카드",
)
async def extract_completeness_cards(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    board_type: str | None = None,
    settings: Settings = Depends(get_settings_dep),
    completeness: CompletenessService = Depends(get_completeness_service),
) -> HTMLResponse:
    """세 유형 입수 현황을 한 partial로 반환한다. 60초 폴링용."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    selected = (board_type or "F001").strip().upper()
    if selected not in RESEARCH_EXTRACT_REPORT_TYPES:
        selected = "F001"
    resolved_start, resolved_end, date_notice, rows, field_bundles = (
        await _extract_completeness_page(completeness, start_date, end_date)
    )
    return templates.TemplateResponse(
        request,
        "admin/partials/extract_completeness.html",
        {
            "start_date": resolved_start,
            "end_date": resolved_end,
            "date_notice": date_notice,
            "completeness_rows": rows,
            "field_bundles": field_bundles,
            "board_type": selected,
        },
    )


@router.get(
    "/extract/completeness-items",
    response_class=HTMLResponse,
    summary="추출 완전성 문서 목록",
)
async def extract_completeness_items(
    request: Request,
    report_type: str,
    status: str,
    start_date: str | None = None,
    end_date: str | None = None,
    cursor: str | None = None,
    settings: Settings = Depends(get_settings_dep),
    completeness: CompletenessService = Depends(get_completeness_service),
) -> HTMLResponse:
    """선택한 유형·상태의 문서 식별자 목록을 반환한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    resolved_start = start_date or RESEARCH_EXTRACT_START_DATE
    resolved_end = end_date or RESEARCH_EXTRACT_END_DATE
    notice: str | None = None
    items: list[CompletenessItem] = []
    next_href: str | None = None
    try:
        _require_extract_dates(resolved_start, resolved_end)
        summary = await completeness.summarize(
            start_date=resolved_start,
            end_date=resolved_end,
            report_type=report_type,
            status=status,
            cursor=cursor,
            limit=50,
        )
        items = list(summary.items)
        if summary.next_cursor:
            next_href = (
                "/admin/extract/completeness-items"
                f"?start_date={quote(resolved_start)}"
                f"&end_date={quote(resolved_end)}"
                f"&report_type={quote(report_type)}"
                f"&status={quote(status)}"
                f"&cursor={quote(summary.next_cursor)}"
            )
    except BadRequest as exc:
        notice = str(exc)
    return templates.TemplateResponse(
        request,
        "admin/partials/extract_completeness_items.html",
        {
            "start_date": resolved_start,
            "end_date": resolved_end,
            "report_type": report_type,
            "status": status,
            "items": items,
            "next_href": next_href,
            "notice": notice,
        },
    )


@router.get(
    "/extract/field-bundle-items",
    response_class=HTMLResponse,
    summary="필드 묶음 실패 문서 목록",
)
async def extract_field_bundle_items(
    request: Request,
    bundle: str,
    start_date: str | None = None,
    end_date: str | None = None,
    cursor: str | None = None,
    settings: Settings = Depends(get_settings_dep),
    completeness: CompletenessService = Depends(get_completeness_service),
) -> HTMLResponse:
    """선택한 묶음의 실패 문서와 TSV 링크를 반환한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    resolved_start = start_date or RESEARCH_EXTRACT_START_DATE
    resolved_end = end_date or RESEARCH_EXTRACT_END_DATE
    notice: str | None = None
    items: list[FieldBundleFailItem] = []
    next_href: str | None = None
    export_href = (
        "/admin/extract/audit-opinion/field-bundles/export"
        f"?start_date={quote(resolved_start)}"
        f"&end_date={quote(resolved_end)}"
        f"&bundle={quote(bundle)}"
        "&outcome=fail"
    )
    try:
        _require_extract_dates(resolved_start, resolved_end)
        page = await completeness.list_field_bundle_fail_items(
            start_date=resolved_start,
            end_date=resolved_end,
            bundle=bundle,
            cursor=cursor,
            limit=50,
        )
        items = list(page.items)
        if page.next_cursor:
            next_href = (
                "/admin/extract/field-bundle-items"
                f"?start_date={quote(resolved_start)}"
                f"&end_date={quote(resolved_end)}"
                f"&bundle={quote(bundle)}"
                f"&cursor={quote(page.next_cursor)}"
            )
    except BadRequest as exc:
        notice = str(exc)
    return templates.TemplateResponse(
        request,
        "admin/partials/extract_field_bundle_items.html",
        {
            "start_date": resolved_start,
            "end_date": resolved_end,
            "bundle": bundle,
            "items": items,
            "next_href": next_href,
            "export_href": export_href,
            "notice": notice,
        },
    )


@router.get("/extract/job-status", response_class=HTMLResponse, summary="추출 작업 상태 카드")
async def extract_job_status_partial(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    extraction: ExtractionService = Depends(get_extraction_service),
    catalog: CatalogService = Depends(get_catalog_service),
) -> HTMLResponse:
    """가장 최근 추출 작업의 상태 카드를 반환한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    return templates.TemplateResponse(
        request,
        "admin/partials/extract_job.html",
        await _extract_ops_context(extraction, catalog),
    )


@router.get("/extract/form", response_class=HTMLResponse, summary="추출 시작 폼 갱신")
async def extract_form_partial(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    report_types: list[str] | None = Query(default=None),
    mode: str | None = None,
    settings: Settings = Depends(get_settings_dep),
    extraction: ExtractionService = Depends(get_extraction_service),
    catalog: CatalogService = Depends(get_catalog_service),
) -> HTMLResponse:
    """진행 중 여부에 따라 추출 폼 활성/비활성 상태를 갱신한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    return templates.TemplateResponse(
        request,
        "admin/partials/extract_form.html",
        await _extract_ops_context(
            extraction,
            catalog,
            start_date=start_date,
            end_date=end_date,
            report_types=report_types,
            mode=mode,
        ),
    )


@router.get("/extract/logs", response_class=HTMLResponse, summary="추출 작업 로그")
async def extract_logs_partial(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    extraction: ExtractionService = Depends(get_extraction_service),
    catalog: CatalogService = Depends(get_catalog_service),
) -> HTMLResponse:
    """가장 최근 추출 작업의 로그를 보여준다. 실행 중이면 info도 포함한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    return templates.TemplateResponse(
        request,
        "admin/partials/extract_logs.html",
        await _extract_ops_context(extraction, catalog),
    )


@router.post("/extract/start", summary="추출 시작")
async def start_extract(
    request: Request,
    background_tasks: BackgroundTasks,
    start_date: str = Form(),
    end_date: str = Form(),
    report_types: list[str] = Form(default=[]),
    mode: str = Form(),
    settings: Settings = Depends(get_settings_dep),
    service: ExtractionService = Depends(get_extraction_service),
) -> RedirectResponse:
    """폼 입력으로 감사 추출 작업을 시작하고 추출 화면으로 돌아간다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    try:
        if not report_types:
            raise BadRequest("유형을 하나 이상 선택해 주세요.")
        job_id = await service.start(start_date, end_date, report_types, mode)
    except (CatalogConflict, BadRequest) as exc:
        return RedirectResponse(
            _extract_dashboard_url(notice=str(exc)),
            status_code=303,
        )
    background_tasks.add_task(service.run_job, job_id)
    return RedirectResponse(_extract_dashboard_url(), status_code=303)


@router.post("/extract/jobs/{job_id}/stop", summary="추출 작업 중단")
async def stop_extract_job(
    request: Request,
    job_id: str,
    settings: Settings = Depends(get_settings_dep),
    service: ExtractionService = Depends(get_extraction_service),
) -> RedirectResponse:
    """다음 접수 경계에서 추출을 멈추도록 요청한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    await service.request_soft_stop(job_id)
    return RedirectResponse(_extract_dashboard_url(), status_code=303)


@router.post("/extract/jobs/{job_id}/finish", summary="추출 작업 강제 종료")
async def finish_extract_job(
    request: Request,
    job_id: str,
    settings: Settings = Depends(get_settings_dep),
    service: ExtractionService = Depends(get_extraction_service),
) -> RedirectResponse:
    """멈춘 추출 잡을 즉시 마감해 DART 잠금을 푼다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    await service.force_finish(job_id)
    return RedirectResponse(_extract_dashboard_url(), status_code=303)


@router.get("/corps-panel", response_class=HTMLResponse, summary="회사 업종 패널 갱신")
async def corps_panel_partial(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    service: CorpIndustryService = Depends(get_corp_industry_service),
) -> HTMLResponse:
    """회사 업종 회사 수와 최신 작업 상태를 반환한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    return templates.TemplateResponse(
        request,
        "admin/partials/corps_panel.html",
        await _corp_panel_context(settings, service),
    )


@router.post("/corps/start", summary="회사 업종 채움 시작")
async def start_corps(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings_dep),
    service: CorpIndustryService = Depends(get_corp_industry_service),
) -> RedirectResponse:
    """빠진 회사 업종 채움 작업을 시작하고 대시보드로 돌아간다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()
    if not settings.opendart_api_keys:
        return RedirectResponse("/admin", status_code=303)

    try:
        job_id = await service.start()
    except (CatalogConflict, BadRequest):
        return RedirectResponse("/admin", status_code=303)
    background_tasks.add_task(service.run_job, job_id)
    return RedirectResponse("/admin", status_code=303)


@router.post("/corps/jobs/{job_id}/stop", summary="회사 업종 작업 중단")
async def stop_corps_job(
    request: Request,
    job_id: str,
    settings: Settings = Depends(get_settings_dep),
    service: CorpIndustryService = Depends(get_corp_industry_service),
) -> RedirectResponse:
    """회사 업종 작업에 소프트 스톱을 요청한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    await service.request_soft_stop(job_id)
    return RedirectResponse("/admin", status_code=303)


@router.post("/corps/jobs/{job_id}/finish", summary="회사 업종 작업 강제 종료")
async def finish_corps_job(
    request: Request,
    job_id: str,
    settings: Settings = Depends(get_settings_dep),
    service: CorpIndustryService = Depends(get_corp_industry_service),
) -> RedirectResponse:
    """회사 업종 작업을 강제로 부분 종료한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()

    await service.force_finish(job_id)
    return RedirectResponse("/admin", status_code=303)
