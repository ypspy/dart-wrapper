"""슬라이스 완전성 조회 서비스.

수집(쓰기)과 조회(읽기)는 변경 이유가 달라 서비스를 분리한다.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.errors import CatalogNotFound
from app.repositories.slice_repository import SliceRepository
from app.schemas.catalog import (
    DisclosureAttemptItem,
    HeatmapCell,
    HeatmapMonthLabel,
    HeatmapResponse,
    HeatmapRow,
    SliceDetailResponse,
    SliceListResponse,
    SliceSummary,
    YearSummaryItem,
    YearSummaryResponse,
)

WEEK_COUNT = 53
DAY_COUNT = 7
# 수집 이력이 없을 때 연도 요약 바가 보여줄 시작 연도
FALLBACK_START_YEAR = 1999
MONTH_LABELS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


class SliceQueryService:
    """Admin 화면이 쓰는 슬라이스 목록·상세를 만든다."""

    def __init__(
        self,
        slices: SliceRepository,
        report_types: tuple[str, ...] = (),
    ) -> None:
        self._slices = slices
        self._report_types = report_types

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

    async def year_summary(
        self,
        *,
        report_type: str | None = None,
        today: date | None = None,
    ) -> YearSummaryResponse:
        """연도별 완전성 요약과 기본 선택 연도를 만든다."""
        end = today or date.today()
        rows = await self._slices.list_slices_between(
            f"{FALLBACK_START_YEAR}0101",
            end.strftime("%Y%m%d"),
        )
        if report_type:
            key = report_type.strip().upper()
            rows = [row for row in rows if row.report_type.strip().upper() == key]

        statuses_by_year: dict[int, list[str]] = {}
        for row in rows:
            statuses_by_year.setdefault(int(row.slice_date[:4]), []).append(row.status)

        first_year = min(statuses_by_year) if statuses_by_year else FALLBACK_START_YEAR
        items = [
            YearSummaryItem(year=year, level=self._year_level(statuses_by_year.get(year, [])))
            for year in range(first_year, end.year + 1)
        ]

        selected_year = end.year
        for item in reversed(items):
            if item.level == "incomplete":
                selected_year = item.year
                break
        return YearSummaryResponse(items=items, selected_year=selected_year)

    @staticmethod
    def _year_level(statuses: list[str]) -> str:
        """한 해의 슬라이스 상태들을 연 단위 완전성으로 접는다."""
        if not statuses:
            return "missing"
        if any(status != "complete" for status in statuses):
            return "incomplete"
        return "complete"

    async def heatmap(self, today: date | None = None) -> HeatmapResponse:
        """오늘 기준 최근 53주 완전성 격자를 만든다."""
        end = today or date.today()
        anchor = end - timedelta(weeks=WEEK_COUNT - 1)
        days_since_sunday = (anchor.weekday() + 1) % DAY_COUNT
        start = anchor - timedelta(days=days_since_sunday)

        rows = await self._slices.list_slices_between(
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
        )
        by_key = {(row.report_type.strip().upper(), row.slice_date): row for row in rows}
        discovered = sorted(
            {row.report_type.strip().upper() for row in rows} - set(self._report_types)
        )
        report_types = [*self._report_types, *discovered]

        heatmap_rows = [
            HeatmapRow(
                report_type=report_type,
                weeks=[
                    [
                        self._cell(
                            report_type,
                            start + timedelta(days=week * DAY_COUNT + weekday),
                            end,
                            by_key,
                        )
                        for weekday in range(DAY_COUNT)
                    ]
                    for week in range(WEEK_COUNT)
                ],
            )
            for report_type in report_types
        ]
        return HeatmapResponse(
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            month_labels=self._month_labels(start),
            rows=heatmap_rows,
        )

    @staticmethod
    def _cell(
        report_type: str,
        cell_date: date,
        today: date,
        by_key: dict[tuple[str, str], object],
    ) -> HeatmapCell:
        """한 날짜의 표시 단계와 링크 데이터를 만든다."""
        key = cell_date.strftime("%Y%m%d")
        row = by_key.get((report_type, key))
        if cell_date > today:
            return HeatmapCell(slice_date=key, level="future")
        if row is None:
            return HeatmapCell(slice_date=key, level="missing")
        return HeatmapCell(
            slice_date=key,
            level="complete" if row.status == "complete" else "incomplete",
            slice_id=row.slice_id,
            status=row.status,
            succeeded=row.succeeded,
            listed_count=row.listed_count,
        )

    @staticmethod
    def _month_labels(start: date) -> list[HeatmapMonthLabel]:
        """월이 처음 바뀌는 주에 영문 월 레이블을 둔다."""
        labels: list[HeatmapMonthLabel] = []
        previous_month: int | None = None
        for week_index in range(WEEK_COUNT):
            week_start = start + timedelta(weeks=week_index)
            month = week_start.month
            if month != previous_month:
                labels.append(
                    HeatmapMonthLabel(
                        week_index=week_index,
                        label=MONTH_LABELS[month - 1],
                    )
                )
                previous_month = month
        return labels
