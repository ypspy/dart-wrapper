"""D-3-4 GAAP 분류."""

from __future__ import annotations

from app.extracting.result import FieldResult
from app.extracting.text import compact

# ypspy/dart-scraping (D-3-4) auditReportGAAP KGAAP/KIFRS/OTHERS 원문
_KGAAP_PATTERNS = (
    "일반기업회계기준에따라",
    "일반회계기준에따라",
    "一般企業會計基準에따라",
    "일반기업회계처리기준에따라",
    "'일반기업회계기준'에 따라",
    "'일반기업회계기준'에따라",  # 위 공백 포함 원문의 compact 패턴
)
_KIFRS_PATTERNS = (
    "한국채택국제회계기준에따라",
    "한국채택회계기준",
)
_OTHERS_PATTERNS = (
    "공기업ㆍ준정부기관회계사무규칙에따라",
    "지방공기업법및지방공기업결산지침에따라",
    "지방공기업법(령)및지방공기업결산지침에따라",
    "일반기업회계기준및",
    "지방공기업법과행정자치부의지방공기업결산지침,대구도시공사정관및회계규정에따라",
)

# (code, tag 한글명, compact 패턴)
_GAAP_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = tuple(
    (code, tag, tuple(compact(pattern) for pattern in patterns))
    for code, tag, patterns in (
        ("k-gaap", "일반기업회계기준", _KGAAP_PATTERNS),
        ("k-ifrs", "한국채택국제회계기준", _KIFRS_PATTERNS),
        ("other", "기타기준", _OTHERS_PATTERNS),
    )
)


def classify_gaap(text: str) -> FieldResult:
    """의견 본문에서 GAAP를 분류한다.

    D-3-4 문구를 순서대로 찾고, 없으면 code=other, raw=예외를 반환한다.
    """
    compacted = compact(text)
    for code, tag, patterns in _GAAP_GROUPS:
        for pattern in patterns:
            if pattern in compacted:
                return FieldResult(raw=tag, code=code, status="ok")

    return FieldResult(raw="예외", code="other", status="ok")
