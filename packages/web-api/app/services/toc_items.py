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


@dataclass(frozen=True)
class TocItem:
    kind: Literal["header", "link"]
    label: str
    indent: int
    entry: TocEntryLike | None = None


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
