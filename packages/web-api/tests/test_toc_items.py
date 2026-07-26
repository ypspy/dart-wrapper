"""path 접두사 기반 목차 항목 재구성 테스트."""

from __future__ import annotations

from app.schemas.catalog_query import EntrySummary
from app.services.toc_items import (
    TocItem,
    build_toc_items,
    build_toc_sections,
    to_nested_rows,
)


def _e(
    entry_id: str,
    path: list[str],
    section: str,
    *,
    source: str = "body",
) -> EntrySummary:
    return EntrySummary(
        entry_id=entry_id,
        source=source,
        section_name=section,
        path=path,
        depth=len(path),
        ordinal=0,
    )


def test_build_toc_items_inserts_ancestor_headers() -> None:
    entries = [
        _e("1", ["감사보고서", "재무상태표"], "재무상태표"),
        _e("2", ["감사보고서", "(첨부)재무제표", "손익계산서"], "손익계산서"),
        _e("3", ["감사보고서", "(첨부)재무제표", "자본변동표"], "자본변동표"),
    ]
    items = build_toc_items(entries)
    kinds_labels = [(i.kind, i.label, i.indent) for i in items]
    assert kinds_labels == [
        ("header", "감사보고서", 0),
        ("link", "재무상태표", 1),
        ("header", "(첨부)재무제표", 1),
        ("link", "손익계산서", 2),
        ("link", "자본변동표", 2),
    ]


def test_build_toc_items_empty_path() -> None:
    entries = [_e("1", [], "단독")]
    items = build_toc_items(entries)
    assert len(items) == 1
    assert items[0].kind == "link"
    assert items[0].indent == 0


def test_build_toc_items_single_segment_path() -> None:
    entries = [_e("1", ["PDF첨부"], "PDF첨부")]
    items = build_toc_items(entries)
    assert [(i.kind, i.label) for i in items] == [("link", "PDF첨부")]


def test_to_nested_rows_opens_and_closes() -> None:
    items = [
        TocItem(kind="header", label="A", indent=0),
        TocItem(kind="link", label="B", indent=1, entry=_e("1", ["A", "B"], "B")),
        TocItem(kind="header", label="C", indent=1),
        TocItem(kind="link", label="D", indent=2, entry=_e("2", ["A", "C", "D"], "D")),
        TocItem(kind="link", label="E", indent=1, entry=_e("3", ["A", "E"], "E")),
    ]
    rows, trailing = to_nested_rows(items)
    assert [(r.close_levels, r.open_levels, r.item.label) for r in rows] == [
        (0, 0, "A"),
        (0, 1, "B"),
        (0, 0, "C"),
        (0, 1, "D"),
        (1, 0, "E"),
    ]
    assert trailing == 1


def test_to_nested_rows_flat() -> None:
    items = [
        TocItem(kind="link", label="X", indent=0, entry=_e("1", ["X"], "X")),
        TocItem(kind="link", label="Y", indent=0, entry=_e("2", ["Y"], "Y")),
    ]
    rows, trailing = to_nested_rows(items)
    assert all(r.open_levels == 0 and r.close_levels == 0 for r in rows)
    assert trailing == 0


def test_build_toc_sections_splits_body_and_attachment() -> None:
    body = _e("b1", ["감사보고서", "재무상태표"], "재무상태표", source="body")
    att = _e("a1", ["첨부", "첨부문서"], "첨부문서", source="attachment")
    sections = build_toc_sections([body, att])
    assert [s.title for s in sections] == ["본문", "첨부"]
    assert sections[0].rows
    assert sections[1].rows


def test_build_toc_sections_hides_empty_body() -> None:
    att = _e("a1", ["첨부문서"], "첨부문서", source="attachment")
    sections = build_toc_sections([att])
    assert [s.title for s in sections] == ["첨부"]
