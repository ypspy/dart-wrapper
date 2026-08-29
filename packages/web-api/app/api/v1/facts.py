"""Public 감사 추출 결과 조회 라우터."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_fact_repository
from app.models.audit_report_fact import AuditReportFact
from app.repositories.fact_repository import FactRepository
from app.schemas.facts import AuditReportFactItem

router = APIRouter(prefix="/api/v1/disclosures", tags=["Facts"])


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
