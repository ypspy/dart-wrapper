from app.extracting.going_concern import extract_going_concern


def _html(*paragraphs: str) -> str:
    body = "".join(f"<p>{text}</p>" for text in paragraphs)
    return f"<html><body>{body}</body></html>"


_RESP = (
    "경영진은 재무제표를 작성할 때 회사의 계속기업으로서의 존속능력을 평가하고 "
    "계속기업 관련 사항을 공시할 책임이 있습니다."
)
_AUDITOR_RESP = (
    "경영진이 사용한 회계의 계속기업전제의 적절성과 중요한 불확실성이 존재하는지 "
    "여부에 대하여 결론을 내립니다."
)


def test_missing_html_is_skipped() -> None:
    result = extract_going_concern(None)
    assert result.status == "skipped"
    assert result.going_concern is None


def test_boilerplate_responsibility_only_is_zero() -> None:
    result = extract_going_concern(
        _html("감사의견", "적정입니다.", _RESP, _AUDITOR_RESP),
        opinion_code="unqualified",
    )
    assert result.status == "ok"
    assert result.going_concern == 0
    assert result.source is None


def test_2018_heading_is_one() -> None:
    result = extract_going_concern(
        _html(
            "감사의견",
            "적정입니다.",
            "계속기업 관련 중요한 불확실성",
            "주석 XXX에 주의를 기울여야 할 필요가 있습니다. "
            "계속기업으로서의 존속능력에 유의적 의문을 제기할 만한 중요한 불확실성이 존재함을 나타냅니다. "
            "우리의 의견은 이 사항으로부터 영향을 받지 아니합니다.",
            "핵심감사사항",
            "우리는 계속기업 관련 중요한 불확실성 단락에 기술된 사항에 추가하여 핵심감사사항을 결정하였습니다.",
            "재무제표에 대한 경영진과 지배기구의 책임",
            _RESP,
            "재무제표감사에 대한 감사인의 책임",
            _AUDITOR_RESP,
        ),
        opinion_code="unqualified",
    )
    assert result.going_concern == 1
    assert result.source == "heading"
    assert result.status == "ok"
    assert result.raw is not None


def test_2014_eom_is_one() -> None:
    result = extract_going_concern(
        _html(
            "감사의견",
            "적정입니다.",
            "강조사항",
            "감사의견에는 영향을 미치지 않는 사항으로서 이용자는 주석 X에 주의를 기울여야 할 필요가 있습니다. "
            "이러한 상황은 계속기업으로서의 존속능력에 유의적 의문을 제기할 만한 중요한 불확실성이 존재함을 나타냅니다.",
            "경영진의 책임",
            _RESP,
        ),
        opinion_code="unqualified",
    )
    assert result.going_concern == 1
    assert result.source == "eom"


def test_qualified_grounds_is_zero() -> None:
    result = extract_going_concern(
        _html(
            "한정의견 근거",
            "이 상황은 계속기업으로서의 존속능력에 유의적 의문을 제기할 수 있는 중요한 불확실성의 존재를 나타냅니다. "
            "재무제표에는 이 사실이 적절하게 공시되지 않았습니다.",
            "한정의견",
            "한정의견근거문단에 기술된 사항을 제외하고는 공정하게 표시하고 있습니다.",
        ),
        opinion_code="qualified",
    )
    assert result.going_concern == 0
    assert result.source is None


def test_disclaimer_grounds_mu_is_zero() -> None:
    result = extract_going_concern(
        _html(
            "의견거절 근거",
            "연결재무제표는 계속기업으로서 존속한다는 가정을 전제로 작성되었습니다. "
            "이러한 사항은 계속기업으로서의 존속능력에 유의적 의문을 제기할 만한 "
            "중요한 불확실성이 존재함을 나타냅니다. "
            "그러나 이러한 불확실성의 최종 결과를 합리적으로 추정할 감사증거를 확보할 수 없었습니다.",
            "의견거절",
            "의견을 표명하지 않습니다.",
        ),
        opinion_code="disclaimer",
    )
    assert result.going_concern == 0
    assert result.source is None


def test_heading_on_disclaimer_is_zero() -> None:
    """거절 의견서에 MU 제목이 있어도 적정 강조가 아니므로 0이다."""
    result = extract_going_concern(
        _html(
            "의견거절",
            "의견을 표명하지 않습니다.",
            "계속기업 관련 중요한 불확실성",
            "주석에 주의를 기울여야 할 필요가 있습니다. "
            "계속기업으로서의 존속능력에 유의적 의문을 제기할 만한 중요한 불확실성이 존재함을 나타냅니다.",
            "의견거절 근거",
            "충분하고 적합한 감사증거를 입수할 수 없었습니다.",
        ),
        opinion_code="disclaimer",
    )
    assert result.going_concern == 0
    assert result.source is None


def test_litigation_eom_is_zero() -> None:
    result = extract_going_concern(
        _html(
            "강조사항",
            "회사를 상대로 소송이 제기되었으며 소송의 결과는 불확실합니다. "
            "우리의 의견은 이 사항과 관련하여 영향을 받지 아니합니다.",
        ),
        opinion_code="unqualified",
    )
    assert result.going_concern == 0


def test_liquidation_eom_is_zero() -> None:
    result = extract_going_concern(
        _html(
            "강조사항",
            "회사는 주주총회 결의에 따라 청산될 예정입니다. "
            "이에 따라 회사의 재무제표는 청산가치를 기반으로 작성되었습니다.",
        ),
        opinion_code="unqualified",
    )
    assert result.going_concern == 0


def test_other_matter_prior_year_is_zero() -> None:
    result = extract_going_concern(
        _html(
            "감사의견",
            "적정입니다.",
            "기타사항",
            "전기 감사보고서에는 계속기업 가정의 불확실성에 대한 부적절한 공시로 인한 한정의견이 표명되었습니다.",
            "재무제표에 대한 경영진과 지배기구의 책임",
            _RESP,
        ),
        opinion_code="unqualified",
    )
    assert result.going_concern == 0


def test_eom_gc_heading_phrase_in_body_is_eom_not_heading() -> None:
    """강조사항 본문에 계속기업관련중요한불확실성 문구가 있어도 heading이 아닌 eom."""
    result = extract_going_concern(
        _html(
            "감사의견",
            "적정입니다.",
            "강조사항",
            "계속기업 관련 중요한 불확실성에 대해 주석 XX에 기술되어 있습니다. "
            "계속기업으로서의 존속능력에 유의적 의문을 제기할 만한 중요한 불확실성이 존재함을 나타냅니다.",
            "경영진의 책임",
            _RESP,
        ),
        opinion_code="unqualified",
    )
    assert result.going_concern == 1
    assert result.source == "eom"


def test_other_matter_qualified_grounds_prior_year_is_zero() -> None:
    """기타사항에 한정의견근거·MU 전기 인용이 있어도 1이 되지 않는다."""
    result = extract_going_concern(
        _html(
            "감사의견",
            "적정입니다.",
            "기타사항",
            "전기 감사보고서의 한정의견 근거에는 "
            "계속기업으로서의 존속능력에 유의적 의문을 제기할 수 있는 중요한 불확실성의 존재가 기술되어 있습니다.",
            "재무제표에 대한 경영진과 지배기구의 책임",
            _RESP,
        ),
        opinion_code="unqualified",
    )
    assert result.going_concern == 0
