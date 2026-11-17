"""반기·분기 검토보고서 본문 필드 파서. 규칙만 쓰고 외부 호출은 하지 않는다."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from bs4 import BeautifulSoup

from research.extracting.auditor_body import extract_body_auditor
from research.extracting.gaap import classify_gaap
from research.extracting.text import compact

INTERIM_EXTRACTOR_VERSION = "interim_review.v1"

_HEADING_RE = re.compile(r"(검토\s*결론|검토\s*의견|감사\s*의견)")
_DATE_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_RANGE_RE = re.compile(
    r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*부터\s*"
    r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*까지"
)
_CURRENT_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*현재")
_MONTHS_RE = re.compile(r"(\d+)\s*개월")
_FIRM_RE = re.compile(r"(.+?(?:회계법인|감사반))")
_REP_RE = re.compile(r"대표\s*이사|대표\s*회계사")
_EMPHASIS_LIMIT = 300
_CONCLUSION_LIMIT = 4000


@dataclass(frozen=True)
class InterimReviewParse:
    """검토보고서 한 건에서 읽은 필드."""

    reviewer_raw: str | None
    reviewer_resolved: str | None
    reviewer_status: str
    conclusion_raw: str | None
    conclusion_code: str
    conclusion_status: str
    review_report_date_raw: str | None
    review_report_date: str | None
    review_report_date_status: str
    review_report_date_candidates: list[dict[str, str]]
    review_period_raw: str | None
    review_period_resolved: str | None
    review_period_status: str
    gaap_code: str | None
    gaap_status: str
    emphasis_of_matter: bool
    going_concern: bool
    emphasis_raw: str | None
    emphasis_status: str


def html_to_text(html: str) -> str:
    """HTML을 문단 줄바꿈이 남은 텍스트로 바꾼다."""
    return BeautifulSoup(html or "", "lxml").get_text("\n", strip=True)


def parse_interim_review(
    html: str,
    *,
    auditor_names: Sequence[str] = (),
) -> InterimReviewParse:
    """검토보고서 HTML에서 검토인·결론·날짜·기간·GAAP·강조사항을 읽는다."""
    text = html_to_text(html)
    reviewer_raw, reviewer_resolved, reviewer_status = _reviewer(text, auditor_names)
    conclusion_raw, conclusion_code, conclusion_status = _conclusion(text)
    date_raw, date_iso, date_status, candidates = _signature_date(text)
    period_raw, period_resolved, period_status = _period(text)
    gaap_code, gaap_status = _gaap(text)
    emphasis_of_matter, going_concern, emphasis_raw, emphasis_status = _emphasis(text)
    return InterimReviewParse(
        reviewer_raw=reviewer_raw,
        reviewer_resolved=reviewer_resolved,
        reviewer_status=reviewer_status,
        conclusion_raw=conclusion_raw,
        conclusion_code=conclusion_code,
        conclusion_status=conclusion_status,
        review_report_date_raw=date_raw,
        review_report_date=date_iso,
        review_report_date_status=date_status,
        review_report_date_candidates=candidates,
        review_period_raw=period_raw,
        review_period_resolved=period_resolved,
        review_period_status=period_status,
        gaap_code=gaap_code,
        gaap_status=gaap_status,
        emphasis_of_matter=emphasis_of_matter,
        going_concern=going_concern,
        emphasis_raw=emphasis_raw,
        emphasis_status=emphasis_status,
    )


def _heading_span(text: str) -> tuple[int, int] | None:
    """검토결론·검토의견·감사의견 제목의 원문 구간."""
    match = _HEADING_RE.search(text)
    if match is None:
        return None
    return match.start(), match.end()


def _opening(text: str) -> str:
    """결론 제목 앞, 첫 단락이 있는 앞부분."""
    span = _heading_span(text)
    if span is None:
        return text
    return text[: span[0]]


def _signature_zone(text: str) -> tuple[str, int]:
    """결론 제목 뒤부터를 서명부로 본다. 제목이 없으면 본문 전체."""
    span = _heading_span(text)
    if span is None:
        return text, 0
    return text[span[1] :], span[1]


def _conclusion_body(text: str) -> str:
    """결론 제목과 서명(대표·회계법인) 사이의 문단."""
    zone, _offset = _signature_zone(text)
    stop = re.search(r"대표\s*이사|대표\s*회계사|회계법인|감사반", zone)
    if stop is not None:
        zone = zone[: stop.start()]
    return zone.strip()


def _calendar_iso(year: int, month: int, day: int) -> str | None:
    """달력에 있는 날만 ISO로 바꾼다."""
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _dotted(year: int, month: int, day: int) -> str:
    """기간 표기용 YYYY.MM.DD."""
    return f"{year:04d}.{month:02d}.{day:02d}"


def _reviewer(text: str, names: Sequence[str]) -> tuple[str | None, str | None, str]:
    """대표이사·대표회계사 줄 바로 위의 회계법인·감사반 이름을 고른다."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rep_at: int | None = None
    for index, line in enumerate(lines):
        if _REP_RE.search(line):
            rep_at = index
            break
    search_space = lines[:rep_at] if rep_at is not None else lines
    firm_line: str | None = None
    for line in reversed(search_space):
        token = compact(line)
        if "회계법인" in token or "감사반" in token:
            firm_line = line
            break
    if firm_line is None:
        return None, None, "not_found"

    matched = extract_body_auditor(firm_line, names)
    if matched.status == "ok" and matched.raw:
        return firm_line, matched.raw, "ok"

    found = _FIRM_RE.search(firm_line)
    if found is None:
        return firm_line, None, "not_found"
    raw = found.group(1).strip()
    resolved = compact(raw)
    if not resolved:
        return None, None, "not_found"
    return raw, resolved, "ok"


