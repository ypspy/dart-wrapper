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

_CONCLUSION_HEADINGS = frozenset(
    {"검토결론", "검토의견", "한정결론", "부적정결론", "결론표명거절", "의견거절"}
)
_HEADING_CODES = {
    "한정결론": "qualified",
    "부적정결론": "adverse",
    "결론표명거절": "disclaimer",
    "의견거절": "disclaimer",
}
_STOP_HEADINGS = frozenset(
    {
        "검토결론근거",
        "기타사항",
        "강조사항",
        "한정결론근거",
        "부적정결론근거",
        "결론표명거절근거",
        "한정의견근거",
    }
)
_DATE_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_RANGE_RE = re.compile(
    r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*부터\s*"
    r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*까지"
)
_END_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일(?:\s*현재|\s*로\s*종료)")
_MONTHS_RE = re.compile(r"(\d+)\s*개월")
_HALF_MONTHS = frozenset({6})
_QUARTER_MONTHS = frozenset({3, 9})
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
    doc_kind: str | None = None,
    review_kind: str | None = None,
) -> InterimReviewParse:
    """검토보고서 HTML에서 검토인·결론·날짜·기간·GAAP·강조사항을 읽는다."""
    text = html_to_text(html)
    reviewer_raw, reviewer_resolved, reviewer_status = _reviewer(text, auditor_names)
    conclusion_raw, conclusion_code, conclusion_status = _conclusion(text, doc_kind)
    date_raw, date_iso, date_status, candidates = _signature_date(text, doc_kind)
    period_raw, period_resolved, period_status = _period(text, review_kind)
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


def _is_conclusion_heading(line: str, doc_kind: str | None) -> bool:
    """줄 전체가 결론 제목일 때만 참이다. 문장 속 '감사의견'은 제목이 아니다."""
    token = compact(line)
    if token in _CONCLUSION_HEADINGS:
        return True
    return doc_kind == "audit" and token == "감사의견"


def _is_stop_heading(line: str) -> bool:
    """결론 다음에 오는 다른 제목이면 결론 문단을 끊는다."""
    token = compact(line)
    if token in _STOP_HEADINGS:
        return True
    if "책임" not in token or len(token) > 40:
        return False
    return "경영진" in token or "감사인" in token or "재무제표에대한" in token


def _is_signature_line(line: str) -> bool:
    """대표 줄이거나, 짧은 회계법인·감사반 이름 줄이다."""
    if _REP_RE.search(line):
        return True
    token = compact(line)
    if len(token) > 40:
        return False
    return token.endswith("회계법인") or token.endswith("감사반")


def _heading_span(text: str, doc_kind: str | None) -> tuple[int, int] | None:
    """줄 전체가 결론 제목인 첫 줄의 원문 구간."""
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        content = raw_line.strip()
        if content and _is_conclusion_heading(content, doc_kind):
            rel = raw_line.find(content)
            start = offset + max(rel, 0)
            return start, start + len(content)
        offset += len(raw_line)
    return None


def _signature_zone(text: str, doc_kind: str | None) -> tuple[str, int]:
    """결론 제목 뒤부터를 서명부로 본다. 제목이 없으면 본문 전체."""
    span = _heading_span(text, doc_kind)
    if span is None:
        return text, 0
    return text[span[1] :], span[1]


def _conclusion_parts(text: str, doc_kind: str | None) -> tuple[str, str]:
    """결론 제목과, 그 다음 줄부터 다음 제목 또는 서명부 직전까지의 문단."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    start: int | None = None
    for index, line in enumerate(lines):
        if _is_conclusion_heading(line, doc_kind):
            start = index
            break
    if start is None:
        return "", ""
    body: list[str] = []
    for line in lines[start + 1 :]:
        if _is_stop_heading(line) or _is_signature_line(line):
            break
        body.append(line)
    return lines[start], "\n".join(body).strip()


def _conclusion_body(text: str, doc_kind: str | None) -> str:
    """결론 제목 다음 줄부터 다음 제목 또는 서명부 직전까지."""
    return _conclusion_parts(text, doc_kind)[1]


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


def _conclusion(text: str, doc_kind: str | None) -> tuple[str | None, str, str]:
    """검토결론 문단만 보고 unmodified/qualified/adverse/disclaimer/unknown을 나눈다.

    한정·부적정·표명거절 제목은 문단 문구보다 제목 자체가 코드를 정한다.
    """
    heading, body = _conclusion_parts(text, doc_kind)
    heading_code = _HEADING_CODES.get(compact(heading))
    if not compact(body) and heading_code is None:
        return None, "unknown", "not_found"
    raw = (body or heading)[:_CONCLUSION_LIMIT]
    if heading_code is not None:
        return raw, heading_code, "ok"
    token = compact(body)
    # 감사의견 표명 거절 문장은 검토 결론 거절이 아니다.
    if "감사의견을표명하지아니" not in token and (
        "의견거절" in token
        or "결론표명하지않" in token
        or "결론을표명하지않" in token
        or "결론을표명하지아니" in token
    ):
        return raw, "disclaimer", "ok"
    if "부적정결론" in token or "부적정의견" in token:
        return raw, "adverse", "ok"
    if "한정결론" in token or "한정의견" in token or "제외하고는" in token:
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
    doc_kind: str | None,
) -> tuple[str | None, str | None, str, list[dict[str, str]]]:
    """서명부(결론 제목 뒤) 날짜 중 서명에 가장 가까운 것을 고르고 나머지는 후보로 둔다."""
    zone, offset = _signature_zone(text, doc_kind)
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


def _scope_paragraph(text: str) -> str:
    """'우리는 … 검토하였습니다'가 있는 단락. 제목이 앞이든 뒤든 그 단락을 본다."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if "우리는" in line and "검토하였습니다" in line:
            return line
    for index, line in enumerate(lines):
        if "우리는" not in line:
            continue
        chunk = "\n".join(lines[index : index + 3])
        if "검토하였습니다" in chunk:
            return chunk
    return ""


