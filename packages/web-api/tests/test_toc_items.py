"""path 접두사 기반 목차 항목 재구성 테스트."""

from __future__ import annotations

from app.schemas.catalog_query import EntrySummary
from app.services.toc_items import build_toc_items


def _e(entry_id: str, path: list[str], section: str) -> EntrySummary:
    return EntrySummary(
        entry_id=entry_id,
        source="body",
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
