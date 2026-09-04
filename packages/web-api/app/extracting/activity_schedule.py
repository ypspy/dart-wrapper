"""현장감사·실사 시기와 상주 인원 숫자 파싱."""

from __future__ import annotations

import re

from app.extracting.text import compact

_DAYS_PAREN = re.compile(r"\((\d+)\s*일\)")
_DAYS = re.compile(r"(\d+)\s*일")
_RANGE = re.compile(
    r"(\d{2,4}\.\d{1,2}\.\d{1,2})\s*[~～]\s*"
    r"(\d{2,4}\.\d{1,2}\.\d{1,2}|\d{1,2}\.\d{1,2}|\d{1,2})"
)
_ONE = re.compile(r"(\d{2,4}\.\d{1,2}\.\d{1,2})")
_KOREAN = re.compile(r"(\d{2,4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일)")
_COUNT = re.compile(r"(\d+)")


def _complete_end(start: str, end: str) -> str:
    """축약된 끝 날짜에 시작의 연·월을 채워 같은 점 표기로 만든다."""
    start_parts = start.split(".")
    end_parts = end.split(".")
    if len(end_parts) >= 3:
        return end
    if len(end_parts) == 2:
        return f"{start_parts[0]}.{end_parts[0]}.{end_parts[1]}"
    return f"{start_parts[0]}.{start_parts[1]}.{end_parts[0]}"


def parse_schedule(raw: str) -> dict[str, object]:
    """원문에서 start_date·end_date·days를 읽는다. ISO로 바꾸지 않는다.

    `2024.09.25~27`처럼 끝이 일 또는 월.일만 있으면 시작 날짜에서 빈다.
    한글 `년월일`의 달력 일은 일수로 쓰지 않는다.
    """
    text = raw.strip()
    if compact(text) in {"", "-"}:
        return {"raw": raw, "start_date": None, "end_date": None, "days": None}
    days: int | None = None
    work = text
    paren = _DAYS_PAREN.search(work)
    if paren:
        days = int(paren.group(1))
        work = _DAYS_PAREN.sub("", work).strip(" ,/")
    start: str | None = None
    end: str | None = None
    remainder = work
    ranged = _RANGE.search(work)
    korean = None if ranged else _KOREAN.search(work)
    one = None if ranged or korean else _ONE.search(work)
    if ranged:
        start = ranged.group(1)
        end = _complete_end(start, ranged.group(2))
        remainder = (work[: ranged.start()] + work[ranged.end() :]).strip(" ,/")
    elif korean:
        start = end = korean.group(1)
        remainder = (work[: korean.start()] + work[korean.end() :]).strip(" ,/")
    elif one:
        start = end = one.group(1)
        remainder = (work[: one.start()] + work[one.end() :]).strip(" ,/")
    if days is None:
        days_match = _DAYS.search(remainder)
        if days_match:
            days = int(days_match.group(1))
    return {"raw": raw, "start_date": start, "end_date": end, "days": days}


def parse_headcount(raw: str) -> dict[str, object]:
    """상주·비상주 원문과 선택적 정수를 반환한다. '-'는 0이 아니다."""
    text = raw.strip()
    if compact(text) in {"", "-"}:
        return {"raw": raw, "count": None}
    match = _COUNT.search(text)
    return {"raw": raw, "count": int(match.group(1)) if match else None}
