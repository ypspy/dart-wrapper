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


def classify_opinion(text: str, *, looks_like_letter: bool) -> FieldResult:
    """감사의견 본문을 분류한다.

    looks_like_letter가 False이면 즉시 not_found를 반환한다.
    True이면 D-3-2 키워드를 거절→한정→부적정 순으로 찾고,
    없으면 boilerplate 적정을 반환한다.
    """
    if not looks_like_letter:
        return FieldResult(raw=None, code=None, status="not_found")

    compacted = compact(text)
    for code, keywords in _OPINION_GROUPS:
        for keyword in keywords:
            if keyword in compacted:
                return FieldResult(raw=keyword, code=code, status="ok")

    return FieldResult(
        raw="boilerplate_unqualified",
        code="unqualified",
        status="ok",
    )
