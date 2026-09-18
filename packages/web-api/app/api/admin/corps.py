"""회사 업종 Admin JSON 라우터."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.api.deps import (
    get_corp_industry_service,
    get_settings_dep,
    require_admin,
)
from app.config import Settings
from app.errors import BadRequest
from app.schemas.catalog import JobLogItem
from app.schemas.corps import (
    CorpEnrichResponse,
    CorpJobStatusResponse,
    CorpSummaryResponse,
)
from app.services.corp_industry_service import CorpIndustryService

router = APIRouter(
    prefix="/admin/corps",
    tags=["Admin"],
    dependencies=[Depends(require_admin)],
)


@router.post(
    "/enrich",
    response_model=CorpEnrichResponse,
    status_code=202,
    summary="회사 업종 채움 트리거",
)
async def enrich_corps(
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings_dep),
    service: CorpIndustryService = Depends(get_corp_industry_service),
) -> CorpEnrichResponse:
    """누락된 회사 업종 작업을 등록하고 백그라운드에서 실행한다."""
    if not settings.opendart_api_keys:
        raise BadRequest(
            "OpenDART 인증키가 없습니다. "
            "OPENDART_API_KEY(와 필요하면 OPENDART_API_KEY_2)를 설정한 뒤 다시 시작해 주세요."
        )
    job_id = await service.start()
    background_tasks.add_task(service.run_job, job_id)
    return CorpEnrichResponse(job_id=job_id)


@router.get(
    "/status",
    response_model=CorpJobStatusResponse,
    summary="회사 업종 작업 현황 및 로그 조회",
)
async def read_corp_status(
    job_id: str | None = Query(default=None, description="회사 업종 작업 식별자"),
    service: CorpIndustryService = Depends(get_corp_industry_service),
) -> CorpJobStatusResponse:
    """지정 잡 또는 최신 회사 업종 잡의 상태와 최근 로그를 반환한다."""
    job, logs = await service.get_status(job_id)
    return CorpJobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        mode=job.mode,
        params=job.params,
        error_message=job.error_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
        stop_requested=job.job_id in service._stop_requested,
        logs=[JobLogItem.model_validate(log) for log in logs],
    )


@router.post(
    "/jobs/{job_id}/soft-stop",
    status_code=202,
    summary="회사 업종 작업 중단 요청",
)
async def soft_stop_corp_job(
    job_id: str,
    service: CorpIndustryService = Depends(get_corp_industry_service),
) -> dict[str, str]:
    """새 회사를 시작하지 않도록 작업 중단을 요청한다."""
    await service.request_soft_stop(job_id)
    return {"job_id": job_id, "detail": "중단을 요청했습니다."}


@router.post(
    "/jobs/{job_id}/force-finish",
    status_code=202,
    summary="회사 업종 작업 강제 종료",
)
async def force_finish_corp_job(
    job_id: str,
    service: CorpIndustryService = Depends(get_corp_industry_service),
) -> dict[str, str]:
    """멈춘 회사 업종 작업을 부분 종료한다."""
    await service.force_finish(job_id)
    return {"job_id": job_id, "detail": "작업을 강제 종료했습니다."}


@router.get(
    "/summary",
    response_model=CorpSummaryResponse,
    summary="회사 업종 채움 현황 집계",
)
async def read_corp_summary(
    service: CorpIndustryService = Depends(get_corp_industry_service),
) -> CorpSummaryResponse:
    """공시 회사 수와 업종 채움 완료·잔여 수를 반환한다."""
    summary = await service.summarize()
    return CorpSummaryResponse(
        disclosure_corps=summary.disclosure_corps,
        ok_count=summary.ok_count,
        remaining_count=summary.remaining_count,
    )
