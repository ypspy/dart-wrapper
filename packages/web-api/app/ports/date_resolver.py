"""감사보고서일 후보 인덱스 선택 포트."""

from __future__ import annotations

from typing import Protocol


class DateResolver(Protocol):
    """ambiguous 날짜 후보 중 인덱스를 고른다. 고를 수 없으면 None."""

    async def pick_index(
        self,
        *,
        candidates: list[dict],
        period_end: str,
        rcept_dt: str,
    ) -> int | None:
        """후보 목록에서 감사보고서일 인덱스를 반환한다."""
        ...