def _conclusion(text: str) -> tuple[str | None, str, str]:
    """검토결론 문단을 unmodified/qualified/adverse/disclaimer/unknown으로 나눈다."""
    body = _conclusion_body(text)
    if not compact(body):
        return None, "unknown", "not_found"
    raw = body[:_CONCLUSION_LIMIT]
    token = compact(body)
    if "의견거절" in token or "결론표명하지않" in token or "결론을표명하지않" in token:
        return raw, "disclaimer", "ok"
    if "부적정" in token:
        return raw, "adverse", "ok"
    if "한정" in token:
        return raw, "qualified", "ok"
    if ("중요성의관점" in token and ("발견되지않았" in token or "발견되지아니" in token)) or (
        "중요하게왜곡표시되지않았" in token
    ):
        return raw, "unmodified", "ok"
    return raw, "unknown", "not_found"


def _signature_anchor(text: str) -> int:
    """서명부 기준 위치. 대표 줄, 없으면 마지막 회계법인·감사반."""
    reps = list(_REP_RE.finditer(text))
    if reps:
        return reps[-1].start()
    firms = list(re.finditer(r"회계법인|감사반", text))
    if firms:
        return firms[-1].start()
    return len(text)


def _signature_date(
    text: str,
) -> tuple[str | None, str | None, str, list[dict[str, str]]]:
    """서명부(결론 제목 뒤) 날짜 중 서명에 가장 가까운 것을 고르고 나머지는 후보로 둔다."""
    zone, offset = _signature_zone(text)
    found: list[tuple[int, str, str]] = []
    for match in _DATE_RE.finditer(zone):
        iso = _calendar_iso(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if iso is None:
            continue
        found.append((offset + match.start(), match.group(0), iso))
    if not found:
        return None, None, "not_found", []

    anchor = _signature_anchor(text)
    chosen = min(found, key=lambda item: (abs(item[0] - anchor), -item[0]))
    candidates = [{"date_raw": raw, "iso": iso} for pos, raw, iso in found if pos != chosen[0]]
    return chosen[1], chosen[2], "ok", candidates


def _period(text: str) -> tuple[str | None, str | None, str]:
    """첫 단락의 부터~까지, 없으면 현재 기준일과 N개월로 기간을 만든다."""
    opening = _opening(text)
    ranged = _RANGE_RE.search(opening)
    if ranged is not None:
        start = _calendar_iso(int(ranged.group(1)), int(ranged.group(2)), int(ranged.group(3)))
        end = _calendar_iso(int(ranged.group(4)), int(ranged.group(5)), int(ranged.group(6)))
        if start and end:
            start_parts = date.fromisoformat(start)
            end_parts = date.fromisoformat(end)
            resolved = (
                f"{_dotted(start_parts.year, start_parts.month, start_parts.day)}"
                f"~{_dotted(end_parts.year, end_parts.month, end_parts.day)}"
            )
            return ranged.group(0), resolved, "ok"

    current = _CURRENT_RE.search(opening)
    months_match = _MONTHS_RE.search(opening)
    if current is None or months_match is None:
        return None, None, "not_found"
    end_iso = _calendar_iso(int(current.group(1)), int(current.group(2)), int(current.group(3)))
    months = int(months_match.group(1))
    if end_iso is None or months < 1:
        return None, None, "not_found"
    end_on = date.fromisoformat(end_iso)
    start_on = _start_of_month_span(end_on, months)
    resolved = (
        f"{_dotted(start_on.year, start_on.month, start_on.day)}"
        f"~{_dotted(end_on.year, end_on.month, end_on.day)}"
    )
    raw = f"{current.group(0)} {months_match.group(0)}"
    return raw, resolved, "ok"


def _start_of_month_span(end_on: date, months: int) -> date:
    """종료일이 속한 달부터 months개월 구간의 시작일(그 달 1일)."""
    index = end_on.year * 12 + (end_on.month - 1) - (months - 1)
    year, month_index = divmod(index, 12)
    return date(year, month_index + 1, 1)


def _gaap(text: str) -> tuple[str | None, str]:
    """기존 GAAP 규칙을 그대로 쓴다. 본문이 비면 not_found."""
    if not compact(text):
        return None, "not_found"
    result = classify_gaap(text)
    return result.code, result.status


def _emphasis(text: str) -> tuple[bool, bool, str | None, str]:
    """강조사항·계속기업 문단 유무와 원문 앞 300자."""
    lines = text.splitlines()
    chunks: list[str] = []
    matter = False
    concern = False
    for index, line in enumerate(lines):
        token = compact(line)
        hit_matter = "강조사항" in token
        hit_concern = "계속기업" in token
        if not hit_matter and not hit_concern:
            continue
        matter = matter or hit_matter
        concern = concern or hit_concern
        block = line.strip()
        if len(token) <= 12 and index + 1 < len(lines):
            follow = lines[index + 1].strip()
            if follow:
                block = f"{block}\n{follow}"
        chunks.append(block)
    if not matter and not concern:
        return False, False, None, "not_found"
    raw = "\n".join(chunks)[:_EMPHASIS_LIMIT]
    return matter, concern, raw, "ok"
