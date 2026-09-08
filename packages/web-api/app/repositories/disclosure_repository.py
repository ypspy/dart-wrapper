"""공시(접수) 단위 집계 테이블 영속화."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.disclosure import Disclosure
from app.models.entry import Entry


class DisclosureRepository:
    """disclosures 저장·keyset 목록·backfill."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_many(self, rows: Sequence[Disclosure]) -> int:
        """rcept_no 기준으로 병합 저장한다."""
        for row in rows:
            await self._session.merge(row)
        return len(rows)

    async def get(self, rcept_no: str) -> Disclosure | None:
        """접수번호로 공시 1건을 조회한다."""
        return await self._session.get(Disclosure, rcept_no)

    async def list_distinct_corp_codes(self) -> list[str]:
        """공시에 나온 비어 있지 않은 고유번호를 정렬해 반환한다."""
        statement = (
            select(Disclosure.corp_code)
            .where(Disclosure.corp_code.is_not(None))
            .where(Disclosure.corp_code != "")
            .distinct()
            .order_by(Disclosure.corp_code)
        )
        result = await self._session.execute(statement)
        return [row[0] for row in result.all() if row[0]]

    async def count_distinct_corp_codes(self) -> int:
        """공시에 나온 비어 있지 않은 고유번호 수를 SQL로 집계한다."""
        statement = (
            select(func.count(Disclosure.corp_code.distinct()))
            .where(Disclosure.corp_code.is_not(None))
            .where(Disclosure.corp_code != "")
        )
        result = await self._session.execute(statement)
        return int(result.scalar_one())

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
    ) -> list[Disclosure]:
        """필터와 keyset cursor로 공시 목록을 조회한다."""
        statement = select(Disclosure)
        if corp_code:
            statement = statement.where(Disclosure.corp_code == corp_code)
        if corp_name:
            statement = statement.where(Disclosure.corp_name.contains(corp_name))
        if report_nm:
            statement = statement.where(Disclosure.report_nm.contains(report_nm))
        if report_type:
            statement = statement.where(Disclosure.report_type == report_type)
        if start_date:
            statement = statement.where(Disclosure.rcept_dt >= start_date)
        if end_date:
            statement = statement.where(Disclosure.rcept_dt <= end_date)
        if cursor_rcept_dt is not None and cursor_rcept_no is not None:
            statement = statement.where(
                or_(
                    Disclosure.rcept_dt < cursor_rcept_dt,
                    and_(
                        Disclosure.rcept_dt == cursor_rcept_dt,
                        Disclosure.rcept_no < cursor_rcept_no,
                    ),
                )
            )
        statement = statement.order_by(
            Disclosure.rcept_dt.desc(), Disclosure.rcept_no.desc()
        ).limit(limit)
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def backfill_from_entries(self) -> int:
        """entries를 rcept_no로 집계해 disclosures를 채운다(idempotent)."""
        result = await self._session.execute(select(Entry))
        entries = list(result.scalars().all())
        by_rcp: dict[str, list[Entry]] = {}
        for entry in entries:
            by_rcp.setdefault(entry.rcept_no, []).append(entry)

        rows: list[Disclosure] = []
        for rcept_no, group in by_rcp.items():
            sample = group[0]
            rows.append(
                Disclosure(
                    rcept_no=rcept_no,
                    corp_code=sample.corp_code,
                    corp_name=sample.corp_name,
                    report_nm=sample.report_nm,
                    report_type=sample.report_type,
                    correction_type=sample.correction_type,
                    submitter=sample.submitter,
                    rcept_dt=sample.rcept_dt or "",
                    bsns_year=sample.bsns_year,
                    year_end=sample.year_end,
                    disclosure_url=sample.disclosure_url,
                    entry_count=len(group),
                )
            )
        return await self.upsert_many(rows)
