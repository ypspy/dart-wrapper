"""연간 완전성 히트맵 계산 테스트."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

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
