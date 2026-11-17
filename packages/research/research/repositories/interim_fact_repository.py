"""반기·분기 검토보고서 추출 결과 저장.

운영자 보정 열은 없다. 같은 키는 merge로 덮어 쓴다.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from research.models.interim_review_fact import InterimReviewFact


class InterimFactRepository:
    """interim_review_facts 저장·조회."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, fact: InterimReviewFact) -> None:
        """rcept_no·dcm_no 기준으로 병합 저장한다."""
        await self._session.merge(fact)
        await self._session.flush()

    async def get(self, rcept_no: str, dcm_no: str) -> InterimReviewFact | None:
        """복합 키로 한 행을 조회한다. 없으면 None."""
        return await self._session.get(InterimReviewFact, (rcept_no, dcm_no))
