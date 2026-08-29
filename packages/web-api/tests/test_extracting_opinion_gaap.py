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


def test_emphasis_of_matter_prior_disclaimer_is_unqualified() -> None:
    """강조사항의 과거 거절 인용은 당기 적정을 덮지 않는다."""
    text = (
        "감사의견 우리는 재무제표를 감사하였습니다. "
        "감사의견근거 대한민국의 회계감사기준에 따라 감사를 수행하였습니다. "
        + ("본문" * 40)
        + " 감사의견에는 영향을 미치지 않는 사항으로서 "
        "우리는 회사의 2021년 12월 31일로 종료되는 회계연도의 재무제표에 대하여 "
        "2022년 5월 16일자로 발행한 감사보고서에서 의견을 표명하지 않았습니다."
    )
    result = classify_opinion(text, looks_like_letter=True)
    assert result.status == "ok"
    assert result.code == "unqualified"
    assert result.raw == "boilerplate_unqualified"


def test_disclaimer_in_opinion_paragraph_still_disclaimer() -> None:
    """결론 문단의 거절 키워드는 그대로 disclaimer이다."""
    text = (
        "감사의견 우리는 의견을 표명하지 않습니다. "
        "의견거절근거 감사범위 제한. "
        + ("가" * 80)
        + " 강조사항 과거 보고서는 무효입니다."
    )
    result = classify_opinion(text, looks_like_letter=True)
    assert result.code == "disclaimer"
    assert result.raw == "의견거절근거"


def test_qualified_grounds_before_kam_still_qualified() -> None:
    """한정의견 근거 문구는 핵심감사사항 앞 구간에 있으면 qualified이다."""
    text = (
        "감사의견 한정의견근거단락에기술된사항이미치는영향을제외하고는 적정합니다. "
        "핵심감사사항 재고자산."
        + ("가" * 80)
    )
    result = classify_opinion(text, looks_like_letter=True)
    assert result.code == "qualified"


def test_no_cut_marker_keeps_full_text_disclaimer() -> None:
    """끊는 표지가 없으면 본문 전체에서 거절 키워드를 찾는다."""
    result = classify_opinion(
        "의견을표명하지아니합니다" + ("가" * 200),
        looks_like_letter=True,
    )
    assert result.code == "disclaimer"


def test_citation_without_cut_skips_hit_then_unqualified() -> None:
    """표지는 없어도 인용 문맥의 거절 히트는 버리고 적정이 된다."""
    text = (
        "감사의견 우리는 재무제표를 감사하였습니다. "
        + ("본문" * 30)
        + " 비교표시목적으로 첨부된 전기 재무제표에 대하여 "
        "의견을 표명하지 않았습니다."
    )
    result = classify_opinion(text, looks_like_letter=True)
    assert result.code == "unqualified"
    assert result.raw == "boilerplate_unqualified"
