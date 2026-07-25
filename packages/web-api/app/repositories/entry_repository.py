"""엔트리 카탈로그 영속화. DB 종류에 의존하지 않는 방식으로 구현한다."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import case, select
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
        """목차용 leaf 목록을 본문 우선·문서·섹션 순으로 반환한다."""
        statement = (
            select(Entry)
            .where(Entry.rcept_no == rcept_no)
            .order_by(
                case((Entry.source == "body", 0), else_=1),
                Entry.dcm_no,
                Entry.ele_id,
                Entry.entry_id,
            )
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def get_by_entry_id(self, entry_id: str) -> Entry | None:
        """entry_id로 단일 엔트리를 조회한다. 없으면 None."""
        return await self._session.get(Entry, entry_id)