def _months_match_kind(review_kind: str | None, months: int) -> bool:
    """반기는 6개월, 분기는 3·9개월만 누적 기간으로 인정한다. 종류가 없으면 통과."""
    if review_kind == "half":
        return months in _HALF_MONTHS
    if review_kind == "quarter":
        return months in _QUARTER_MONTHS
    return True


def _resolved_range(start_iso: str, end_iso: str) -> str:
    """두 ISO 날짜를 YYYY.MM.DD~YYYY.MM.DD로 잇는다."""
    start_on = date.fromisoformat(start_iso)
    end_on = date.fromisoformat(end_iso)
    return (
        f"{_dotted(start_on.year, start_on.month, start_on.day)}"
        f"~{_dotted(end_on.year, end_on.month, end_on.day)}"
    )


def _inclusive_months(start_iso: str, end_iso: str) -> int:
    """시작 달부터 끝 달까지를 센다. 1월~6월은 6이다."""
    start_on = date.fromisoformat(start_iso)
    end_on = date.fromisoformat(end_iso)
    return (end_on.year - start_on.year) * 12 + (end_on.month - start_on.month) + 1


def _period(text: str, review_kind: str | None) -> tuple[str | None, str | None, str]:
    """대상 재무제표 단락의 부터~까지, 없으면 기준일과 가장 긴 개월 수로 기간을 만든다.

    부터~까지가 여러 개면 가장 긴 누적 구간을 고른 뒤, 그 개월 수가 반기·분기와
    맞는지 본다. 3개월만 있는 반기는 그 구간을 ok로 저장하지 않는다.
    """
    scope = _scope_paragraph(text)
    if not scope:
        return None, None, "not_found"
    ranges: list[tuple[int, int, str, str, str]] = []
    for ranged in _RANGE_RE.finditer(scope):
        start = _calendar_iso(int(ranged.group(1)), int(ranged.group(2)), int(ranged.group(3)))
        end = _calendar_iso(int(ranged.group(4)), int(ranged.group(5)), int(ranged.group(6)))
        if not start or not end or start > end:
            continue
        start_on = date.fromisoformat(start)
        end_on = date.fromisoformat(end)
        ranges.append(
            (
                _inclusive_months(start, end),
                (end_on - start_on).days,
                ranged.group(0),
                start,
                end,
            )
        )
    if ranges:
        months, _days, raw, start, end = max(ranges, key=lambda item: (item[0], item[1]))
        if not _months_match_kind(review_kind, months):
            return raw, None, "ambiguous"
        return raw, _resolved_range(start, end), "ok"

    current = _END_RE.search(scope)
    month_matches = list(_MONTHS_RE.finditer(scope))
    if current is None or not month_matches:
        return None, None, "not_found"
    months = max(int(item.group(1)) for item in month_matches)
    raw = f"{current.group(0)} " + " ".join(item.group(0) for item in month_matches)
    if months < 1:
        return raw, None, "not_found"
    if not _months_match_kind(review_kind, months):
        return raw, None, "ambiguous"
    end_iso = _calendar_iso(int(current.group(1)), int(current.group(2)), int(current.group(3)))
    if end_iso is None:
        return raw, None, "not_found"
    end_on = date.fromisoformat(end_iso)
    start_on = _start_of_month_span(end_on, months)
    start_iso = start_on.isoformat()
    return raw, _resolved_range(start_iso, end_iso), "ok"


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
