"""연간 완전성 히트맵 계산 테스트."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.schemas.catalog import YearSummaryResponse
from app.services.slice_query_service import SliceQueryService


class FakeSliceRepository:
    """기간 조회 결과를 고정으로 반환한다."""

    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.range: tuple[str, str] | None = None

    async def list_slices_between(self, start_date: str, end_date: str) -> list[object]:
        self.range = (start_date, end_date)
        return self.rows


def _slice(
    report_type: str,
    slice_date: str,
    status: str,
    *,
    succeeded: int,
    listed_count: int | None,
) -> object:
    return SimpleNamespace(
        slice_id=f"{report_type}-{slice_date}",
        report_type=report_type,
        slice_date=slice_date,
        status=status,
        succeeded=succeeded,
        listed_count=listed_count,
    )


async def test_heatmap_builds_53_weeks_and_orders_report_types() -> None:
    repository = FakeSliceRepository(
        [
            _slice("A001", "20260721", "complete", succeeded=3, listed_count=3),
            _slice("X001", "20260720", "blocked", succeeded=1, listed_count=2),
        ]
    )
    service = SliceQueryService(repository, ("A001", "F001"))

    result = await service.heatmap(today=date(2026, 7, 22))

    assert repository.range == ("20250720", "20260722")
    assert [row.report_type for row in result.rows] == ["A001", "F001", "X001"]
    assert all(len(row.weeks) == 53 for row in result.rows)
    assert all(len(week) == 7 for row in result.rows for week in row.weeks)

    cells = {
        (row.report_type, cell.slice_date): cell
        for row in result.rows
        for week in row.weeks
        for cell in week
    }
    assert cells[("A001", "20260721")].level == "complete"
    assert cells[("X001", "20260720")].level == "incomplete"
    assert cells[("F001", "20260721")].level == "missing"
    assert cells[("A001", "20260723")].level == "future"


async def test_heatmap_month_labels_use_first_week_of_month() -> None:
    service = SliceQueryService(FakeSliceRepository([]), ("A001",))

    result = await service.heatmap(today=date(2026, 7, 25))

    labels = {item.week_index: item.label for item in result.month_labels}
    assert labels[2] == "Aug"
    assert "Aug" in labels.values()
    assert "Jan" in labels.values()
    assert "Jul" in labels.values()


async def test_heatmap_normalizes_database_report_type_into_fixed_row() -> None:
    repository = FakeSliceRepository(
        [_slice("f001", "20260721", "complete", succeeded=2, listed_count=2)]
    )
    service = SliceQueryService(repository, ("F001",))

    result = await service.heatmap(today=date(2026, 7, 22))

    assert [row.report_type for row in result.rows] == ["F001"]
    cell = next(
        cell for week in result.rows[0].weeks for cell in week if cell.slice_date == "20260721"
    )
    assert cell.level == "complete"
    assert cell.slice_id == "f001-20260721"


async def test_year_summary_marks_levels_and_selects_latest_incomplete() -> None:
    rows = [
        _slice("F001", "20240115", "complete", succeeded=1, listed_count=1),
        _slice("F001", "20250110", "blocked", succeeded=0, listed_count=2),
        _slice("F001", "20250301", "complete", succeeded=1, listed_count=1),
        _slice("A001", "20260101", "complete", succeeded=1, listed_count=1),
    ]
    service = SliceQueryService(FakeSliceRepository(rows), ("F001",))

    result = await service.year_summary(report_type="F001", today=date(2026, 7, 26))

    assert isinstance(result, YearSummaryResponse)
    by_year = {item.year: item.level for item in result.items}
    assert by_year[2024] == "complete"
    assert by_year[2025] == "incomplete"
    assert by_year[2026] == "missing"
    assert result.selected_year == 2025
    assert result.items[0].year <= result.items[-1].year


async def test_year_summary_empty_uses_fallback_range() -> None:
    service = SliceQueryService(FakeSliceRepository([]), ("F001",))

    result = await service.year_summary(today=date(2026, 7, 26))

    assert result.items[0].year == 1999
    assert result.items[-1].year == 2026
    assert all(item.level == "missing" for item in result.items)
    assert result.selected_year == 2026
