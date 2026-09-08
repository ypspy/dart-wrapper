"""회사 마스터 영속화."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corp import Corp


class CorpRepository:
    """corps upsert와 ok 집합."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, corp: Corp) -> None:
        """corp_code 기준으로 병합 저장한다."""
        await self._session.merge(corp)

    async def list_ok_codes(self) -> set[str]:
        """fetch_status=ok인 고유번호."""
        statement = select(Corp.corp_code).where(Corp.fetch_status == "ok")
        result = await self._session.execute(statement)
        return {row[0] for row in result.all()}

    async def count_ok(self) -> int:
        """ok 행 수."""
        statement = select(func.count()).select_from(Corp).where(Corp.fetch_status == "ok")
        result = await self._session.execute(statement)
        return int(result.scalar_one())
