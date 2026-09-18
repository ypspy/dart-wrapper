"""감사보고서일 후보 추출과 창 안 최댓값 선택."""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

from app.extracting.text import compact

_DATE_PATTERN = re.compile(
    r"(?P<ymd>[0-9]{4}년[0-9]{1,2}월[0-9]{1,2}일)"
    r"|(?P<cjk>[0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)"
    r"|(?P<dot>[0-9]{4}[.][0-9]{1,2}[.][0-9]{1,2})"
    r"|(?P<dash>[0-9]{4}[-][0-9]{1,2}[-][0-9]{1,2})"
    r"|(?P<slash>[0-9]{4}[/][0-9]{1,2}[/][0-9]{1,2})"
)
_YEAR_END_PATTERN = re.compile(r"(\d{4})\.(\d{1,2})")
_SNIPPET_RADIUS = 40


@dataclass(frozen=True)
class DateCandidate:
    """감사보고서일 후보(원문, ISO, 주변 문장, 등장 순번)."""

    date_raw: str
    iso: str
    snippet: str
    index: int


def extract_date_candidates(text: str) -> list[DateCandidate]:
    """NFKC·compact 본문에서 날짜 후보를 모두 찾는다."""
    normalized = unicodedata.normalize("NFKC", text)
    scanned = compact(normalized)
    candidates: list[DateCandidate] = []
    original_from = 0
    for index, match in enumerate(_DATE_PATTERN.finditer(scanned)):
        date_raw = match.group(0)
        iso = _raw_to_iso(date_raw)
        if iso is None:
            continue
        found_at = text.find(date_raw, original_from)
        if found_at < 0:
            found_at = normalized.find(date_raw, original_from)
            snippet_src = normalized if found_at >= 0 else scanned
            snippet_at = found_at if found_at >= 0 else match.start()
            snippet = _slice_around(snippet_src, snippet_at, len(date_raw))
            if found_at >= 0:
                original_from = found_at + 1
        else:
            snippet = _slice_around(text, found_at, len(date_raw))
            original_from = found_at + 1
        candidates.append(
            DateCandidate(
                date_raw=date_raw,
                iso=iso,
                snippet=snippet,
                index=len(candidates),
            )
        )
    return candidates


def pick_audit_report_date(
    candidates: Sequence[DateCandidate],
    *,
    period_end: date | None,
    auth_date: date | None,
) -> tuple[str | None, str, list[DateCandidate]]:
    """창 안 ISO 중 최댓값을 보고일로 고른다.

    후보 0·인증일 없음·창 통과 0 → not_found. ambiguous를 만들지 않는다.
    """
    if not candidates:
        return None, "not_found", []
    if auth_date is None:
        return None, "not_found", []
    in_window = [
        item
        for item in candidates
        if date_in_auth_window(
            date.fromisoformat(item.iso),
            period_end=period_end,
            auth_date=auth_date,
        )
    ]
    if not in_window:
        return None, "not_found", []
    latest = max(item.iso for item in in_window)
    passing = [item for item in in_window if item.iso == latest]
    return latest, "ok", passing


def date_in_auth_window(
    iso: date,
    *,
    period_end: date | None,
    auth_date: date | None,
) -> bool:
    """period_end < iso ≤ auth_date. 한쪽 None이면 그 비교는 생략한다."""
    if period_end is not None and not (period_end < iso):
        return False
    if auth_date is not None and not (iso <= auth_date):
        return False
    return True


def parse_auth_date(rcept_no: str | None) -> date | None:
    """접수번호 앞 8자리 YYYYMMDD를 인증일로 읽는다."""
    if not rcept_no or len(rcept_no) < 8:
        return None
    raw = rcept_no[:8]
    if not raw.isdigit():
        return None
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError:
        return None


def parse_year_end(year_end: str | None) -> date | None:
    """목록 year_end 문자열(예: (2019.12))을 해당 월 말일로 변환한다."""
    if not year_end:
        return None
    match = _YEAR_END_PATTERN.search(year_end)
    if match is None:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    try:
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, last_day)
    except ValueError:
        return None


def parse_rcept_dt(rcept_dt: str | None) -> date | None:
    """접수일 문자열(2019.03.31 또는 2019-03-31)을 date로 변환한다."""
    if not rcept_dt:
        return None
    value = rcept_dt.strip()
    for fmt in ("%Y.%m.%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _raw_to_iso(date_raw: str) -> str | None:
    """매칭 원문을 ISO로 바꾼다. 달력이 아니면 None."""
    if "년" in date_raw:
        year_s, rest = date_raw.split("년", 1)
        month_s, rest = rest.split("월", 1)
        day_s = rest.removesuffix("일")
    elif "年" in date_raw:
        year_s, rest = date_raw.split("年", 1)
        month_s, rest = rest.split("月", 1)
        day_s = rest.removesuffix("日")
    elif "." in date_raw:
        year_s, month_s, day_s = date_raw.split(".")
    elif "-" in date_raw:
        year_s, month_s, day_s = date_raw.split("-")
    elif "/" in date_raw:
        year_s, month_s, day_s = date_raw.split("/")
    else:
        return None
    try:
        parsed = date(int(year_s), int(month_s), int(day_s))
    except ValueError:
        return None
    return parsed.isoformat()


def _slice_around(source: str, start: int, length: int) -> str:
    left = max(0, start - _SNIPPET_RADIUS)
    right = min(len(source), start + length + _SNIPPET_RADIUS)
    return source[left:right]
