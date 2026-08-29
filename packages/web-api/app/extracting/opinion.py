"""D-3-2 감사의견 분류."""

from __future__ import annotations

from app.extracting.result import FieldResult
from app.extracting.text import compact

# ypspy/dart-scraping (D-3-2) auditReportOpinion keyWord1..3 원문
_DISCLAIMER_KEYWORDS = (
    "의견거절근거",
    "의견을표명하지않",
    "감사의견을표명하지아니합니다",
    "의견을표명하지아니",
    "의견을표명할수없",
)
_QUALIFIED_KEYWORDS = (
    "한정의견근거",
    "한정의견근거단락에기술된사항이미치는영향을제외",
)
_ADVERSE_KEYWORDS = (
    "부적정의견근거",
    "부적정의견근거단락에서기술된사항의유의성",
)

# (code, keywords) — 거절 → 한정 → 부적정 순, 첫 매칭이 이긴다.
_OPINION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("disclaimer", _DISCLAIMER_KEYWORDS),
    ("qualified", _QUALIFIED_KEYWORDS),
    ("adverse", _ADVERSE_KEYWORDS),
)

_SNIPPET_RADIUS = 80
_CUT_MARKERS = (
    "강조사항",
    "핵심감사사항",
    "기타사항",
    "재무제표에대한경",
    "감사의견에는영향을미치지않는사항",
    "영향을미치지않는사항",
)
_CITATION_MARKERS = (
    "일자로발행한감사보고서에서",
    "비교표시목적으로",
)


def _opinion_window(compacted: str) -> str:
    """끊는 표지 앞만 남긴다. 표지가 없으면 전체다."""
    cuts = [compacted.find(marker) for marker in _CUT_MARKERS]
    cuts = [index for index in cuts if index >= 0]
    if not cuts:
        return compacted
    return compacted[: min(cuts)]


def _is_prior_report_citation(compacted: str, start: int, length: int) -> bool:
    """히트 앞뒤 80자에 과거 보고서 인용 표지가 있는지 본다."""
    left = max(0, start - _SNIPPET_RADIUS)
    right = min(len(compacted), start + length + _SNIPPET_RADIUS)
    snippet = compacted[left:right]
    return any(marker in snippet for marker in _CITATION_MARKERS)


def classify_opinion(text: str, *, looks_like_letter: bool) -> FieldResult:
    """감사의견 본문을 분류한다.

    looks_like_letter가 False이면 즉시 not_found를 반환한다.
    True이면 끊는 표지 앞 구간에서 D-3-2 키워드를 거절→한정→부적정 순으로 찾고,
    과거 보고서 인용 히트는 건너뛴다. 없으면 boilerplate 적정을 반환한다.
    """
    if not looks_like_letter:
        return FieldResult(raw=None, code=None, status="not_found")

    window = _opinion_window(compact(text))
    for code, keywords in _OPINION_GROUPS:
        for keyword in keywords:
            start = 0
            while True:
                found = window.find(keyword, start)
                if found < 0:
                    break
                if not _is_prior_report_citation(window, found, len(keyword)):
                    return FieldResult(raw=keyword, code=code, status="ok")
                start = found + 1

    return FieldResult(
        raw="boilerplate_unqualified",
        code="unqualified",
        status="ok",
    )
