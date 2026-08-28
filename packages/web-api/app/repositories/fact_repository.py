"""감사보고서 추출 결과(facts) 영속화."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_report_fact import AuditReportFact


class FactRepository:
    """audit_report_facts 저장·조회 담당."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, fact: AuditReportFact) -> None:
        """rcept_no·dcm_no 기준으로 병합 저장한다."""
        await self._session.merge(fact)
        await self._session.flush()

    async def get(self, rcept_no: str, dcm_no: str) -> AuditReportFact | None:
        """복합 키로 한 행을 조회한다. 없으면 None."""
        return await self._session.get(AuditReportFact, (rcept_no, dcm_no))

    async def list_by_rcept_no(self, rcept_no: str) -> list[AuditReportFact]:
        """해당 접수의 문서 행을 dcm_no 순으로 반환한다."""
        statement = (
            select(AuditReportFact)
            .where(AuditReportFact.rcept_no == rcept_no)
            .order_by(AuditReportFact.dcm_no)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def list_ambiguous_dates(self) -> list[AuditReportFact]:
        """감사보고서일이 ambiguous인 행을 반환한다."""
        statement = (
            select(AuditReportFact)
            .where(AuditReportFact.audit_report_date_status == "ambiguous")
            .order_by(AuditReportFact.rcept_no, AuditReportFact.dcm_no)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())
