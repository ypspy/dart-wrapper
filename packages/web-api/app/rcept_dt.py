"""접수일 YYYYMMDD와 저장 형식 YYYY.MM.DD 변환."""

from __future__ import annotations


def to_dotted_rcept_dt(value: str) -> str:
    """YYYYMMDD를 disclosures.rcept_dt 비교용 YYYY.MM.DD로 바꾼다."""
    digits = value.replace(".", "")
    if len(digits) != 8 or not digits.isdigit():
        return value
    return f"{digits[:4]}.{digits[4:6]}.{digits[6:8]}"
