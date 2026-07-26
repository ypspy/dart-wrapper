"""DART 원문 HTML을 문서 순서 블록으로 변환한다.

heading/paragraph/table 세 종류의 블록을 원문 등장 순서대로 만든다. 표 내용은
paragraph에 섞이지 않으며, 이 블록 목록에서 text와 tables를 유도한다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from app.errors import ParseError
from app.schemas.viewer import (
    ContentBlock,
    HeadingBlock,
    ParagraphBlock,
    TableBlock,
    TableData,
)

# 본문과 무관한 태그는 통째로 제거한다.
_NOISE_TAGS = ("script", "style", "noscript", "iframe", "link", "meta")
_SPACES = re.compile(r"[\s\u00a0\u3000]+")
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# 자손에 이 태그가 있으면 자체 블록으로 분해해야 하므로 컨테이너를 재귀한다.
_STRUCTURAL = ["table", "h1", "h2", "h3", "h4", "h5", "h6", "p"]


def extract_blocks(html: str) -> list[ContentBlock]:
    """noise를 제거하고 heading/paragraph/table 블록을 문서 순서로 반환한다.

    :param html: 디코딩이 끝난 원문 HTML 문자열
    :return: 문서 등장 순서의 블록 목록
    :raises ParseError: HTML 파싱에 실패한 경우
    """
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:  # pragma: no cover - lxml 내부 오류 방어
        raise ParseError(f"본문 HTML을 파싱하지 못했습니다: {exc}") from exc

    for tag in soup(list(_NOISE_TAGS)):
        tag.decompose()
    for comment in soup.find_all(string=lambda node: isinstance(node, Comment)):
        comment.extract()

    root = soup.body or soup
    blocks: list[ContentBlock] = []
    _walk(root, blocks)
    return blocks


def blocks_to_text(blocks: Iterable[ContentBlock]) -> str:
    """heading·paragraph만 이어 붙인다. 표 텍스트는 제외한다."""
    lines: list[str] = []
    for block in blocks:
        if block.type in ("heading", "paragraph"):
            text = block.text.strip()
            if text:
                lines.append(text)
    return "\n".join(lines)


def blocks_to_tables(blocks: Iterable[ContentBlock]) -> list[TableData]:
    """table 블록만 TableData 목록으로 변환한다."""
    return [
        TableData(headers=list(block.headers), rows=[list(row) for row in block.rows])
        for block in blocks
        if block.type == "table"
    ]


def _walk(node: Tag, blocks: list[ContentBlock]) -> None:
    """노드의 자식을 문서 순서로 훑어 블록을 채운다."""
    for child in node.children:
        if isinstance(child, NavigableString):
            text = _norm(str(child))
            if text:
                _append_paragraph(blocks, text)
            continue
        if not isinstance(child, Tag):
            continue

        name = child.name.lower()
        if name in _HEADINGS:
            text = _norm(child.get_text(" "))
            if text:
                blocks.append(HeadingBlock(level=min(int(name[1]), 3), text=text))
            continue
        if name == "table":
            table = _parse_table(child)
            if table is not None:
                blocks.append(table)
            continue
        if name == "p":
            text = _norm(child.get_text(" "))
            if text:
                _append_paragraph(blocks, text)
            continue

        # 일반 컨테이너: 구조적 자손이 있으면 재귀, 없으면 한 문단으로 평탄화한다.
        if child.find(_STRUCTURAL) is not None:
            _walk(child, blocks)
        else:
            text = _norm(child.get_text(" "))
            if text:
                _append_paragraph(blocks, text)


def _append_paragraph(blocks: list[ContentBlock], text: str) -> None:
    """직전 블록도 문단이면 이어 붙여 잘게 쪼개지는 것을 막는다."""
    if blocks and blocks[-1].type == "paragraph":
        merged = f"{blocks[-1].text} {text}".strip()
        blocks[-1] = ParagraphBlock(text=merged)
    else:
        blocks.append(ParagraphBlock(text=text))


def _parse_table(table: Tag) -> TableBlock | None:
    """표를 headers/rows로 변환한다. 내용이 없으면 None을 반환한다."""
    parsed_rows: list[list[str]] = []
    for row in table.find_all("tr"):
        cells = [_norm(cell.get_text(" ")) for cell in row.find_all(["th", "td"])]
        if cells:
            parsed_rows.append(cells)

    if not parsed_rows:
        return None

    first_row = table.find("tr")
    has_header = bool(first_row and first_row.find("th"))
    headers = parsed_rows[0] if has_header else []
    rows = parsed_rows[1:] if has_header else parsed_rows
    return TableBlock(headers=headers, rows=rows)


def _norm(value: str) -> str:
    """공백·개행·전각 공백을 한 칸으로 정리한다."""
    return _SPACES.sub(" ", value).strip()
