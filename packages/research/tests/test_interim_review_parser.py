"""검토보고서 필드 파서 테스트. 합성 HTML fixture만 읽는다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.extracting.interim_review import parse_interim_review

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "interim_review"
_MANIFEST = json.loads((_FIXTURE / "manifest.json").read_text(encoding="utf-8"))
_KEYS = (
    "conclusion_code",
    "conclusion_status",
    "review_report_date",
    "review_report_date_status",
    "review_period_resolved",
    "review_period_status",
    "gaap_code",
    "gaap_status",
    "emphasis_of_matter",
    "going_concern",
    "emphasis_status",
    "reviewer_status",
    "reviewer_resolved",
)


@pytest.mark.parametrize("expect", _MANIFEST["documents"], ids=lambda item: item["file"])
def test_parse_interim_fixture(expect: dict[str, object]) -> None:
    """합성 검토보고서에서 결론·날짜·기간·GAAP·강조·검토인을 읽는다."""
    html = (_FIXTURE / str(expect["file"])).read_text(encoding="utf-8")
    parsed = parse_interim_review(html)
    for key in _KEYS:
        assert getattr(parsed, key) == expect[key], key
    assert [item["iso"] for item in parsed.review_report_date_candidates] == expect[
        "candidate_isos"
    ]
    if expect["emphasis_status"] == "not_found":
        assert parsed.emphasis_raw is None
    else:
        assert parsed.emphasis_raw is not None
        assert len(parsed.emphasis_raw) <= 300
        prefix = expect.get("emphasis_raw_prefix")
        if prefix:
            assert str(parsed.emphasis_raw).startswith(str(prefix))
        if expect.get("emphasis_raw_len") is not None:
            assert len(parsed.emphasis_raw) == expect["emphasis_raw_len"]
    if parsed.review_report_date_status == "ok":
        assert parsed.review_report_date not in {
            item["iso"] for item in parsed.review_report_date_candidates
        }


def test_dictionary_name_is_preferred_for_reviewer() -> None:
    """감사인 목록에 있으면 그 정규화 이름을 검토인으로 쓴다."""
    html = """
    <html><body>
    <p>검토결론</p>
    <p>추가 자료가 필요합니다.</p>
    <p>라마 바회계법인</p>
    <p>대표이사 홍길동</p>
    </body></html>
    """
    parsed = parse_interim_review(html, auditor_names=("라마 바회계법인",))
    assert parsed.reviewer_status == "ok"
    assert parsed.reviewer_resolved == "라마바회계법인"
    assert parsed.conclusion_code == "unknown"


def _read_fixture(name: str) -> str:
    return (_FIXTURE / name).read_text(encoding="utf-8")


def _assert_conclusion_paragraph_only(raw: str | None) -> None:
    """결론 원문은 결론 문단만 담고 근거·기타·서명으로 넘어가지 않는다."""
    assert raw is not None
    assert "발견되지" in raw
    for banned in (
        "한정의견",
        "한정되어",
        "검토결론근거",
        "기타사항",
        "감사의견을 표명하지",
        "가나다회계법인",
        "대표이사",
    ):
        assert banned not in raw


def test_leading_conclusion_ignores_later_qualified_words() -> None:
    """앞에 오는 검토결론은 뒤의 근거·전기 한정의견을 결론으로 보지 않는다."""
    parsed = parse_interim_review(
        _read_fixture("leading_conclusion_unmodified.html"),
        review_kind="half",
    )
    assert parsed.conclusion_code == "unmodified"
    assert parsed.conclusion_status == "ok"
    _assert_conclusion_paragraph_only(parsed.conclusion_raw)
    assert parsed.review_period_resolved == "2025.01.01~2025.06.30"
    assert parsed.review_period_status == "ok"


def test_responsibility_sentence_is_not_a_conclusion_heading() -> None:
    """'감사의견을 표명하지 아니합니다'는 제목이 아니고 결론 문단에 들어가지 않는다."""
    parsed = parse_interim_review(_read_fixture("trailing_opinion_unmodified.html"))
    assert parsed.conclusion_code == "unmodified"
    assert parsed.conclusion_status == "ok"
    _assert_conclusion_paragraph_only(parsed.conclusion_raw)
    assert parsed.conclusion_raw is not None
    assert parsed.conclusion_raw.startswith("우리의 검토결과")
    assert "표명하지 아니합니다" not in parsed.conclusion_raw


def test_prior_period_qualified_mention_stays_unmodified() -> None:
    """기타사항의 전기 한정의견은 당기 결론을 qualified로 바꾸지 않는다."""
    parsed = parse_interim_review(_read_fixture("prior_period_qualified_mention.html"))
    assert parsed.conclusion_code == "unmodified"
    assert parsed.conclusion_status == "ok"
    _assert_conclusion_paragraph_only(parsed.conclusion_raw)


def test_half_period_uses_cumulative_six_months() -> None:
    """'3개월 및 6개월'은 누적 6개월인 1월 1일부터 6월 30일이다."""
    parsed = parse_interim_review(
        _read_fixture("half_cumulative_months.html"),
        review_kind="half",
    )
    assert parsed.review_period_resolved == "2025.01.01~2025.06.30"
    assert parsed.review_period_status == "ok"
    assert parsed.review_period_resolved != "2025.04.01~2025.06.30"


def test_quarter_period_uses_cumulative_nine_months() -> None:
    """'3개월 및 9개월'은 누적 9개월인 1월 1일부터 9월 30일이다."""
    parsed = parse_interim_review(
        _read_fixture("quarter_cumulative_nine_months.html"),
        review_kind="quarter",
    )
    assert parsed.review_period_resolved == "2025.01.01~2025.09.30"
    assert parsed.review_period_status == "ok"
    assert parsed.review_period_resolved != "2025.07.01~2025.09.30"


def test_first_quarter_period_is_three_months() -> None:
    """1분기 '3개월'은 1월 1일부터 3월 31일이다."""
    parsed = parse_interim_review(
        _read_fixture("quarter_three_months.html"),
        review_kind="quarter",
    )
    assert parsed.review_period_resolved == "2025.01.01~2025.03.31"
    assert parsed.review_period_status == "ok"


def test_month_span_that_disagrees_with_review_kind_is_ambiguous() -> None:
    """반기 문서에 3개월만 있으면 틀린 기간을 ok로 저장하지 않는다."""
    html = """
    <html><body>
    <p>우리는 2025년 6월 30일 현재로 종료되는 3개월 보고기간의 반기재무제표를 검토하였습니다.</p>
    <p>검토결론</p>
    <p>우리의 검토결과, 상기 반기재무제표가 중요성의 관점에서 한국채택국제회계기준에 따라
    작성되지 않았다는 점이 발견되지 않았습니다.</p>
    </body></html>
    """
    parsed = parse_interim_review(html, review_kind="half")
    assert parsed.review_period_status == "ambiguous"
    assert parsed.review_period_resolved is None
    assert parsed.review_period_raw is not None
    assert "3개월" in parsed.review_period_raw
    assert "2025.04.01~2025.06.30" not in (parsed.review_period_raw or "")


def test_half_only_short_calendar_range_is_ambiguous() -> None:
    """반기 문서에 4월~6월 구간만 있으면 그 기간을 ok로 두지 않는다."""
    html = """
    <html><body>
    <p>우리는 2025년 4월 1일부터 2025년 6월 30일까지의 반기재무제표를 검토하였습니다.</p>
    </body></html>
    """
    parsed = parse_interim_review(html, review_kind="half")
    assert parsed.review_period_status == "ambiguous"
    assert parsed.review_period_resolved is None
    assert parsed.review_period_raw == "2025년 4월 1일부터 2025년 6월 30일까지"


def test_half_picks_longest_cumulative_range() -> None:
    """3개월 구간과 6개월 구간이 있으면 누적 1월 1일~6월 30일을 고른다."""
    html = """
    <html><body>
    <p>우리는 2025년 4월 1일부터 2025년 6월 30일까지 및
    2025년 1월 1일부터 2025년 6월 30일까지의 재무제표를 검토하였습니다.</p>
    </body></html>
    """
    parsed = parse_interim_review(html, review_kind="half")
    assert parsed.review_period_status == "ok"
    assert parsed.review_period_resolved == "2025.01.01~2025.06.30"


def test_quarter_nine_month_calendar_range_is_ok() -> None:
    """3분기 1월 1일부터 9월 30일까지는 누적 9개월로 인정한다."""
    html = """
    <html><body>
    <p>우리는 2025년 1월 1일부터 2025년 9월 30일까지의 분기재무제표를 검토하였습니다.</p>
    </body></html>
    """
    parsed = parse_interim_review(html, review_kind="quarter")
    assert parsed.review_period_status == "ok"
    assert parsed.review_period_resolved == "2025.01.01~2025.09.30"


@pytest.mark.parametrize(
    ("heading", "code"),
    [
        ("한정결론", "qualified"),
        ("부적정결론", "adverse"),
        ("결론표명거절", "disclaimer"),
        ("의견거절", "disclaimer"),
    ],
)
def test_special_conclusion_heading_sets_the_code(heading: str, code: str) -> None:
    """한정·부적정·표명거절 제목 자체가 결론 코드를 정하고 근거 문단은 끊는다."""
    html = f"""
    <html><body>
    <p>{heading}</p>
    <p>결론 본문입니다.</p>
    <p>강조사항</p>
    <p>근거 문단은 결론에 넣지 않습니다.</p>
    </body></html>
    """
    parsed = parse_interim_review(html)
    assert parsed.conclusion_status == "ok"
    assert parsed.conclusion_code == code
    assert parsed.conclusion_raw is not None
    assert parsed.conclusion_raw.startswith("결론 본문")
    assert "근거 문단" not in parsed.conclusion_raw


def test_standard_review_sentence_stays_unmodified() -> None:
    """표준 검토결과 문장은 unmodified로 남는다."""
    html = """
    <html><body>
    <p>검토결론</p>
    <p>우리의 검토결과, 상기 재무제표가 중요성의 관점에서 한국채택국제회계기준에 따라
    작성되지 않았다는 점이 발견되지 않았습니다.</p>
    <p>한정의견근거</p>
    <p>전기에는 한정의견이었습니다.</p>
    </body></html>
    """
    parsed = parse_interim_review(html)
    assert parsed.conclusion_code == "unmodified"
    assert parsed.conclusion_status == "ok"
    assert parsed.conclusion_raw is not None
    assert "한정의견" not in parsed.conclusion_raw


def test_refusal_to_express_conclusion_is_disclaimer() -> None:
    """'결론을 표명하지 아니합니다'는 disclaimer다."""
    html = """
    <html><body>
    <p>검토결론</p>
    <p>우리는 결론을 표명하지 아니합니다.</p>
    </body></html>
    """
    parsed = parse_interim_review(html)
    assert parsed.conclusion_code == "disclaimer"
    assert parsed.conclusion_status == "ok"


def test_audit_opinion_refusal_sentence_is_not_a_review_disclaimer() -> None:
    """'감사의견을 표명하지 아니합니다'만으로는 검토 결론 거절이 아니다."""
    html = """
    <html><body>
    <p>검토결론</p>
    <p>우리는 감사의견을 표명하지 아니합니다.</p>
    </body></html>
    """
    parsed = parse_interim_review(html)
    assert parsed.conclusion_code != "disclaimer"
