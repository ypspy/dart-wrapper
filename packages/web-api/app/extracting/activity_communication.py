"""외부감사 실시내용 4절 커뮤니케이션 추출."""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from app.extracting.table_matrix import expand_table_matrix
from app.extracting.text import compact

_HEADING_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6")


def extract_communications(html: str) -> tuple[dict[str, object], str]:
    """4절 표를 읽어 회차 목록과 감사위원회 여부를 반환한다.

    제목을 찾으면 다음 형제 중 첫 표를 쓴다. 없으면 not_found와 빈 페이로드다.
    """
    soup = BeautifulSoup(html, "lxml")
    title = _find_section_four_title(soup)
    if title is None:
        return {"has_audit_committee": False, "items": []}, "not_found"

    table = title.find_next_sibling("table")
    if table is None:
        return {"has_audit_committee": False, "items": []}, "not_found"

    return _parse_table(table), "ok"


def _find_section_four_title(soup: BeautifulSoup) -> Tag | None:
    """4절 제목 노드를 찾는다. 3절 지배기구 커뮤니케이션은 제외한다."""
    for node in soup.find_all(_HEADING_TAGS):
        token = compact(node.get_text())
        if "지배기구와의커뮤니케이션" in token:
            continue
        if "와의커뮤니케이션" not in token:
            continue
        if token.startswith("4.") or "감사(감사위원회)" in token:
            return node
    return None


def _parse_table(table: Tag) -> dict[str, object]:
    """헤더를 키로 회차 행을 묶고, 표 본문에 감사위원회가 있는지 본다."""
    matrix = expand_table_matrix(table)
    if not matrix:
        return {
            "has_audit_committee": "감사위원회" in compact(table.get_text()),
            "items": [],
        }

    headers: list[str] = []
    for index, cell in enumerate(matrix[0]):
        key = cell.strip()
        headers.append(key if key else f"col_{index}")

    items: list[dict[str, str]] = []
    for row in matrix[1:]:
        if not any(cell.strip() for cell in row):
            continue
        item: dict[str, str] = {}
        for index, key in enumerate(headers):
            item[key] = row[index].strip() if index < len(row) else ""
        items.append(item)

    return {
        "has_audit_committee": "감사위원회" in compact(table.get_text()),
        "items": items,
    }
