"""Admin 감사 추출·완전성 라우터."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.api.deps import (
    get_completeness_service,
    get_extraction_service,
    require_admin,
)
from app.schemas.extract import (
    CompletenessResponse,
    DateOverrideRequest,
    DateOverrideResponse,
    ExtractAuditRequest,
    ExtractAuditResponse,
    ExtractJobStatusResponse,
)
from app.services.completeness_service import CompletenessService
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
