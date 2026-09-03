"""내부회계관리제도 감사·검토 의견 추출."""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.extracting.text import compact

_CONSOLIDATED_AUDIT_PHRASE = "연결내부회계관리제도를감사하였"
_SEPARATE_AUDIT_PHRASE = "내부회계관리제도를감사하였"
_REVIEW_REPORT = "내부회계관리제도검토보고서"
_REVIEW_STANDARD = "검토기준에따라검토"
_AUDIT_REPORT = "내부회계관리제도감사보고서"

_AUDIT_HEADINGS: tuple[tuple[str, str], ...] = (
    ("내부회계관리제도에대한의견거절", "disclaimer"),
    ("내부회계관리제도에대한부적정의견", "adverse"),
    ("내부회계관리제도에대한감사의견", "unqualified"),
)
_AUDIT_CUTS = (
    "내부회계관리제도감사의견근거",
    "내부회계관리제도부적정의견근거",
    "내부회계관리제도의견거절근거",
    "내부회계관리제도에대한경영진과지배기구의책임",
)
_AUDIT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("disclaimer", ("의견을표명하지", "의견거절근거")),
    ("adverse", ("효과적으로설계및운영되고있지", "부적정의견근거")),
)
_REVIEW_CUT = "내부회계관리제도에대한경영진과지배기구의책임"
_REVIEW_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("disclaimer", ("검토의견을표명하지",)),
    ("qualified", ("미치는영향을제외하고는",)),
    ("material_weakness", ("중요한취약점이발견되었", "중요한취약점이언급")),
)


@dataclass(frozen=True)
class IcfrResult:
    """내부회계 leaf 한 장의 판별·의견."""

    engagement: str | None
    opinion_raw: str | None
    opinion_code: str | None
    status: str


def _compact_html(html: str | None) -> str:
    if not html:
        return ""
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    return compact(text)


def _before_markers(compacted: str, markers: tuple[str, ...]) -> str:
    cuts = [compacted.find(marker) for marker in markers]
    hits = [index for index in cuts if index >= 0]
    if not hits:
        return compacted
    return compacted[: min(hits)]


def _first_keyword(
    compacted: str, groups: tuple[tuple[str, tuple[str, ...]], ...]
) -> tuple[str, str] | None:
    for code, keywords in groups:
        for keyword in keywords:
            if keyword in compacted:
                return keyword, code
    return None


def _classify_engagement(
    opinion_compact: str, icfr_compact: str, fs_scope: str
) -> str:
    """스펙 §6 순서. leaf가 있을 때만 호출한다."""
    if fs_scope == "consolidated":
        if _CONSOLIDATED_AUDIT_PHRASE in opinion_compact:
            return "audit"
    elif (
        _SEPARATE_AUDIT_PHRASE in opinion_compact
        and _CONSOLIDATED_AUDIT_PHRASE not in opinion_compact
    ):
        return "audit"
    if _REVIEW_REPORT in icfr_compact or _REVIEW_STANDARD in icfr_compact:
        return "review"
    if _AUDIT_REPORT in icfr_compact or _SEPARATE_AUDIT_PHRASE in icfr_compact:
        return "audit"
    return "none"


def _classify_audit(icfr_compact: str) -> tuple[str, str]:
    for heading, code in _AUDIT_HEADINGS:
        if heading in icfr_compact:
            return heading, code
    window = _before_markers(icfr_compact, _AUDIT_CUTS)
    hit = _first_keyword(window, _AUDIT_KEYWORDS)
    if hit is not None:
        return hit
    return "boilerplate_unqualified", "unqualified"


def _classify_review(icfr_compact: str) -> tuple[str, str]:
    start = icfr_compact.find(_REVIEW_CUT)
    window = icfr_compact if start < 0 else icfr_compact[:start]
    hit = _first_keyword(window, _REVIEW_KEYWORDS)
    if hit is not None:
        return hit
    return "boilerplate_unqualified", "unqualified"


def extract_icfr(
    *,
    opinion_html: str | None,
    icfr_html: str | None,
    fs_scope: str,
) -> IcfrResult:
    """내부회계 leaf와 재무제표 의견서 HTML에서 engagement·의견 코드를 뽑는다."""
    if not icfr_html:
        return IcfrResult(None, None, None, "skipped")
    icfr_compact = _compact_html(icfr_html)
    opinion_compact = _compact_html(opinion_html)
    engagement = _classify_engagement(opinion_compact, icfr_compact, fs_scope)
    if engagement == "none":
        return IcfrResult("none", None, None, "ok")
    if engagement == "audit":
        raw, code = _classify_audit(icfr_compact)
    else:
        raw, code = _classify_review(icfr_compact)
    return IcfrResult(engagement, raw, code, "ok")
