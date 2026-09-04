"""연결 주석·A001 계열회사 표에서 종속기업 수를 센다."""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from app.extracting.table_matrix import expand_table_matrix
from app.extracting.text import compact

_SKIP_ROWS = ("합계", "소계")
_KIND_HEADERS = ("구분", "관계", "기업구분")
_NAME_HEADERS = ("회사명", "기업명", "종속기업명", "법인명")
_NOTES_MARKER = "주석 "


@dataclass(frozen=True)
class SubsidiaryResult:
    """종속기업 수 추출 결과."""

    count: int | None
    status: str
    source: str | None


def notes_tail(html: str) -> str:
    """cut_notes와 같은 구분자 뒤의 주석 부분만 반환한다."""
    if _NOTES_MARKER not in html:
        return ""
    return html.split(_NOTES_MARKER, 1)[1]


def _heading_before(table: Tag) -> str:
    """표 바로 앞의 제목 성격 요소에서 텍스트를 읽는다."""
    heading_tags = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "span", "div"}
    for sibling in table.previous_siblings:
        if not isinstance(sibling, Tag):
            continue
        if sibling.name == "table":
            break
        if sibling.name in heading_tags:
            heading = compact(sibling.get_text(" ", strip=True))
            if heading:
                return heading
    return ""


def _is_notes_heading(heading: str) -> bool:
    """종속기업 또는 연결대상을 명시한 제목인지 판별한다."""
    return "종속기업" in heading or "연결대상" in heading


def _header_row_index(matrix: list[list[str]]) -> int:
    """앞쪽 행 중 회사명이나 구분 열이 있는 헤더 위치를 찾는다."""
    hints = _NAME_HEADERS + _KIND_HEADERS
    for index, row in enumerate(matrix[:3]):
        joined = compact("".join(row))
        if any(hint in joined for hint in hints):
            return index
    return 0


def _kind_column(header: list[str]) -> int | None:
    """구분·관계·기업구분 열의 위치를 반환한다."""
    for index, cell in enumerate(header):
        token = compact(cell)
        if any(name in token for name in _KIND_HEADERS):
            return index
    return None


def _meaningful_cells(row: list[str]) -> list[str]:
    """격자 확장용 자리표시자를 제외한 셀을 정규화한다."""
    return [compact(cell) for cell in row if cell != "#"]


def _is_skip_row(row: list[str]) -> bool:
    """공란과 합계·소계 행을 제외한다."""
    cells = _meaningful_cells(row)
    joined = "".join(cells)
    return not joined or any(marker in joined for marker in _SKIP_ROWS)


def _is_subsidiary_kind(cell: str) -> bool:
    """관계·공동이 아닌 종속 구분만 인정한다."""
    token = compact(cell)
    return "종속" in token and "관계" not in token and "공동" not in token


def _count_table(table: Tag, *, require_kind: bool) -> int | None:
    """표를 한 번 펼쳐 종속기업 행 수를 센다."""
    matrix = expand_table_matrix(table)
    if not matrix:
        return None

    header_index = _header_row_index(matrix)
    kind_index = _kind_column(matrix[header_index])
    if require_kind and kind_index is None:
        return None

    body_rows = 0
    count = 0
    for row in matrix[header_index + 1 :]:
        if _is_skip_row(row):
            continue
        body_rows += 1
        if kind_index is not None:
            kind = row[kind_index] if kind_index < len(row) else ""
            if not _is_subsidiary_kind(kind):
                continue
        count += 1

    if require_kind and body_rows > 0 and count == 0:
        return None
    return count


def _count_from_html(html: str, *, require_kind: bool, notes_mode: bool) -> int | None:
    """조건에 맞는 첫 표를 찾아 센다."""
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        if notes_mode and not _is_notes_heading(_heading_before(table)):
            continue
        count = _count_table(table, require_kind=require_kind)
        if count is not None:
            return count
    return None


def extract_subsidiaries(
    *,
    fs_scope: str,
    notes_html: str | None,
    a001_html: str | None,
) -> SubsidiaryResult:
    """연결재무제표의 주석 또는 A001에서 종속기업 수를 추출한다."""
    if fs_scope != "consolidated":
        return SubsidiaryResult(None, "not_applicable", None)

    if notes_html:
        count = _count_from_html(
            notes_html,
            require_kind=False,
            notes_mode=True,
        )
        if count is not None:
            return SubsidiaryResult(count, "ok", "notes")

    if a001_html:
        count = _count_from_html(
            a001_html,
            require_kind=True,
            notes_mode=False,
        )
        if count is not None:
            return SubsidiaryResult(count, "ok", "a001")

    return SubsidiaryResult(None, "not_found", None)
