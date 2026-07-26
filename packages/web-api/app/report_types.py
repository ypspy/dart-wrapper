"""DART 보고서 유형 코드와 한국어 명칭.

DART 상세검색의 `reportType` 값을 그대로 쓴다. 목록에 없는 코드는 코드 자체를
이름으로 사용한다.
"""

from __future__ import annotations

REPORT_TYPE_LABELS: dict[str, str] = {
    "A001": "사업보고서",
    "A002": "반기보고서",
    "A003": "분기보고서",
    "F001": "감사보고서",
    "F002": "연결감사보고서",
    "F004": "회계법인사업보고서",
}


def report_type_label(code: str) -> str:
    """보고서 유형 코드의 한국어 명칭을 반환한다. 모르는 코드는 코드 그대로."""
    return REPORT_TYPE_LABELS.get(code.strip().upper(), code.strip().upper())


def report_type_options(codes: tuple[str, ...]) -> list[dict[str, str]]:
    """화면 토글·선택 목록에 쓸 코드·명칭 쌍을 만든다."""
    return [{"code": code, "label": report_type_label(code)} for code in codes]
