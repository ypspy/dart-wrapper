"""감사보고서 추출용 텍스트 정규화."""

import re


def compact(value: str | None) -> str:
    """공백을 제거한 문자열을 반환한다. None이면 빈 문자열."""
    return re.sub(r"\s+", "", value or "")
