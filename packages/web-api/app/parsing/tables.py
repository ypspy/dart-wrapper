"""DART 원문 HTML의 표를 JSON 구조로 변환한다."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.errors import ParseError

_SPACES = re.compile(r"[\s\u00a0\u3000]+")


def _cell_text(cell: Tag) -> str:
    """셀 안의 공백·개행을 한 칸으로 정리한 문자열을 반환한다."""
    return _SPACES.sub(" ", cell.get_text(" ")).strip()


def extract_tables(html: str) -> list[dict[str, list]]:
    """HTML의 모든 표를 headers/rows 구조로 변환한다.

    :param html: 디코딩이 끝난 원문 HTML 문자열
    :return: 표별 {"headers": [...], "rows": [[...]]} 목록
    :raises ParseError: HTML 파싱에 실패한 경우
    """
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:  # pragma: no cover - lxml 내부 오류 방어
        raise ParseError(f"표 HTML을 파싱하지 못했습니다: {exc}") from exc

    for tag in soup(["script", "style"]):
        tag.decompose()

    tables: list[dict[str, list]] = []
    for table in soup.find_all("table"):
        parsed_rows: list[list[str]] = []
        for row in table.find_all("tr"):
            cells = [_cell_text(cell) for cell in row.find_all(["th", "td"])]
            if cells:
                parsed_rows.append(cells)

        if not parsed_rows:
            continue

        first_row = table.find("tr")
        has_header = bool(first_row and first_row.find("th"))
        headers = parsed_rows[0] if has_header else []
        rows = parsed_rows[1:] if has_header else parsed_rows
        tables.append({"headers": headers, "rows": rows})

    return tables
