"""A001 「1. 외부감사에 관한 사항」 당기 칸."""

from __future__ import annotations

import re
from collections.abc import Callable

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.extracting.result import FieldResult
from app.extracting.text import compact

_NOT_FOUND = FieldResult(raw=None, code=None, status="not_found")
_NTH_PERIOD = re.compile(r"제\d+기")


def extract_a001_current_audit(html: str) -> tuple[FieldResult, FieldResult]:
    """표 헤더의 당기/제N기 열에서 당기 의견·감사인 칸을 읽는다.

    적정 boilerplate 기본값은 쓰지 않는다. 빈 칸은 not_found.
    """
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        rows = _row_texts(table)
        column = _current_period_column(rows)
        if column is None:
            continue
        opinion = _labeled_cell(rows, column, _is_opinion_label)
        auditor = _labeled_cell(rows, column, _is_auditor_label)
        return opinion, auditor
    return _NOT_FOUND, _NOT_FOUND


def _row_texts(table: Tag) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if cells:
            rows.append([compact(cell.get_text()) for cell in cells])
    return rows


def _current_period_column(rows: list[list[str]]) -> int | None:
    """당기 열이 있으면 그 인덱스, 없으면 첫 제N기 열."""
    for row in rows:
        danggi: int | None = None
        nth: int | None = None
        for index, text in enumerate(row):
            if "당기" in text:
                if danggi is None:
                    danggi = index
            elif nth is None and _NTH_PERIOD.search(text):
                nth = index
        if danggi is not None:
            return danggi
        if nth is not None:
            return nth
    return None


def _is_opinion_label(text: str) -> bool:
    return "감사의견" in text


def _is_auditor_label(text: str) -> bool:
    return "감사인" in text and "감사의견" not in text


def _labeled_cell(
    rows: list[list[str]],
    column: int,
    is_label: Callable[[str], bool],
) -> FieldResult:
    for row in rows:
        if not row or not is_label(row[0]) or column >= len(row):
            continue
        value = row[column]
        if not value:
            return _NOT_FOUND
        return FieldResult(raw=value, code=None, status="ok")
    return _NOT_FOUND
