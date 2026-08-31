"""현장감사·실사 시기와 상주 인원 숫자 파싱."""

from __future__ import annotations

import re

from app.extracting.text import compact

_DAYS = re.compile(r"\(?\s*(\d+)\s*일\s*\)?")
_RANGE = re.compile(
    r"(\d{2,4}\.\d{1,2}\.\d{1,2})\s*[~～]\s*(\d{2,4}\.\d{1,2}\.\d{1,2})"
)
_ONE = re.compile(r"(\d{2,4}\.\d{1,2}\.\d{1,2})")
_COUNT = re.compile(r"(\d+)")


def parse_schedule(raw: str) -> dict[str, object]:
    """원문에서 start_date·end_date·days를 읽는다. ISO로 바꾸지 않는다."""
    text = raw.strip()
    if compact(text) in {"", "-"}:
        return {"raw": raw, "start_date": None, "end_date": None, "days": None}
    days: int | None = None
    days_match = _DAYS.search(text)
    if days_match:
        days = int(days_match.group(1))
    date_part = _DAYS.sub("", text).strip(" ,/")
    start: str | None = None
    end: str | None = None
    ranged = _RANGE.search(date_part)
    if ranged:
        start, end = ranged.group(1), ranged.group(2)
    else:
        one = _ONE.search(date_part)
        if one:
            start = end = one.group(1)
    return {"raw": raw, "start_date": start, "end_date": end, "days": days}


def parse_headcount(raw: str) -> dict[str, object]:
    """상주·비상주 원문과 선택적 정수를 반환한다. '-'는 0이 아니다."""
    text = raw.strip()
    if compact(text) in {"", "-"}:
        return {"raw": raw, "count": None}
    match = _COUNT.search(text)
    return {"raw": raw, "count": int(match.group(1)) if match else None}
