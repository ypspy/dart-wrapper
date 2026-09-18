"""감사보고서 추출 결과(facts) 영속화."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
from app.models.entry import Entry


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
        return await self.list_by_rcept_nos([rcept_no])

    async def list_by_rcept_nos(self, rcept_nos: Sequence[str]) -> list[AuditReportFact]:
        """여러 접수의 문서 행을 rcept_no·dcm_no 순으로 반환한다."""
        if not rcept_nos:
            return []
        rows: list[AuditReportFact] = []
        unique = list(dict.fromkeys(rcept_nos))
        chunk_size = 500
        for index in range(0, len(unique), chunk_size):
            chunk = unique[index : index + chunk_size]
            statement = (
                select(AuditReportFact)
                .where(AuditReportFact.rcept_no.in_(chunk))
                .order_by(AuditReportFact.rcept_no, AuditReportFact.dcm_no)
            )
            result = await self._session.execute(statement)
            rows.extend(result.scalars().all())
        return rows

    async def list_page(
        self,
        *,
        corp_code: str | None = None,
        corp_name: str | None = None,
        report_nm: str | None = None,
        report_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int,
        cursor_rcept_dt: str | None = None,
        cursor_rcept_no: str | None = None,
        cursor_dcm_no: str | None = None,
    ) -> list[tuple[AuditReportFact, Disclosure]]:
        """공시와 조인한 추출 행을 keyset으로 돌려준다."""
        statement = select(AuditReportFact, Disclosure).join(
            Disclosure, AuditReportFact.rcept_no == Disclosure.rcept_no
        )
        if corp_code:
            statement = statement.where(Disclosure.corp_code == corp_code)
        if corp_name:
            statement = statement.where(Disclosure.corp_name.contains(corp_name))
        if report_nm:
            statement = statement.where(Disclosure.report_nm.contains(report_nm))
        if report_type:
            statement = statement.where(AuditReportFact.source_report_type == report_type)
        if start_date:
            statement = statement.where(Disclosure.rcept_dt >= start_date)
        if end_date:
            statement = statement.where(Disclosure.rcept_dt <= end_date)
        if (
            cursor_rcept_dt is not None
            and cursor_rcept_no is not None
            and cursor_dcm_no is not None
        ):
            statement = statement.where(
                or_(
                    Disclosure.rcept_dt < cursor_rcept_dt,
                    and_(
                        Disclosure.rcept_dt == cursor_rcept_dt,
                        AuditReportFact.rcept_no < cursor_rcept_no,
                    ),
                    and_(
                        Disclosure.rcept_dt == cursor_rcept_dt,
                        AuditReportFact.rcept_no == cursor_rcept_no,
                        AuditReportFact.dcm_no > cursor_dcm_no,
                    ),
                )
            )
        statement = statement.order_by(
            Disclosure.rcept_dt.desc(),
            AuditReportFact.rcept_no.desc(),
            AuditReportFact.dcm_no.asc(),
        ).limit(limit)
        result = await self._session.execute(statement)
        return [(fact, disc) for fact, disc in result.all()]

    async def list_ambiguous_dates(self) -> list[AuditReportFact]:
        """감사보고서일이 ambiguous인 행을 반환한다."""
        statement = (
            select(AuditReportFact)
            .where(AuditReportFact.audit_report_date_status == "ambiguous")
            .order_by(AuditReportFact.rcept_no, AuditReportFact.dcm_no)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def list_not_found_dates(self) -> list[AuditReportFact]:
        """감사보고서일이 not_found이고 후보가 있는 행."""
        statement = (
            select(AuditReportFact)
            .where(AuditReportFact.audit_report_date_status == "not_found")
            .order_by(AuditReportFact.rcept_no, AuditReportFact.dcm_no)
        )
        result = await self._session.execute(statement)
        return [
            row
            for row in result.scalars().all()
            if row.audit_report_date_candidates
        ]

    async def list_siblings(
        self,
        *,
        corp_code: str,
        year_end: str,
        fs_scope: str,
        rcept_no: str,
    ) -> list[AuditReportFact]:
        """같은 기업·결산월·범위이면서 접수가 다른 추출 행을 반환한다."""
        rcept_stmt = (
            select(Entry.rcept_no)
            .where(Entry.corp_code == corp_code)
            .where(Entry.year_end == year_end)
            .where(Entry.rcept_no != rcept_no)
            .distinct()
        )
        rcept_result = await self._session.execute(rcept_stmt)
        rcept_nos = list(rcept_result.scalars().all())
        if not rcept_nos:
            return []
        statement = (
            select(AuditReportFact)
            .where(AuditReportFact.rcept_no.in_(rcept_nos))
            .where(AuditReportFact.fs_scope == fs_scope)
            .order_by(AuditReportFact.rcept_no, AuditReportFact.dcm_no)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())
