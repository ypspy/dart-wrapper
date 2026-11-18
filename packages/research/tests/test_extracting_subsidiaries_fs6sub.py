"""FS6-SUB: 다단 헤더·묶음 행·그룹 구분행·제목 표·세로형 개요 표 (합성 표본, 실제 회사명 아님)."""

import pytest

from research.extracting.subsidiaries import extract_subsidiaries


def _notes(table: str, heading: str = "(2) 당기말 현재 종속기업의 현황은 다음과 같습니다.") -> str:
    return f"<html><body><p>{heading}</p>{table}</body></html>"


def _run(html: str, a001: str | None = None):
    return extract_subsidiaries(fs_scope="consolidated", notes_html=html, a001_html=a001)


# S1: 원문 #52·#55·#56 형태. 이름 열 rowspan=2, 지분율 colspan=2 아래 당기/전기.
TWO_ROW_HEADER = """
<table border="1">
<tr><th rowspan="2">종속기업명</th><th rowspan="2">소재지</th><th colspan="2">지분율(%)</th></tr>
<tr><th>2016.12.31</th><th>2015.12.31</th></tr>
<tr><td>가상A㈜</td><td>대한민국</td><td>100.00</td><td>100.00</td></tr>
<tr><td>가상B Ltd.</td><td>중국</td><td>80.00</td><td>80.00</td></tr>
<tr><td>가상C Inc.</td><td>미국</td><td>51.00</td><td>-</td></tr>
</table>
"""


def test_s1_two_row_header_continuation_is_not_counted() -> None:
    result = _run(_notes(TWO_ROW_HEADER))
    assert (result.count, result.status, result.source) == (3, "ok", "notes")


# S2: 원문 20160405002471 형태. 표 안 단위 행 + 헤더 3줄. 원문 셋째 줄은 「합 계」라 기존 합계 제외로
# 우연히 빠지므로, 다단 헤더 제거를 확인하려고 「계」로 바꿨다.
THREE_ROW_HEADER_WITH_UNIT = """
<table border="1">
<tr><td colspan="5">(단위:%)</td></tr>
<tr><th rowspan="3">종속기업명</th><th rowspan="3">소재지</th><th colspan="3">투자지분비율</th></tr>
<tr><th colspan="3">당기말</th></tr>
<tr><th>지배기업</th><th>종속기업</th><th>계</th></tr>
<tr><td>가상D㈜</td><td>대한민국</td><td>100.00</td><td>-</td><td>100.00</td></tr>
<tr><td>가상E S.A.</td><td>파나마 등</td><td>-</td><td>-</td><td>-</td></tr>
</table>
"""


def test_s2_three_row_header_after_unit_row() -> None:
    result = _run(_notes(THREE_ROW_HEADER_WITH_UNIT))
    assert (result.count, result.status) == (2, "ok")


# S3: 원문 #53·#57 형태. 회사명 rowspan=2, 당기말/전기말 colspan=2 아래 투자주식수/지분율·지배기업/종속기업/계.
TWO_ROW_HEADER_SUBCOLUMNS = """
<table border="1">
<tr><th rowspan="2">회사명</th><th colspan="3">투자주식수</th><th rowspan="2">지분율</th></tr>
<tr><th>지배기업</th><th>종속기업</th><th>계</th></tr>
<tr><td>가상F㈜</td><td>1,000</td><td>-</td><td>1,000</td><td>100%</td></tr>
<tr><td>가상G㈜</td><td>-</td><td>500</td><td>500</td><td>50%</td></tr>
</table>
"""


def test_s3_two_row_header_with_subcolumns() -> None:
    result = _run(_notes(TWO_ROW_HEADER_SUBCOLUMNS))
    assert (result.count, result.status) == (2, "ok")


# S11: 원문 20170323000219 주석 첫머리 형태. 「…와 그 종속기업」 제목 표가 먼저 나온다.
TITLE_TABLE = """
<table><tr><td>가상주식회사와 그 종속기업</td></tr><tr><td></td></tr>
<tr><td>2016년 12월 31일 현재</td></tr></table>
"""


def test_s11_title_table_is_skipped() -> None:
    html = f"<html><body>{TITLE_TABLE}<p>(2) 종속기업의 현황</p>{TWO_ROW_HEADER}</body></html>"
    result = _run(html)
    assert (result.count, result.status) == (3, "ok")


# S13: 원문 20160412001705(전체 문서 입력) 형태. 헤더 힌트 없는 표(서명란 등)는 세지 않는다.
def test_s13_headerless_table_is_not_counted() -> None:
    html = _notes(
        "<table><tr><td></td><td>가상회계법인</td></tr><tr><td></td><td>대표이사 가상</td></tr>"
        "<tr><td></td><td>2016년 4월 1일</td></tr></table>",
        heading="회사와 그 종속기업의 연결재무제표는 공정하게 표시하고 있습니다.",
    )
    result = _run(html)
    assert (result.count, result.status) == (None, "not_found")


# S14: 원문 20160429000416·20161129000586 형태. 이름 열 헤더 칸 전체가 「연결대상종속기업」「종속기업」.
@pytest.mark.parametrize("label", ["연결대상종속기업", "종속기업"])
def test_s14_exact_subsidiary_header_cell_still_counts(label: str) -> None:
    html = _notes(
        f"<table border='1'><tr><th>{label}</th><th>소재지</th><th>결산일</th></tr>"
        "<tr><td>가상V㈜</td><td>한국</td><td>12/31</td></tr>"
        "<tr><td>가상W㈜</td><td>한국</td><td>12/31</td></tr></table>"
    )
    result = _run(html)
    assert (result.count, result.status) == (2, "ok")


# S16: 구분 열 rowspan 다단 헤더 + 분류값. 구분 칸 복제 행도 헤더로 본다.
def test_s16_kind_column_rowspan_header() -> None:
    html = _notes(
        "<table border='1'><tr><th rowspan='2'>구분</th><th rowspan='2'>회사명</th>"
        "<th colspan='2'>지분율</th></tr><tr><th>당기</th><th>전기</th></tr>"
        "<tr><td>종속기업</td><td>가상X㈜</td><td>100%</td><td>100%</td></tr>"
        "<tr><td>관계기업</td><td>가상Y㈜</td><td>30%</td><td>30%</td></tr></table>",
        heading="종속기업 및 관계기업 현황",
    )
    result = _run(html)
    assert (result.count, result.status) == (1, "ok")
