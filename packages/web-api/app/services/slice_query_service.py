"""슬라이스 완전성 조회 서비스.

수집(쓰기)과 조회(읽기)는 변경 이유가 달라 서비스를 분리한다.
"""

from __future__ import annotations

from app.errors import CatalogNotFound
from app.repositories.slice_repository import SliceRepository
from app.schemas.catalog import (
    DisclosureAttemptItem,
    SliceDetailResponse,
    SliceListResponse,
    SliceSummary,
)


class SliceQueryService:
    """Admin 화면이 쓰는 슬라이스 목록·상세를 만든다."""

    def __init__(self, slices: SliceRepository) -> None:
        self._slices = slices

    async def list_slices(
        self,
        *,
        report_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
    ) -> SliceListResponse:
        """슬라이스 목록을 최신 날짜순으로 반환한다."""
        rows = await self._slices.list_slices(
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
        return SliceListResponse(items=[SliceSummary.model_validate(row) for row in rows])

    async def get_slice(self, slice_id: str) -> SliceDetailResponse:
        """슬라이스 요약과 공시별 처리 결과를 반환한다.

        :raises CatalogNotFound: 해당 슬라이스가 없는 경우
        """
        row = await self._slices.get_slice(slice_id)
        if row is None:
            raise CatalogNotFound(f"수집 슬라이스를 찾을 수 없습니다: {slice_id}")

        attempts = await self._slices.list_attempts(slice_id)
        return SliceDetailResponse(
            slice=SliceSummary.model_validate(row),
            attempts=[DisclosureAttemptItem.model_validate(item) for item in attempts],
        )
