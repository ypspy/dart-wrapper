"""D-3-3 감사보고서일 후보 추출과 창 선택."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

from app.extracting.text import compact

_DATE_PATTERN = re.compile(r"[0-9]{4}년[0-9]{1,2}월[0-9]{1,2}일")
_YEAR_END_PATTERN = re.compile(r"(\d{4})\.(\d{1,2})")
_SNIPPET_RADIUS = 40
_OPINION_GROUNDS = "의견근거"
_FS_SECTION = "재무제표에대한경"


@dataclass(frozen=True)
class DateCandidate:
    """감사보고서일 후보(원문, ISO, 주변 문장, 등장 순번)."""

    date_raw: str
    iso: str
    snippet: str
    index: int


def extract_date_candidates(text: str) -> list[DateCandidate]:
    """compact 본문에서 D-3-3 전처리 후 날짜 후보를 모두 찾는다."""
    compact_text = compact(text)
    scanned = _preprocess(compact_text)
    candidates: list[DateCandidate] = []
    for index, match in enumerate(_DATE_PATTERN.finditer(scanned)):
        date_raw = match.group(0)
        candidates.append(
            DateCandidate(
                date_raw=date_raw,
                iso=_to_iso(date_raw),
                snippet=_snippet(text, scanned, date_raw, match.start()),
                index=index,
            )
        )
    return candidates


def pick_audit_report_date(
    candidates: Sequence[DateCandidate],
    *,
    period_end: date | None,
    rcept_dt: date | None,
) -> tuple[str | None, str, list[DateCandidate]]:
    """창(period_end < iso <= rcept_dt)을 통과한 후보로 보고일을 고른다.

    통과 1개면 ok, 0개면 not_found, 2개 이상이면 ambiguous(ISO는 None).
    후반 우선은 적용하지 않는다. 한쪽 경계가 None이면 그 비교는 생략한다.
    """
    passing: list[DateCandidate] = []
    for candidate in candidates:
        iso_date = _parse_iso(candidate.iso)
        if iso_date is None:
            continue
        if period_end is not None and not (period_end < iso_date):
            continue
        if rcept_dt is not None and not (iso_date <= rcept_dt):
            continue
        passing.append(candidate)

    unique: dict[str, DateCandidate] = {}
    for candidate in passing:
        unique.setdefault(candidate.iso, candidate)
    passing = list(unique.values())

    if len(passing) == 1:
        return passing[0].iso, "ok", passing
    if not passing:
        return None, "not_found", passing
    return None, "ambiguous", passing


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


def _preprocess(compact_text: str) -> str:
    """의견근거 앞과 마지막 재무제표에대한경 이후를 이어 붙인다.

    마커가 없으면 본문을 두 번 붙이지 않는다. 하나만 있으면 그 구간만 쓴다.
    """
    first_part = (
        compact_text.split(_OPINION_GROUNDS)[0]
        if _OPINION_GROUNDS in compact_text
        else ""
    )
    second_part = (
        compact_text.split(_FS_SECTION)[-1] if _FS_SECTION in compact_text else ""
    )
    if first_part or second_part:
        return first_part + second_part
    return compact_text


def _to_iso(date_raw: str) -> str:
    """YYYY년M월D일을 zero-pad ISO(YYYY-MM-DD)로 바꾼다."""
    year_s, rest = date_raw.split("년", 1)
    month_s, rest = rest.split("월", 1)
    day_s = rest.removesuffix("일")
    return f"{int(year_s):04d}-{int(month_s):02d}-{int(day_s):02d}"


def _parse_iso(iso: str) -> date | None:
    try:
        return date.fromisoformat(iso)
    except ValueError:
        return None


def _snippet(original: str, scanned: str, date_raw: str, match_start: int) -> str:
    """원문에서 매칭 전후 40자를 취하고, 없으면 compact 기준으로 자른다."""
    found_at = original.find(date_raw)
    if found_at >= 0:
        return _slice_around(original, found_at, len(date_raw))
    return _slice_around(scanned, match_start, len(date_raw))


def _slice_around(source: str, start: int, length: int) -> str:
    left = max(0, start - _SNIPPET_RADIUS)
    right = min(len(source), start + length + _SNIPPET_RADIUS)
    return source[left:right]
