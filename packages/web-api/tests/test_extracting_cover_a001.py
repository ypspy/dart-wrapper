"""표지·실시내용 헤더·A001 표·본문 감사인 추출 테스트."""

from pathlib import Path

from app.extracting.a001_section import extract_a001_current_audit
from app.extracting.activity_header import extract_activity_header
from app.extracting.auditor_body import extract_body_auditor
from app.extracting.cover import extract_cover_auditor, extract_cover_period
from app.extracting.text import compact

_COVER_HTML = """
<html><body>
<table>
<tr><td>감사보고서</td></tr>
</table>
<table>
<tr><td>제51기</td><td>2019.01.01부터 2019.12.31까지</td></tr>
</table>
<table>
<tr><td>삼일회계법인</td></tr>
</table>
</body></html>
"""

_ACTIVITY_HTML = """
<html><body>
<table>
<tr>
  <td>회사명</td><td>삼성전자주식회사</td>
  <td>결산월</td><td>12월</td>
</tr>
</table>
<table>
<tr><td>투입 인원수</td><td>10</td><td>20</td></tr>
<tr><td>감사</td><td>100</td><td>200</td></tr>
</table>
</body></html>
"""

_A001_HTML = """
<html><body>
<table>
<tr><td>구분</td><td>당기</td><td>전기</td></tr>
<tr><td>감사인</td><td>삼일회계법인</td><td>안진회계법인</td></tr>
<tr><td>감사의견</td><td>적정</td><td>한정</td></tr>
</table>
</body></html>
"""

_AUDITOR_NAMES_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "extracting" / "data" / "auditor_names.txt"
)


def test_cover_period_and_auditor_from_html() -> None:
    """표지 표에서 기 뒤 당기와 회계법인 td를 읽는다."""
    period = extract_cover_period(_COVER_HTML)
    assert period.status == "ok"
    assert period.code is None
    assert period.raw == "2019.01.01부터2019.12.31까지"

    auditor = extract_cover_auditor(_COVER_HTML)
    assert auditor.status == "ok"
    assert auditor.code is None
    assert auditor.raw == "삼일회계법인"


def test_cover_period_prefers_ideographic_qi() -> None:
    """기보다 期가 있으면 期 뒤 구간을 쓴다."""
    html = "<table><tr><td>第51期2019.01.01～2019.12.31</td></tr></table>"
    result = extract_cover_period(html)
    assert result.status == "ok"
    assert result.raw == "2019.01.01～2019.12.31"


def test_cover_period_not_found_without_marker() -> None:
    """기·期가 없으면 not_found이다."""
    result = extract_cover_period("<table><tr><td>감사보고서 2019</td></tr></table>")
    assert result.status == "not_found"
    assert result.raw is None
    assert result.code is None


def test_cover_auditor_from_p_when_no_td() -> None:
    """회계법인 문구가 p에만 있으면 그 텍스트를 쓴다."""
    html = "<html><body><p>한영회계법인</p></body></html>"
    result = extract_cover_auditor(html)
    assert result.status == "ok"
    assert result.raw == "한영회계법인"


def test_cover_auditor_not_found() -> None:
    """회계법인·감사반이 없으면 not_found이다."""
    result = extract_cover_auditor("<p>감사보고서</p>")
    assert result.status == "not_found"
    assert result.raw is None


def test_activity_header_company_and_year_end() -> None:
    """실시내용 상단 회사명·결산월 라벨 행을 읽고 투입시간 표는 무시한다."""
    corp_name, year_end = extract_activity_header(_ACTIVITY_HTML)
    assert corp_name == "삼성전자주식회사"
    assert year_end == "12월"


def test_activity_header_uses_fiscal_year_label() -> None:
    """결산월이 없으면 사업연도 칸을 결산 헤더로 쓴다."""
    html = """
    <table>
    <tr><td>회사명</td><td>LG전자</td></tr>
    <tr><td>사업연도</td><td>2019.01.01 ~ 2019.12.31</td></tr>
    </table>
    """
    corp_name, year_end = extract_activity_header(html)
    assert corp_name == "LG전자"
    assert year_end == "2019.01.01~2019.12.31"


def test_activity_header_missing_labels() -> None:
    """라벨이 없으면 (None, None)이다."""
    assert extract_activity_header("<table><tr><td>감사</td></tr></table>") == (
        None,
        None,
    )


def test_a001_current_period_opinion_and_auditor() -> None:
    """A001 표의 당기 칸에서 적정 의견과 삼일 감사인을 읽는다."""
    opinion, auditor = extract_a001_current_audit(_A001_HTML)
    assert opinion.status == "ok"
    assert opinion.code is None
    assert opinion.raw == "적정"
    assert auditor.status == "ok"
    assert auditor.code is None
    assert auditor.raw == "삼일회계법인"


def test_a001_uses_first_nth_period_column() -> None:
    """당기 헤더가 없으면 첫 제N기 열을 당기로 본다."""
    html = """
    <table>
    <tr><td>구분</td><td>제50기</td><td>제49기</td></tr>
    <tr><td>감사인</td><td>삼일회계법인</td><td>안진회계법인</td></tr>
    <tr><td>감사의견</td><td>적정</td><td>한정</td></tr>
    </table>
    """
    opinion, auditor = extract_a001_current_audit(html)
    assert opinion.raw == "적정"
    assert auditor.raw == "삼일회계법인"


def test_a001_empty_cell_is_not_found() -> None:
    """당기 칸이 비면 boilerplate 없이 not_found이다."""
    html = """
    <table>
    <tr><td>구분</td><td>당기</td></tr>
    <tr><td>감사인</td><td></td></tr>
    <tr><td>감사의견</td><td></td></tr>
    </table>
    """
    opinion, auditor = extract_a001_current_audit(html)
    assert opinion.status == "not_found"
    assert opinion.raw is None
    assert opinion.code is None
    assert auditor.status == "not_found"
    assert auditor.raw is None


def test_a001_not_found_without_period_table() -> None:
    """당기·제N기 표가 없으면 둘 다 not_found이다."""
    opinion, auditor = extract_a001_current_audit("<p>본문만</p>")
    assert opinion.status == "not_found"
    assert auditor.status == "not_found"


def test_body_auditor_picks_name_at_latest_position() -> None:
    """compact 본문에서 가장 뒤에 나온 사전 이름을 고른다."""
    result = extract_body_auditor(
        "머리 안진 회계 법인 본문 삼일회계법인 서명",
        ["삼일회계법인", "안진회계법인"],
    )
    assert result.status == "ok"
    assert result.code is None
    assert result.raw == "삼일회계법인"


def test_body_auditor_not_found() -> None:
    """사전 이름이 없으면 not_found이다."""
    result = extract_body_auditor("의견 본문", ["삼일회계법인"])
    assert result.status == "not_found"
    assert result.raw is None
    assert result.code is None


def test_body_auditor_uses_names_file_head() -> None:
    """auditor_names.txt 앞줄 이름으로 본문 매칭이 된다."""
    lines = _AUDITOR_NAMES_PATH.read_text(encoding="utf-8").splitlines()
    names = [compact(line) for line in lines[:3] if compact(line)]
    assert names[0].startswith("신승회계법인")
    result = extract_body_auditor(f"본문 {names[0]} 끝", names)
    assert result.status == "ok"
    assert result.raw == names[0]
