"""엔트리 카탈로그 영속화. DB 종류에 의존하지 않는 방식으로 구현한다."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entry import Entry
from app.schemas.entry import EntryRecord


class EntryRepository:
    """flat leaf 엔트리 저장·조회 담당."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_many(self, records: Sequence[EntryRecord]) -> int:
        """entry_id 기준으로 병합 저장한다. 재실행 시 중복이 생기지 않는다.

        SQLite/PostgreSQL 모두에서 같은 코드로 동작하도록 세션 merge를 사용한다.
        """
        for record in records:
            await self._session.merge(Entry(**record.model_dump()))
        return len(records)

    async def list_by_rcept_no(self, rcept_no: str) -> list[Entry]:
        """해당 접수번호의 모든 엔트리를 entry_id 순으로 반환한다."""
        statement = select(Entry).where(Entry.rcept_no == rcept_no).order_by(Entry.entry_id)
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def list_toc_by_rcept_no(self, rcept_no: str) -> list[Entry]:
        """목차용 leaf 목록을 ordinal 순으로 반환한다."""
        statement = (
            select(Entry)
            .where(Entry.rcept_no == rcept_no)
            .order_by(
                case((Entry.ordinal.is_(None), 1), else_=0),
                Entry.ordinal,
                Entry.entry_id,
            )
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def get_by_entry_id(self, entry_id: str) -> Entry | None:
        """entry_id로 단일 엔트리를 조회한다. 없으면 None."""
        return await self._session.get(Entry, entry_id)

    def _extraction_filters(
        self, start: str, end: str, report_types: Sequence[str]
    ) -> tuple[ColumnElement[bool], ColumnElement[bool], ColumnElement[bool]]:
        """기간·유형 조건을 반환한다. 저장된 rcept_dt는 YYYY.MM.DD이다."""
        start_key = start.replace(".", "")
        end_key = end.replace(".", "")
        rcept_key = func.replace(Entry.rcept_dt, ".", "")
        return (
            Entry.report_type.in_(list(report_types)),
            rcept_key >= start_key,
            rcept_key <= end_key,
        )

    async def list_rcept_nos_for_extraction(
        self,
        start: str,
        end: str,
        report_types: Sequence[str],
    ) -> list[str]:
        """추출 대상 기간·유형에 해당하는 접수번호를 중복 없이 반환한다.

        한 접수 안의 leaf는 `list_by_rcept_no`로 따로 읽어 메모리에
        기간 전체를 올리지 않는다.
        """
        filters = self._extraction_filters(start, end, report_types)
        statement = (
            select(Entry.rcept_no).where(*filters).distinct().order_by(Entry.rcept_no)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def list_extraction_document_rows(
        self,
        start: str,
        end: str,
        report_types: Sequence[str],
    ) -> list[tuple[str, str | None, str | None, str, str | None]]:
        """기간·유형의 문서 후보를 한 번의 조회로 반환한다.

        접수마다 leaf 전체를 다시 읽지 않는다. selector는 호출측에서 적용한다.
        """
        filters = self._extraction_filters(start, end, report_types)
        statement = (
            select(
                Entry.rcept_no,
                Entry.dcm_no,
                Entry.report_type,
                Entry.source,
                Entry.document_name,
            )
            .where(*filters, Entry.dcm_no.is_not(None), Entry.dcm_no != "")
            .distinct()
            .order_by(Entry.rcept_no, Entry.dcm_no)
        )
        result = await self._session.execute(statement)
        return [(row[0], row[1], row[2], row[3], row[4]) for row in result.all()]

    async def list_for_extraction(
        self,
        start: str,
        end: str,
        report_types: Sequence[str],
    ) -> list[Entry]:
        """추출 대상 기간·유형의 엔트리를 반환한다.

        저장된 `rcept_dt`는 `YYYY.MM.DD`이고, 인자는 `YYYYMMDD`이다.
        점만 제거해 비교하므로 두 형식을 모두 받을 수 있다.
        """
        filters = self._extraction_filters(start, end, report_types)
        statement = (
            select(Entry)
            .where(*filters)
            .order_by(Entry.rcept_no, Entry.dcm_no, Entry.entry_id)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())
