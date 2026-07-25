"""Admin 카탈로그 수집 라우터."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.api.deps import get_catalog_service
from app.schemas.catalog import ExtractRequest, ExtractResponse, JobStatusResponse
from app.services.catalog_service import CatalogService

router = APIRouter(prefix="/admin/catalog", tags=["Admin"])


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


@router.get("/status", response_model=JobStatusResponse, summary="수집 현황 및 로그 조회")
async def read_catalog_status(
    job_id: str = Query(description="수집 작업 식별자"),
    service: CatalogService = Depends(get_catalog_service),
) -> JobStatusResponse:
    """수집 작업의 상태·진행 수치·최근 로그를 반환한다."""
    return await service.get_status(job_id)
