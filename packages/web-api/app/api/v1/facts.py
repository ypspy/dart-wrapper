"""Public 감사 추출 결과 조회 라우터."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_fact_query_service, get_fact_repository
from app.models.audit_report_fact import AuditReportFact
from app.repositories.fact_repository import FactRepository
from app.schemas.facts import AuditReportFactItem, FactListResponse
from app.services.fact_query_service import FactQueryService

router = APIRouter(prefix="/api/v1/disclosures", tags=["Facts"])
list_router = APIRouter(prefix="/api/v1", tags=["Facts"])


@router.get(
    "/{rcp_no}/audit-facts",
    response_model=list[AuditReportFactItem],
    summary="공시별 감사 추출 결과 조회",
)
async def list_audit_facts(
    rcp_no: str,
    facts: FactRepository = Depends(get_fact_repository),
) -> list[AuditReportFact]:
    """접수번호의 추출 행을 반환한다. 없으면 빈 목록이다(404가 아니다)."""
    return await facts.list_by_rcept_no(rcp_no)


@list_router.get("/facts", response_model=FactListResponse, summary="감사 추출 결과 목록")
async def list_facts(
    corp_code: str | None = None,
    corp_name: str | None = None,
    report_nm: str | None = None,
    report_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    service: FactQueryService = Depends(get_fact_query_service),
) -> FactListResponse:
    """회사·보고서·기간으로 추출 문서 목록을 조회한다(keyset cursor)."""
    return await service.list_page(
        corp_code=corp_code,
        corp_name=corp_name,
        report_nm=report_nm,
        report_type=report_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        cursor=cursor,
    )
