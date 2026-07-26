"""leaf path로 Browse 목차용 헤더·링크 항목을 만든다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, Sequence


class TocEntryLike(Protocol):
    entry_id: str
    path: list[str]
    section_name: str | None
    document_name: str | None
    depth: int | None
    source: str


@dataclass(frozen=True)
class TocItem:
    kind: Literal["header", "link"]
    label: str
    indent: int
    entry: TocEntryLike | None = None


@dataclass(frozen=True)
class TocRow:
    item: TocItem
    open_levels: int
    close_levels: int


@dataclass(frozen=True)
class TocSection:
    title: str
    rows: list[TocRow]
    trailing_close: int


def _ancestors(path: list[str]) -> list[str]:
    if len(path) <= 1:
        return []
    return list(path[:-1])


def _common_prefix_len(a: list[str], b: list[str]) -> int:
    n = 0
    for left, right in zip(a, b):
        if left != right:
            break
        n += 1
    return n


def _link_label(entry: TocEntryLike) -> str:
    return entry.section_name or entry.document_name or entry.entry_id


def _link_indent(entry: TocEntryLike) -> int:
    path = list(entry.path or [])
    if path:
        return max(0, len(path) - 1)
    if entry.depth is not None and entry.depth > 0:
        return max(0, entry.depth - 1)
    return 0


def build_toc_items(entries: Sequence[TocEntryLike]) -> list[TocItem]:
    """ordinal 순 leaf 목록을 헤더+링크 평탄 리스트로 변환한다."""
    items: list[TocItem] = []
    prev_ancestors: list[str] = []

    for entry in entries:
        path = list(entry.path or [])
        ancestors = _ancestors(path)
        k = _common_prefix_len(prev_ancestors, ancestors)
        for index, name in enumerate(ancestors[k:], start=k):
            items.append(TocItem(kind="header", label=name, indent=index))
        items.append(
            TocItem(
                kind="link",
                label=_link_label(entry),
                indent=_link_indent(entry),
                entry=entry,
            )
        )
        prev_ancestors = ancestors

    return items


def to_nested_rows(items: Sequence[TocItem]) -> tuple[list[TocRow], int]:
    """indent 변화로 중첩 <ul> 개폐 수를 계산한다.

    close_levels / open_levels는 해당 행을 출력하기 **전에** 적용한다.
    trailing_close는 마지막에 열린 깊이를 모두 닫는 개수다.
    """
    rows: list[TocRow] = []
    prev_indent = 0
    for item in items:
        indent = item.indent
        close_levels = max(0, prev_indent - indent)
        open_levels = max(0, indent - prev_indent)
        rows.append(
            TocRow(item=item, open_levels=open_levels, close_levels=close_levels)
        )
        prev_indent = indent
    return rows, prev_indent


def build_toc_sections(entries: Sequence[TocEntryLike]) -> list[TocSection]:
    """source별로 본문/첨부 목차 구역을 만든다."""
    groups: list[tuple[str, list[TocEntryLike]]] = [
        ("본문", [e for e in entries if getattr(e, "source", None) == "body"]),
        (
            "첨부",
            [e for e in entries if getattr(e, "source", None) == "attachment"],
        ),
    ]
    sections: list[TocSection] = []
    for title, group in groups:
        if not group:
            continue
        rows, trailing = to_nested_rows(build_toc_items(group))
        sections.append(TocSection(title=title, rows=rows, trailing_close=trailing))
    return sections
