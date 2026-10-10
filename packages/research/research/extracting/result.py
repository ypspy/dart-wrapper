"""추출 필드 공통 결과 타입."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldResult:
    """필드 추출 결과(원문, 정규화 코드, 상태)."""

    raw: str | None
    code: str | None
    status: str
