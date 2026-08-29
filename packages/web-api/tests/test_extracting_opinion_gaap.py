"""감사의견·GAAP 분류기 테스트."""

from app.extracting.opinion import classify_opinion
from app.extracting.gaap import classify_gaap


def test_boilerplate_unqualified_when_letter_and_no_exception() -> None:
    text = "감사의견 " + ("본문" * 80)
    result = classify_opinion(text, looks_like_letter=True)
    assert result.status == "ok"
    assert result.code == "unqualified"
    assert result.raw == "boilerplate_unqualified"


def test_disclaimer_keyword() -> None:
    result = classify_opinion("의견을표명하지아니합니다" + ("가" * 200), looks_like_letter=True)
    assert result.code == "disclaimer"


def test_qualified_keyword() -> None:
    """한정의견 근거 문구는 qualified이다."""
    result = classify_opinion(
        "한정의견근거단락에기술된사항이미치는영향을제외" + ("가" * 200),
        looks_like_letter=True,
    )
    assert result.code == "qualified"


def test_adverse_keyword() -> None:
    """부적정의견 근거 문구는 adverse이다."""
    result = classify_opinion(
        "부적정의견근거단락에서기술된사항의유의성" + ("가" * 200),
        looks_like_letter=True,
    )
    assert result.code == "adverse"


def test_not_found_when_not_a_letter() -> None:
    result = classify_opinion("짧음", looks_like_letter=False)
    assert result.status == "not_found"
    assert result.code is None


def test_gaap_k_ifrs_and_other() -> None:
    ifrs = classify_gaap("한국채택국제회계기준에따라작성")
    kgaap = classify_gaap("일반기업회계기준에따라작성")
    other = classify_gaap("관련 문구 없음")
    assert ifrs.code == "k-ifrs"
    assert ifrs.raw == "한국채택국제회계기준"
    assert kgaap.code == "k-gaap"
    assert kgaap.raw == "일반기업회계기준"
    assert other.code == "other"
    assert other.status == "ok"
    assert other.raw == "예외"
