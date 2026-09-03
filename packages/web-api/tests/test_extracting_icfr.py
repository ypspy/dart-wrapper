"""내부회계 감사·검토 의견 추출 테스트."""

from app.extracting.icfr import extract_icfr


def _html(*paragraphs: str) -> str:
    body = "".join(f"<p>{text}</p>" for text in paragraphs)
    return f"<html><body>{body}</body></html>"


def test_missing_leaf_is_skipped() -> None:
    """내부회계 HTML이 없으면 skipped이고 engagement를 채우지 않는다."""
    opinion = _html("우리는 또한 내부회계관리제도를 감사하였으며 적정의견을 표명하였습니다.")
    result = extract_icfr(opinion_html=opinion, icfr_html=None, fs_scope="separate")
    assert result.status == "skipped"
    assert result.engagement is None
    assert result.opinion_code is None


def test_placeholder_leaf_is_none() -> None:
    """leaf는 있으나 서식이 아니면 none이다."""
    result = extract_icfr(
        opinion_html=_html("재무제표 감사의견 적정"),
        icfr_html=_html("해당사항 없음"),
        fs_scope="separate",
    )
    assert result.status == "ok"
    assert result.engagement == "none"
    assert result.opinion_code is None


def test_fs_letter_separate_audit_phrase() -> None:
    """별도 의견서 추가 문단이면 감사이고, 제목 적정은 unqualified다."""
    opinion = _html(
        "우리는 또한 회계감사기준에 따라 내부회계관리제도를 감사하였으며 "
        "2024년 3월 6일자 감사보고서에서 적정의견을 표명하였습니다."
    )
    icfr = _html(
        "독립된 감사인의 내부회계관리제도 감사보고서",
        "내부회계관리제도에 대한 감사의견",
        "효과적으로 설계 및 운영되고 있습니다.",
    )
    result = extract_icfr(opinion_html=opinion, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "audit"
    assert result.opinion_code == "unqualified"
    assert result.opinion_raw == "내부회계관리제도에대한감사의견"
    assert result.status == "ok"


def test_consolidated_phrase_does_not_mark_separate_row() -> None:
    """연결…를감사하였은 별도 행을 audit으로 만들지 않는다."""
    opinion = _html("우리는 연결내부회계관리제도를 감사하였으며 적정의견을 표명하였습니다.")
    icfr = _html("해당사항 없음")
    result = extract_icfr(opinion_html=opinion, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "none"


def test_consolidated_fs_letter_and_heading() -> None:
    """연결 행은 연결 문단·연결 제목으로 audit unqualified다."""
    opinion = _html(
        "우리는 또한 회계감사기준에 따라 연결내부회계관리제도를 감사하였으며 "
        "적정의견을 표명하였습니다."
    )
    icfr = _html(
        "독립된 감사인의 연결내부회계관리제도 감사보고서",
        "연결내부회계관리제도에 대한 감사의견",
    )
    result = extract_icfr(opinion_html=opinion, icfr_html=icfr, fs_scope="consolidated")
    assert result.engagement == "audit"
    assert result.opinion_code == "unqualified"


def test_audit_adverse_heading_not_material_weakness() -> None:
    """부적정 제목이면 근거의 취약점 서술이 material_weakness가 되지 않는다."""
    icfr = _html(
        "독립된 감사인의 내부회계관리제도 감사보고서",
        "내부회계관리제도에 대한 부적정의견",
        "중요한 취약점의 영향 때문에 효과적으로 설계 및 운영되고 있지 않습니다.",
        "내부회계관리제도 부적정의견근거",
        "다음의 중요한 취약점이 식별되었으며",
    )
    result = extract_icfr(opinion_html=None, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "audit"
    assert result.opinion_code == "adverse"
    assert result.opinion_raw == "내부회계관리제도에대한부적정의견"


def test_audit_disclaimer_heading() -> None:
    """의견거절 제목이면 disclaimer다."""
    icfr = _html(
        "독립된 감사인의 내부회계관리제도 감사보고서",
        "내부회계관리제도에 대한 의견거절",
        "의견을 표명하지 않습니다.",
        "그러나 중요한 취약점이 식별되었습니다.",
    )
    result = extract_icfr(opinion_html=None, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "audit"
    assert result.opinion_code == "disclaimer"


def test_review_clean_not_material_weakness() -> None:
    """발견되지 아니하였은 취약점이 아니다."""
    icfr = _html(
        "외부감사인의 내부회계관리제도 검토보고서",
        "우리는 내부회계관리제도 검토기준에 따라 검토를 실시하였습니다.",
        "중요한 취약점이 발견되지 아니하였습니다.",
    )
    result = extract_icfr(opinion_html=None, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "review"
    assert result.opinion_code == "unqualified"
    assert result.opinion_raw == "boilerplate_unqualified"


def test_review_qualified() -> None:
    """미치는영향을제외하고는 한정이다."""
    icfr = _html(
        "외부감사인의 내부회계관리제도 검토보고서",
        "검토기준에 따라 검토를 실시하였습니다.",
        "절차를 수행하였을 경우 발견되었을 사항이 미치는 영향을 제외하고는 "
        "작성되지 않았다고 판단하게 하는 점이 발견되지 아니하였습니다.",
    )
    result = extract_icfr(opinion_html=None, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "review"
    assert result.opinion_code == "qualified"
    assert result.opinion_raw == "미치는영향을제외하고는"


def test_review_disclaimer() -> None:
    """검토의견을표명하지는 거절이다."""
    icfr = _html(
        "외부감사인의 내부회계관리제도 검토보고서",
        "검토의견을 표명하지 아니합니다.",
    )
    result = extract_icfr(opinion_html=None, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "review"
    assert result.opinion_code == "disclaimer"


def test_review_material_weakness() -> None:
    """중요한취약점이발견되었은 취약점이다."""
    icfr = _html(
        "외부감사인의 내부회계관리제도 검토보고서",
        "검토기준에 따라 검토를 실시하였습니다.",
        "다음과 같은 중요한 취약점이 발견되었습니다.",
    )
    result = extract_icfr(opinion_html=None, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "review"
    assert result.opinion_code == "material_weakness"
    assert result.opinion_raw == "중요한취약점이발견되었"
