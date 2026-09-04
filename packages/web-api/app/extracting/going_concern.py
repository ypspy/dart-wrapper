"""의견서 HTML에서 당기 계속기업 중요한 불확실성(MU)을 판정한다."""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.extracting.text import compact

_HEADING = "계속기업관련중요한불확실성"
_GC_STEMS = ("계속기업가정", "계속기업전제", "계속기업")
_MU_MARKERS = ("중요한불확실성",)
_DOUBT_MARKERS = ("존속능력", "유의적의문", "유의적의문을")
_LIQUIDATION = ("청산가치", "청산기준")
_GROUNDS_HEADS = ("한정의견근거", "부적정의견근거", "의견거절근거")
_EOM_HEADS = ("강조사항", "특기사항")
_STRIP_FROM = (
    "재무제표에대한경영진과지배기구의책임",
    "연결재무제표에대한경영진과지배기구의책임",
    "재무제표에대한경영진의책임",
    "연결재무제표에대한경영진의책임",
    "재무제표감사에대한감사인의책임",
    "연결재무제표감사에대한감사인의책임",
    "감사인의책임",
    "기타사항",
)
_EOM_END = (
    "핵심감사사항",
    "기타사항",
    "재무제표에대한경영진과지배기구의책임",
    "재무제표에대한경영진의책임",
    "경영진의책임",
    "한정의견근거",
    "부적정의견근거",
    "의견거절근거",
)
_GROUNDS_END = (
    "한정의견",
    "부적정의견",
    "의견거절",
    "강조사항",
    "특기사항",
    "핵심감사사항",
    "기타사항",
    "재무제표에대한경영진과지배기구의책임",
    "재무제표에대한경영진의책임",
)
_GROUNDS_STRIP_FROM = ("기타사항",)


@dataclass(frozen=True)
class GoingConcernResult:
    """당기 계속기업 MU 판정."""

    going_concern: int | None
    status: str
    raw: str | None
    source: str | None


def _compact_html(html: str) -> str:
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    return compact(text)


def _cut_from(compacted: str, markers: tuple[str, ...]) -> str:
    cuts = [compacted.find(marker) for marker in markers]
    hits = [index for index in cuts if index >= 0]
    if not hits:
        return compacted
    return compacted[: min(hits)]


def _section_after(compacted: str, head: str, ends: tuple[str, ...]) -> str | None:
    start = compacted.find(head)
    if start < 0:
        return None
    body = compacted[start + len(head) :]
    return _cut_from(body, ends)


def _eom_section_ranges(compacted: str) -> list[tuple[int, int]]:
    """강조사항/특기사항 본문 구간 (start, end) 목록."""
    ranges: list[tuple[int, int]] = []
    for head in _EOM_HEADS:
        start = 0
        while True:
            found = compacted.find(head, start)
            if found < 0:
                break
            body_start = found + len(head)
            body = compacted[body_start:]
            body_end = body_start + len(_cut_from(body, _EOM_END))
            ranges.append((body_start, body_end))
            start = found + 1
    return ranges


def _is_inside_eom_section(compacted: str, pos: int) -> bool:
    return any(start <= pos < end for start, end in _eom_section_ranges(compacted))


def _has_gc_heading(compacted: str) -> bool:
    start = 0
    while True:
        found = compacted.find(_HEADING, start)
        if found < 0:
            return False
        if _is_inside_eom_section(compacted, found):
            start = found + 1
            continue
        after = compacted[found + len(_HEADING) :]
        if not after.startswith("단락"):
            return True
        start = found + 1


def _has_mu(compacted: str) -> bool:
    if not any(stem in compacted for stem in _GC_STEMS):
        return False
    if any(marker in compacted for marker in _MU_MARKERS):
        return True
    return any(marker in compacted for marker in _DOUBT_MARKERS)


def _is_liquidation_only(compacted: str) -> bool:
    if not any(token in compacted for token in _LIQUIDATION):
        return False
    return "중요한불확실성" not in compacted


def extract_going_concern(opinion_html: str | None) -> GoingConcernResult:
    """의견서 HTML에서 당기 MU가 있으면 1, 없으면 0이다. HTML이 없으면 skipped."""
    if not opinion_html:
        return GoingConcernResult(None, "skipped", None, None)

    full = _compact_html(opinion_html)
    searchable = _cut_from(full, _STRIP_FROM)

    if _has_gc_heading(searchable):
        return GoingConcernResult(1, "ok", "계속기업 관련 중요한 불확실성", "heading")

    for head in _EOM_HEADS:
        section = _section_after(searchable, head, _EOM_END)
        if not section:
            continue
        if _is_liquidation_only(section):
            continue
        if _has_mu(section):
            snippet = section[:80]
            return GoingConcernResult(1, "ok", snippet, "eom")

    grounds_searchable = _cut_from(full, _GROUNDS_STRIP_FROM)
    for head in _GROUNDS_HEADS:
        section = _section_after(grounds_searchable, head, _GROUNDS_END)
        if not section:
            continue
        if _has_mu(section):
            snippet = section[:80]
            return GoingConcernResult(1, "ok", snippet, "grounds")

    return GoingConcernResult(0, "ok", None, None)
