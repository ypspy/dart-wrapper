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


def test_not_found_when_not_a_letter() -> None:
    result = classify_opinion("짧음", looks_like_letter=False)
    assert result.status == "not_found"
    assert result.code is None


def test_gaap_k_ifrs_and_other() -> None:
    assert classify_gaap("한국채택국제회계기준에따라작성").code == "k-ifrs"
    assert classify_gaap("일반기업회계기준에따라작성").code == "k-gaap"
    assert classify_gaap("관련 문구 없음").code == "other"
    assert classify_gaap("관련 문구 없음").status == "ok"
