"""Admin 카탈로그 수집·재개·완전성 라우터."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.api.deps import get_catalog_service, get_slice_query_service, require_admin
from app.schemas.catalog import (
    ExtractRequest,
    ExtractResponse,
    JobStatusResponse,
    ResumeRequest,
    SliceDetailResponse,
    SliceListResponse,
)
from app.services.catalog_service import CatalogService
from app.services.slice_query_service import SliceQueryService

router = APIRouter(prefix="/admin/catalog", tags=["Admin"], dependencies=[Depends(require_admin)])


@router.post(
    "/extract",
    response_model=ExtractResponse,
    status_code=202,
    summary="기간/기업별 공시 수집 트리거",
)
async def extract_catalog(
    payload: ExtractRequest,
    background_tasks: BackgroundTasks,
    service: CatalogService = Depends(get_catalog_service),
) -> ExtractResponse:
    """수집 작업을 등록하고 즉시 job_id를 반환한다. 실제 수집은 백그라운드에서 진행된다."""
    response = await service.start_extract(payload)
    if response.status == "pending":
        background_tasks.add_task(service.run_job, response.job_id, payload)
    return response


@router.post(
    "/resume",
    response_model=ExtractResponse,
    status_code=202,
    summary="미완료·실패 슬라이스 재개",
)
async def resume_catalog(
    payload: ResumeRequest,
    background_tasks: BackgroundTasks,
    service: CatalogService = Depends(get_catalog_service),
) -> ExtractResponse:
    """완료되지 않은 슬라이스와 실패한 공시만 다시 처리한다."""
    response = await service.start_resume(payload)
    if response.status == "pending":
        background_tasks.add_task(service.run_resume_job, response.job_id, payload)
    return response


@router.get("/status", response_model=JobStatusResponse, summary="수집 현황 및 로그 조회")
async def read_catalog_status(
    job_id: str = Query(description="수집 작업 식별자"),
    service: CatalogService = Depends(get_catalog_service),
) -> JobStatusResponse:
    """수집 작업의 상태·진행 수치·최근 로그를 반환한다."""
    return await service.get_status(job_id)


@router.get("/slices", response_model=SliceListResponse, summary="날짜 슬라이스 완전성 목록")
async def list_slices(
    report_type: str | None = Query(default=None, description="공시 유형"),
    start_date: str | None = Query(default=None, description="시작일 YYYYMMDD"),
    end_date: str | None = Query(default=None, description="종료일 YYYYMMDD"),
    limit: int = Query(default=100, ge=1, le=500),
    service: SliceQueryService = Depends(get_slice_query_service),
) -> SliceListResponse:
    """슬라이스별 목록 건수 대비 성공·실패 현황을 반환한다."""
    return await service.list_slices(
        report_type=report_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


@router.get(
    "/slices/{slice_id}",
    response_model=SliceDetailResponse,
    summary="슬라이스 상세와 공시별 처리 결과",
)
async def read_slice(
    slice_id: str,
    service: SliceQueryService = Depends(get_slice_query_service),
) -> SliceDetailResponse:
    """슬라이스 요약과 공시별 성공·실패 내역을 반환한다."""
    return await service.get_slice(slice_id)


@router.post(
    "/slices/{slice_id}/retry",
    response_model=ExtractResponse,
    status_code=202,
    summary="슬라이스 실패분 재시도",
)
async def retry_slice(
    slice_id: str,
    background_tasks: BackgroundTasks,
    service: CatalogService = Depends(get_catalog_service),
) -> ExtractResponse:
    """해당 슬라이스에서 아직 성공하지 못한 공시만 다시 처리한다."""
    payload = ResumeRequest(slice_id=slice_id)
    response = await service.start_resume(payload)
    if response.status == "pending":
        background_tasks.add_task(service.run_resume_job, response.job_id, payload)
    return response


@router.post("/jobs/{job_id}/soft-stop", status_code=202, summary="진행 중 작업 중단 요청")
async def soft_stop_job(
    job_id: str,
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, str]:
    """다음 공시 경계에서 작업을 멈춘다. 이미 저장된 공시는 유지된다."""
    await service.request_soft_stop(job_id)
    return {"job_id": job_id, "detail": "중단을 요청했습니다."}
