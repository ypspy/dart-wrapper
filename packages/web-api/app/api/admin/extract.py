"""Admin 감사 추출·완전성 라우터."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response

from app.api.deps import (
    get_completeness_service,
    get_date_resolver_service,
    get_extraction_service,
    get_settings_dep,
    require_admin,
)
from app.config import Settings
from app.errors import BadRequest
from app.extracting.field_bundles import EXPORT_PAGE_SIZE
from app.schemas.extract import (
    CompletenessResponse,
    DateOverrideRequest,
    DateOverrideResponse,
    ExtractAuditRequest,
    ExtractAuditResponse,
    ExtractJobStatusResponse,
    FieldBundleCountsResponse,
    FieldBundleFailListResponse,
    ResolveDatesRequest,
    ResolveDatesResponse,
)
from app.services.completeness_service import CompletenessService
from app.services.date_resolver_service import DateResolverService
from app.services.extraction_service import ExtractionService

router = APIRouter(
    prefix="/admin/extract",
    tags=["Admin"],
    dependencies=[Depends(require_admin)],
)


@router.post(
    "/audit-opinion",
    response_model=ExtractAuditResponse,
    status_code=202,
    summary="감사보고서 추출 트리거",
)
async def extract_audit_opinion(
    payload: ExtractAuditRequest,
    background_tasks: BackgroundTasks,
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractAuditResponse:
    """추출 작업을 등록하고 즉시 job_id를 반환한다. 실제 추출은 백그라운드에서 진행된다."""
    job_id = await service.start(
        payload.start_date,
        payload.end_date,
        payload.report_types,
        payload.mode,
    )
    background_tasks.add_task(service.run_job, job_id)
    return ExtractAuditResponse(job_id=job_id, status="pending", mode=payload.mode)


@router.get(
    "/status",
    response_model=ExtractJobStatusResponse,
    summary="추출 작업 현황 및 로그 조회",
)
async def read_extract_status(
    job_id: str = Query(description="추출 작업 식별자"),
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractJobStatusResponse:
    """추출 작업의 상태·파라미터·최근 로그를 반환한다."""
    return await service.get_status(job_id)


@router.post(
    "/jobs/{job_id}/soft-stop",
    status_code=202,
    summary="진행 중 추출 중단 요청",
)
async def soft_stop_extract_job(
    job_id: str,
    service: ExtractionService = Depends(get_extraction_service),
) -> dict[str, str]:
    """다음 접수 경계에서 추출을 멈춘다. 이미 저장한 문서는 유지된다."""
    await service.request_soft_stop(job_id)
    return {"job_id": job_id, "detail": "중단을 요청했습니다."}


@router.post(
    "/jobs/{job_id}/force-finish",
    status_code=202,
    summary="멈춘 추출 작업 강제 종료",
)
async def force_finish_extract_job(
    job_id: str,
    service: ExtractionService = Depends(get_extraction_service),
) -> dict[str, str]:
    """워커가 죽은 추출 잡을 부분 종료해 DART 잠금을 푼다."""
    await service.force_finish(job_id)
    return {"job_id": job_id, "detail": "작업을 강제 종료했습니다."}


@router.get(
    "/audit-opinion/completeness",
    response_model=CompletenessResponse,
    summary="감사 추출 완전성 집계",
)
async def read_completeness(
    start_date: str = Query(pattern=r"^\d{8}$", description="시작일 YYYYMMDD"),
    end_date: str = Query(pattern=r"^\d{8}$", description="종료일 YYYYMMDD"),
    report_type: str = Query(description="공시 유형"),
    status: str | None = Query(default=None, description="목록을 볼 상태 코드"),
    cursor: str | None = Query(default=None, description="다음 페이지 cursor"),
    limit: int = Query(default=50, ge=1, le=200),
    service: CompletenessService = Depends(get_completeness_service),
) -> CompletenessResponse:
    """기간·유형의 추출 건수를 반환하고, status가 있으면 문서 목록도 붙인다."""
    return await service.summarize(
        start_date=start_date,
        end_date=end_date,
        report_type=report_type,
        status=status,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/audit-opinion/field-bundles",
    response_model=FieldBundleCountsResponse,
    summary="추출 필드 묶음 12줄 집계",
)
async def read_field_bundles(
    start_date: str = Query(pattern=r"^\d{8}$"),
    end_date: str = Query(pattern=r"^\d{8}$"),
    service: CompletenessService = Depends(get_completeness_service),
) -> FieldBundleCountsResponse:
    """현재 추출기 ok facts의 12묶음 건수를 반환한다."""
    return await service.summarize_field_bundles(
        start_date=start_date,
        end_date=end_date,
    )


@router.get(
    "/audit-opinion/field-bundles/items",
    response_model=FieldBundleFailListResponse,
    summary="필드 묶음 실패 문서 목록",
)
async def read_field_bundle_items(
    start_date: str = Query(pattern=r"^\d{8}$"),
    end_date: str = Query(pattern=r"^\d{8}$"),
    bundle: str = Query(),
    outcome: str = Query(),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=50),
    service: CompletenessService = Depends(get_completeness_service),
) -> FieldBundleFailListResponse:
    """outcome=fail만 허용한다."""
    if outcome != "fail":
        raise BadRequest("outcome은 fail만 지원합니다. 실패 목록을 요청해 주세요.")
    return await service.list_field_bundle_fail_items(
        start_date=start_date,
        end_date=end_date,
        bundle=bundle,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/audit-opinion/field-bundles/export",
    summary="필드 묶음 실패 TSV",
)
async def export_field_bundle_items(
    start_date: str = Query(pattern=r"^\d{8}$"),
    end_date: str = Query(pattern=r"^\d{8}$"),
    bundle: str = Query(),
    outcome: str = Query(),
    cursor: str | None = Query(default=None),
    service: CompletenessService = Depends(get_completeness_service),
) -> Response:
    """실패 행을 탭 구분 텍스트로 내려 준다. 최대 5000행."""
    if outcome != "fail":
        raise BadRequest("outcome은 fail만 지원합니다. 실패 목록을 요청해 주세요.")
    page = await service.list_field_bundle_fail_items(
        start_date=start_date,
        end_date=end_date,
        bundle=bundle,
        cursor=cursor,
        limit=EXPORT_PAGE_SIZE,
    )
    headers_row = [
        "report_type",
        "rcept_no",
        "dcm_no",
        "fs_scope",
        "bundle",
        "status",
        "extractor_version",
        "viewer_url",
    ]
    lines = ["\t".join(headers_row)]
    for item in page.items:
        lines.append(
            "\t".join(
                [
                    item.report_type,
                    item.rcept_no,
                    item.dcm_no,
                    item.fs_scope,
                    item.bundle,
                    item.status or "",
                    item.extractor_version or "",
                    item.viewer_url or "",
                ]
            )
        )
    headers = {"Content-Type": "text/tab-separated-values; charset=utf-8"}
    if page.next_cursor:
        headers["X-Next-Cursor"] = page.next_cursor
    return Response(content="\n".join(lines) + "\n", headers=headers)


@router.post(
    "/resolve-dates",
    response_model=ResolveDatesResponse,
    status_code=202,
    summary="ambiguous 감사보고서일 LLM 해소",
)
async def resolve_dates(
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings_dep),
    service: DateResolverService = Depends(get_date_resolver_service),
    payload: ResolveDatesRequest = ResolveDatesRequest(),
) -> ResolveDatesResponse:
    """ambiguous 날짜를 LLM 인덱스로 고른다. DART는 호출하지 않는다."""
    if not settings.date_resolver_api_key:
        raise BadRequest(
            "날짜 해소용 API 키가 설정되어 있지 않습니다. "
            "DATE_RESOLVER_API_KEY를 확인한 뒤 다시 시도해 주세요."
        )
    limit = payload.limit
    if limit is not None and limit < 1:
        raise BadRequest("limit는 1 이상의 정수여야 합니다.")
    job_id = await service.start(limit=limit)
    background_tasks.add_task(service.run, job_id)
    return ResolveDatesResponse(job_id=job_id, status="pending")


@router.patch(
    "/audit-opinion/{rcept_no}/{dcm_no}/date",
    response_model=DateOverrideResponse,
    summary="감사보고서일 수동 보정",
)
async def override_audit_report_date(
    rcept_no: str,
    dcm_no: str,
    payload: DateOverrideRequest,
    service: CompletenessService = Depends(get_completeness_service),
) -> DateOverrideResponse:
    """지정한 ISO 날짜를 override로 저장하고 다른 필드는 유지한다."""
    return await service.override_audit_report_date(rcept_no, dcm_no, payload.iso)
