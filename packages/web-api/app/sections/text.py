"""섹션 viewer HTML을 저장용 평문으로 바꾼다.

감리결과는 거의 전부 표다. Viewer API의 text 필드는 표를 빼지만, 여기서는
셀 내용을 행 단위로 남겨 본문만 저장해도 지적사항을 읽을 수 있게 한다.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from app.parsing.blocks import extract_blocks

_HORIZONTAL = re.compile(r"[ \t\u00a0\u3000]+")


def normalize_body(text: str) -> str:
    """해시가 흔들리지 않게 본문 공백을 정리한다.

    NFC로 맞추고, 줄 끝 공백을 지우며, 빈 줄은 버린다.
    """
    normalized = unicodedata.normalize(
        "NFC", (text or "").replace("\r\n", "\n").replace("\r", "\n")
    )
    lines: list[str] = []
    for raw in normalized.split("\n"):
        line = _HORIZONTAL.sub(" ", raw).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def body_hash(text: str) -> str:
    """정규화한 본문의 SHA-256 소문자 hex."""
    normalized = normalize_body(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def section_plain_text(html: str) -> str:
    """제목·문단·표 셀을 문서 순서로 이어 붙인 평문을 반환한다."""
    lines: list[str] = []
    for block in extract_blocks(html or ""):
        if block.type in ("heading", "paragraph"):
            text = block.text.strip()
            if text:
                lines.append(text)
            continue
        if block.type != "table":
            continue
        header = _row_line(list(block.headers))
        if header:
            lines.append(header)
        for row in block.rows:
            rendered = _row_line(list(row))
            if rendered:
                lines.append(rendered)
    return normalize_body("\n".join(lines))


def _row_line(cells: list[str]) -> str | None:
    """표의 한 줄을 `셀 | 셀`로 만든다. 빈 행은 버린다."""
    cleaned = [cell.strip() for cell in cells]
    if not any(cleaned):
        return None
    return " | ".join(cleaned)
