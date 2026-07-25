"""report_type별 디폴트(primary) 섹션 이름 allowlist."""

from __future__ import annotations

PRIMARY_SECTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "F001": (
        "재무상태표",
        "손익계산서",
        "포괄손익계산서",
        "자본변동표",
        "현금흐름표",
        "주석",
    ),
}


def is_primary_section(
    report_type: str | None,
    section_name: str | None,
    document_name: str | None = None,
) -> bool:
    """섹션명(없으면 문서명)이 allowlist 패턴을 포함하면 True."""
    if not report_type:
        return False
    patterns = PRIMARY_SECTION_PATTERNS.get(report_type)
    if not patterns:
        return False
    target = (section_name or document_name or "").strip()
    if not target:
        return False
    return any(pattern in target for pattern in patterns)
