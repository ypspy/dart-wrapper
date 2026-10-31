"""facts 엔트리와 원문 셀을 검수 화면에 연결한다."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from research.extracting.field_bundles import DART_DOCUMENT_VIEW

ENTRY_FIELDS: dict[str, list[str]] = {
    "auditor": ["cover_entry_id", "opinion_entry_id", "a001_cover_entry_id"],
    "opinion": ["opinion_entry_id", "a001_opinion_entry_id", "cover_entry_id"],
    "gaap": ["opinion_entry_id", "cover_entry_id"],
    "audit_report_date": ["opinion_entry_id", "cover_entry_id"],
    "current_period": ["cover_entry_id", "opinion_entry_id"],
    "hours": ["activity_entry_id"],
    "activities": ["activity_entry_id"],
    "communications": ["activity_entry_id"],
    "accounts": ["bs_entry_id", "is_entry_id", "fs_parent_entry_id"],
    "icfr": ["icfr_entry_id"],
    "going_concern": ["opinion_entry_id", "notes_entry_id"],
    "subsidiary": ["notes_entry_id", "a001_affiliate_entry_id"],
}


@dataclass
class Evidence:
    """한 필드의 근거 섹션."""

    entry_id: str
    section_name: str
    viewer_url: str
    dart_url: str
    ele_id: str = ""


class _Annotator(HTMLParser):
    """td/th에 data-t, data-r, data-c를 붙인다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.table_index = -1
        self.row_index = -1
        self.cell_index = 0
        self.table_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        extra = ""
        if tag == "table":
            self.table_depth += 1
            if self.table_depth == 1:
                self.table_index += 1
                self.row_index = -1
        if tag == "tr" and self.table_depth:
            self.row_index += 1
            self.cell_index = 0
        if tag in {"td", "th"} and self.table_depth and self.row_index >= 0:
            extra = (
                f' data-t="{self.table_index}" data-r="{self.row_index}"'
                f' data-c="{self.cell_index}"'
            )
            self.cell_index += 1
        rendered = "".join(
            f' {name}="{value}"' if value is not None else f" {name}"
            for name, value in attrs
        )
        self.parts.append(f"<{tag}{rendered}{extra}>")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self.table_depth:
            self.table_depth -= 1
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")


def annotate_cells(html: str) -> str:
    """표 칸에 표·행·열 번호를 붙인다."""
    parser = _Annotator()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts)


class _CellReader(HTMLParser):
    """주석이 달린 칸의 텍스트를 읽는다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cells: list[tuple[int, int, int, str]] = []
        self._current: tuple[int, int, int] | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"td", "th"}:
            return
        attr = {name: value or "" for name, value in attrs}
        if "data-t" not in attr:
            return
        self._current = (int(attr["data-t"]), int(attr["data-r"]), int(attr["data-c"]))
        self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._current is not None:
            self.cells.append((*self._current, "".join(self._buffer)))
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._buffer.append(data)


def _compact(value: str) -> str:
    """비교용으로 쉼표와 공백을 뺀다."""
    return (value or "").replace(",", "").replace(" ", "")


def find_cells(html: str, raw: str, label: str | None) -> list[tuple[int, int, int]]:
    """표시값과 같은 칸을 찾는다. 같은 행에 계정명이 있으면 그 행을 우선한다."""
    reader = _CellReader()
    reader.feed(html)
    reader.close()
    grouped: dict[tuple[int, int], list[tuple[int, int, int, str]]] = {}
    for table, row, col, text in reader.cells:
        grouped.setdefault((table, row), []).append((table, row, col, text))
    chosen = grouped
    if label:
        label_key = _compact(label)
        matched = {
            key: cells
            for key, cells in grouped.items()
            if any(
                label_key and label_key in _compact(text) for _t, _r, _c, text in cells
            )
        }
        if matched:
            chosen = matched
    target = _compact(raw)
    found: list[tuple[int, int, int]] = []
    for cells in chosen.values():
        for table, row, col, text in cells:
            if raw and (raw in text or (target and target == _compact(text))):
                found.append((table, row, col))
    return found


def evidence_for(
    conn: sqlite3.Connection, snapshot: dict[str, Any], bundle: str
) -> list[Evidence]:
    """묶음에 해당하는 엔트리의 뷰어 주소를 읽는다."""
    rcept_no = str(snapshot.get("rcept_no") or "")
    dcm_no = str(snapshot.get("dcm_no") or "")
    dart_url = DART_DOCUMENT_VIEW.format(rcept_no=rcept_no, dcm_no=dcm_no)
    found: list[Evidence] = []
    seen: set[str] = set()
    for column in ENTRY_FIELDS.get(bundle, []):
        entry_id = snapshot.get(column)
        if not entry_id or str(entry_id) in seen:
            continue
        seen.add(str(entry_id))
        row = conn.execute(
            """
            SELECT entry_id, section_name, viewer_url, ele_id
            FROM cat.entries
            WHERE entry_id = ?
            """,
            (entry_id,),
        ).fetchone()
        if row is None:
            continue
        found.append(
            Evidence(
                entry_id=row["entry_id"],
                section_name=row["section_name"] or "",
                viewer_url=row["viewer_url"] or "",
                dart_url=dart_url,
                ele_id=row["ele_id"] or "",
            )
        )
    return found
