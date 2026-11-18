"""연결 주석·A001 계열회사 표에서 종속기업 수를 센다.

R1 헤더의 회사명·구분 칸이 rowspan으로 복제된 아랫줄은 연속 헤더로 보고 세지 않는다.
R2 앞 3행에 회사명·구분 헤더가 없는 주석 표는 세지 않는다. R3 칸 전체가 이름 헤더이면 그 칸을 이름 열로 본다.
R4 「외 N개」 묶음 행, R5 빈 회사명, R6 정해진 그룹 구분 밖의 이름만 있는 행, R7 본문의 회사명 라벨은 모호하다.
R8 모호하면 세지 않고 ambiguous로 두며, 뒤 표나 A001로 보강하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from research.extracting.table_matrix import expand_table_matrix
from research.extracting.text import compact

_SKIP_ROWS = ("합계", "소계")
_KIND_HEADERS = ("구분", "관계", "기업구분")
_NAME_HEADERS = ("회사명", "기업명", "종속기업명", "법인명")
_NOTES_MARKER = "주석 "
_UNIT_BANNER_MARKERS = ("단위", "당기", "전기")
_BUNDLE_ROW = re.compile(r"(?:외|등|기타)\d+(?:개|社|곳)")
_GROUP_LABEL = re.compile(
    r"^(?:\[.+\]|<.+>|〈.+〉|\(.+\)|국내|해외|국내법인|해외법인|.+의?종속(?:기업|회사)|.+자회사)$"
)


# 헤더 칸 전체가 이 값이면 이름 열로 본다(제목 문장 속 「…와 그 종속기업」은 칸 전체가 아니라 제외).
_NAME_CELLS = (
    "종속기업",
    "종속회사",
    "연결대상종속기업",
    "연결대상종속회사",
    "연결대상회사",
    "회사",
    "법인",
)


class _Ambiguous(Exception):
    """선택한 표를 확정해 셀 수 없음(추측하지 않음)."""


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


def _table_joined_text(table: Tag) -> str:
    """표 칸을 compact로 이어 붙인다."""
    matrix = expand_table_matrix(table)
    return compact("".join("".join(row) for row in matrix))


def _is_unit_banner_table(table: Tag) -> bool:
    """(단위:천원)·(당기)처럼 본표 앞의 단위 안내 표인지 본다."""
    joined = _table_joined_text(table)
    if not joined:
        return False
    if any(hint in joined for hint in _NAME_HEADERS + _KIND_HEADERS):
        return False
    return any(marker in joined for marker in _UNIT_BANNER_MARKERS)


def _heading_from_previous_siblings(element: Tag) -> str:
    """요소 앞 형제에서 표 경계 전의 제목 텍스트를 읽는다.

    단위 안내 표는 제목을 가리지 않는다.
    """
    heading_tags = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "span", "div"}
    for sibling in element.previous_siblings:
        if not isinstance(sibling, Tag):
            continue
        if sibling.name == "table":
            if _is_unit_banner_table(sibling):
                continue
            break
        if sibling.name in heading_tags:
            heading = compact(sibling.get_text(" ", strip=True))
            if heading:
                return heading
    return ""


def _heading_before(table: Tag) -> str:
    """caption·형제·첫 행·부모 형제에서 표 제목을 읽는다."""
    caption = table.find("caption", recursive=False)
    if caption is not None:
        heading = compact(caption.get_text(" ", strip=True))
        if heading:
            return heading

    heading = _heading_from_previous_siblings(table)
    if heading:
        return heading

    first_row = table.find("tr")
    if first_row is not None:
        heading = compact(first_row.get_text(" ", strip=True))
        if _is_notes_heading(heading):
            return heading

    parent = table.parent
    if isinstance(parent, Tag):
        return _heading_from_previous_siblings(parent)
    return ""


def _is_notes_heading(heading: str) -> bool:
    """종속기업 또는 연결대상을 명시한 제목인지 판별한다."""
    return "종속기업" in heading or "연결대상" in heading


def _header_row_index(matrix: list[list[str]]) -> int | None:
    """앞쪽 행 중 회사명이나 구분 열이 있는 헤더 위치를 찾는다. 없으면 None."""
    hints = _NAME_HEADERS + _KIND_HEADERS
    for index, row in enumerate(matrix[:3]):
        joined = compact("".join(row))
        if any(hint in joined for hint in hints):
            return index
        cells = [compact(cell) for cell in row if cell != "#"]
        merged_title = len(cells) > 1 and len(set(cells)) == 1
        if not merged_title and any(cell in _NAME_CELLS for cell in cells):
            return index
    return None


def _hint_columns(header: list[str]) -> list[int]:
    """헤더 행에서 이름·구분 힌트가 있는 칸 위치."""
    hints = _NAME_HEADERS + _KIND_HEADERS
    return [
        i
        for i, c in enumerate(header)
        if c != "#" and (any(h in compact(c) for h in hints) or compact(c) in _NAME_CELLS)
    ]


def _is_name_cell(cell: str) -> bool:
    """칸이 회사명 힌트이거나 칸 전체가 이름 헤더인지 본다."""
    token = compact(cell)
    return any(h in token for h in _NAME_HEADERS) or token in _NAME_CELLS


def _name_column(header: list[str]) -> int | None:
    """헤더에서 이름 열의 첫 위치를 반환한다. 없으면 None."""
    for i, c in enumerate(header):
        if c != "#" and _is_name_cell(c):
            return i
    return None


def _is_header_continuation(row: list[str], header: list[str], cols: list[int]) -> bool:
    """헤더 힌트 칸이 rowspan으로 복제된 행(다단 헤더의 아랫줄)."""
    return any(i < len(row) and compact(row[i]) == compact(header[i]) for i in cols)


def _kind_column(header: list[str], body: list[list[str]]) -> int | None:
    """본문 값이 분류형인 구분·관계·기업구분 열의 위치를 반환한다."""
    for index, cell in enumerate(header):
        token = compact(cell)
        if any(name in token for name in _KIND_HEADERS) and any(
            not _is_skip_row(row) and index < len(row) and _is_taxonomic_kind(row[index])
            for row in body
        ):
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


def _is_taxonomic_kind(cell: str) -> bool:
    """종속·관계·공동 분류값인지 판별한다."""
    token = compact(cell)
    return any(marker in token for marker in ("종속", "관계", "공동"))


def _count_table(table: Tag, *, require_kind: bool) -> int | None:
    """표를 한 번 펼쳐 종속기업 행 수를 센다."""
    matrix = expand_table_matrix(table)
    if not matrix:
        return None

    header_index = _header_row_index(matrix)
    if header_index is None:
        if require_kind:
            header_index = 0
        else:
            return None
    header = matrix[header_index]
    hint_cols = _hint_columns(header)
    body = matrix[header_index + 1 :]
    while body and _is_header_continuation(body[0], header, hint_cols):
        body = body[1:]
    name_index = _name_column(header)
    kind_index = _kind_column(header, body)
    if require_kind and kind_index is None:
        return None

    body_rows = 0
    count = 0
    for row in body:
        if _is_skip_row(row):
            continue
        if any(c != "#" and any(h in compact(c) for h in _NAME_HEADERS) for c in row):
            raise _Ambiguous("name_label_in_body")
        if name_index is not None:
            name = compact(row[name_index]) if name_index < len(row) else ""
            if _BUNDLE_ROW.search(name):
                raise _Ambiguous("bundle_row")
            others = [compact(c) for i, c in enumerate(row) if i != name_index and c != "#"]
            if not name:
                raise _Ambiguous("empty_name")
            if len(row) > 1 and all(not o or o == name for o in others):
                if _GROUP_LABEL.match(name):
                    continue
                raise _Ambiguous("label_like_row")
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
        if _is_unit_banner_table(table):
            continue
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
        try:
            count = _count_from_html(
                notes_html,
                require_kind=False,
                notes_mode=True,
            )
        except _Ambiguous:
            return SubsidiaryResult(None, "ambiguous", "notes")
        if count is not None:
            return SubsidiaryResult(count, "ok", "notes")

    if a001_html:
        try:
            count = _count_from_html(
                a001_html,
                require_kind=True,
                notes_mode=False,
            )
        except _Ambiguous:
            return SubsidiaryResult(None, "ambiguous", "a001")
        if count is not None:
            return SubsidiaryResult(count, "ok", "a001")

    return SubsidiaryResult(None, "not_found", None)
