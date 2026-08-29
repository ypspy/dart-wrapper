"""D-3-1 의견 본문 감사인 사전 매칭."""

from __future__ import annotations

from collections.abc import Sequence

from app.extracting.result import FieldResult
from app.extracting.text import compact

_NOT_FOUND = FieldResult(raw=None, code=None, status="not_found")


def extract_body_auditor(text: str, names: Sequence[str]) -> FieldResult:
    """compact 본문에서 사전 이름 중 가장 뒤 위치의 이름을 고른다."""
    content = compact(text)
    best_name: str | None = None
    best_pos = -1
    for name in names:
        compacted = compact(name)
        if not compacted:
            continue
        pos = content.rfind(compacted)
        if pos == -1:
            continue
        if pos >= best_pos:
            best_pos = pos
            best_name = compacted
    if best_name is None:
        return _NOT_FOUND
    return FieldResult(raw=best_name, code=None, status="ok")
