"""FS6-SUB: 다단 헤더·묶음 행·그룹 구분행·제목 표·세로형 개요 표 (합성 표본, 실제 회사명 아님)."""

import pytest

from research.extracting.subsidiaries import extract_subsidiaries

_A001_OK = """
<p>계열회사의 현황</p>
<table>
<tr><td>회사명</td><td>관계</td></tr>
<tr><td>갑</td><td>종속회사</td></tr>
</table>
"""


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


# S4·S5·S6: 원문 #54 형태. 한 행이 여러 회사를 묶음(「… 외 57개 (주2)」).
BUNDLED = """
<table border="1">
<tr><th>종속기업명</th><th>소재지</th><th>지분율</th></tr>
<tr><td>가상H㈜ (주2, 3)</td><td>대한민국</td><td>33.40%</td></tr>
<tr><td>{name}</td><td>파나마</td><td>100.00%</td></tr>
<tr><td>가상J Ltd.</td><td>홍콩</td><td>100.00%</td></tr>
</table>
"""


def test_s4_bundled_row_is_ambiguous() -> None:
    result = _run(_notes(BUNDLED.format(name="가상I Shipholding S.A. 외 57개 (주2)")))
    assert (result.count, result.status, result.source) == (None, "ambiguous", "notes")


def test_s5_bundled_row_does_not_fall_back_to_a001() -> None:
    html = _notes(BUNDLED.format(name="가상I Shipholding S.A. 외 57개 (주2)"))
    result = _run(html, a001=_A001_OK)
    assert (result.count, result.status, result.source) == (None, "ambiguous", "notes")


@pytest.mark.parametrize("name", ["가상K㈜ 외 3개사", "가상L 투자조합 등 2개"])
def test_s6_bundled_row_variants_are_ambiguous(name: str) -> None:
    result = _run(_notes(BUNDLED.format(name=name)))
    assert (result.count, result.status) == (None, "ambiguous")


def test_s17_name_with_oe_but_no_bundle_is_counted() -> None:
    """「해외 2호」처럼 개수 표기가 아닌 이름은 묶음 행이 아니다."""
    result = _run(_notes(BUNDLED.format(name="가상해외 2호 투자조합")))
    assert (result.count, result.status) == (3, "ok")


# S7: 원문 20170323000219 형태. 3줄 헤더 뒤 전 칸 colspan 그룹 구분행 [국내]/[해외].
GROUP_ROWS_BRACKET = """
<table border="1">
<tr><th rowspan="2">종속기업명</th><th rowspan="2">업 종</th><th colspan="2">지분율(%)</th></tr>
<tr><th>지배기업 보유지분</th><th>합 계</th></tr>
<tr><td colspan="4">[국내]</td></tr>
<tr><td>가상M㈜</td><td>건설</td><td>52.80</td><td>52.80</td></tr>
<tr><td>가상N㈜</td><td>판매</td><td>95.30</td><td>95.30</td></tr>
<tr><td colspan="4">[해외]</td></tr>
<tr><td>가상O Co., Ltd.</td><td>제조</td><td>100.00</td><td>100.00</td></tr>
</table>
"""


def test_s7_bracket_group_rows_are_not_counted() -> None:
    result = _run(_notes(GROUP_ROWS_BRACKET))
    assert (result.count, result.status) == (3, "ok")


# S8: 원문 20170330001518 형태. 「갑은행의 종속기업」 행(다른 칸 공란).
GROUP_ROWS_PARENT = """
<table border="1">
<tr><th>회사명</th><th>국가</th><th>주요사업</th><th>지분율(%)</th></tr>
<tr><td>가상은행의 종속기업</td><td></td><td></td><td></td></tr>
<tr><td>가상P유한공사</td><td>중국</td><td>은행업</td><td>100.0</td></tr>
<tr><td>가상Q 신탁</td><td>대한민국</td><td>집합투자기구</td><td>100.0</td></tr>
<tr><td>가상R Inc.의 종속기업</td><td></td><td></td><td></td></tr>
<tr><td>가상S Corp.</td><td>미국</td><td>특수목적회사</td><td>100.0</td></tr>
</table>
"""


def test_s8_parent_group_rows_are_not_counted() -> None:
    result = _run(_notes(GROUP_ROWS_PARENT))
    assert (result.count, result.status) == (3, "ok")


def test_s9_unknown_name_only_row_is_ambiguous() -> None:
    html = _notes(GROUP_ROWS_PARENT.replace("가상은행의 종속기업", "비고: 아래 회사는 당기 신규"))
    result = _run(html)
    assert (result.count, result.status) == (None, "ambiguous")


# S10: 둘째 헤더 줄에 rowspan이 없어 이름 칸이 빈 경우(구조를 확정할 수 없음).
TWO_ROW_HEADER_NO_ROWSPAN = """
<table border="1">
<tr><th>종속기업명</th><th>소재지</th><th colspan="2">지분율(%)</th></tr>
<tr><th></th><th></th><th>당기말</th><th>전기말</th></tr>
<tr><td>가상T㈜</td><td>대한민국</td><td>100.00</td><td>100.00</td></tr>
</table>
"""


def test_s10_empty_name_cell_is_ambiguous() -> None:
    result = _run(_notes(TWO_ROW_HEADER_NO_ROWSPAN))
    assert (result.count, result.status) == (None, "ambiguous")


# S11: 원문 20170323000219 주석 첫머리 형태. 「…와 그 종속기업」 제목 표가 먼저 나온다.
TITLE_TABLE = """
<table><tr><td>가상주식회사와 그 종속기업</td></tr><tr><td></td></tr>
<tr><td>2016년 12월 31일 현재</td></tr></table>
"""


def test_s11_title_table_is_skipped() -> None:
    html = f"<html><body>{TITLE_TABLE}<p>(2) 종속기업의 현황</p>{TWO_ROW_HEADER}</body></html>"
    result = _run(html)
    assert (result.count, result.status) == (3, "ok")


# S12: 원문 20170208000026 형태. 구분/내용 세로형 개요 표(회사명이 본문 행 라벨).
KEY_VALUE = """
<table border="1">
<tr><th>구 분</th><th>내 용</th></tr>
<tr><td>회 사 명</td><td>가상U 주식회사</td></tr>
<tr><td>설립연월일</td><td>2015년 12월 04일</td></tr>
<tr><td>본점소재지</td><td>서울특별시</td></tr>
</table>
"""


def test_s12_key_value_overview_table_is_ambiguous() -> None:
    html = _notes(KEY_VALUE, heading="1-1. 지배기업 및 종속기업의 개요")
    result = _run(html)
    assert (result.count, result.status) == (None, "ambiguous")


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


# --- PR16-K: 구분 열·A001에서 비종속 행을 R4–R6 전에 건너뛰기 (회귀 H1·H6·H9·H10) ---


def test_k1_kind_column_empty_total_row_is_skipped() -> None:
    """구분 열 + 빈 이름 계 행: 비종속 행을 건너뛰어 count=2 (notes)."""
    html = (
        "<html><body><p>종속기업 및 관계기업 현황</p><table border='1'>"
        "<tr><td>구분</td><td>회사명</td><td>지분율</td></tr>"
        "<tr><td>종속기업</td><td>가상A㈜</td><td>100</td></tr>"
        "<tr><td>종속기업</td><td>가상B㈜</td><td>60</td></tr>"
        "<tr><td>관계기업</td><td>가상C㈜</td><td>30</td></tr>"
        "<tr><td>계</td><td></td><td></td></tr></table></body></html>"
    )
    result = _run(html)
    assert (result.count, result.status, result.source) == (2, "ok", "notes")


def test_k2_kind_column_colspan_footnote_is_skipped() -> None:
    """구분 열 + colspan 각주 행: 비종속 행을 건너뛰어 count=2 (notes)."""
    html = (
        "<html><body><p>종속기업 및 관계기업 현황</p><table border='1'>"
        "<tr><td>구분</td><td>회사명</td><td>지분율</td></tr>"
        "<tr><td>종속기업</td><td>가상A㈜</td><td>100</td></tr>"
        "<tr><td>종속기업</td><td>가상B㈜</td><td>60</td></tr>"
        "<tr><td>관계기업</td><td>가상C㈜</td><td>30</td></tr>"
        "<tr><td colspan='3'>(주1) 당기 중 신규 설립하였습니다.</td></tr>"
        "</table></body></html>"
    )
    result = _run(html)
    assert (result.count, result.status, result.source) == (2, "ok", "notes")


def test_k3_a001_empty_total_row_is_skipped() -> None:
    """A001 관계 열 + 빈 이름 계 행: notes 없이 a001 경로, count=2."""
    a001 = (
        "<html><body><p>계열회사의 현황</p><table border='1'>"
        "<tr><td>회사명</td><td>관계</td></tr>"
        "<tr><td>가상A㈜</td><td>종속회사</td></tr>"
        "<tr><td>가상B㈜</td><td>종속회사</td></tr>"
        "<tr><td>가상C㈜</td><td>관계회사</td></tr>"
        "<tr><td></td><td>계</td></tr></table></body></html>"
    )
    result = extract_subsidiaries(fs_scope="consolidated", notes_html="", a001_html=a001)
    assert (result.count, result.status, result.source) == (2, "ok", "a001")


def test_k4_a001_colspan_footnote_is_skipped() -> None:
    """A001 관계 열 + colspan 각주 행: notes 없이 a001 경로, count=2."""
    a001 = (
        "<html><body><p>계열회사의 현황</p><table border='1'>"
        "<tr><td>회사명</td><td>관계</td></tr>"
        "<tr><td>가상A㈜</td><td>종속회사</td></tr>"
        "<tr><td>가상B㈜</td><td>종속회사</td></tr>"
        "<tr><td>가상C㈜</td><td>관계회사</td></tr>"
        "<tr><td colspan='2'>(주) 상장사 표시</td></tr></table></body></html>"
    )
    result = extract_subsidiaries(fs_scope="consolidated", notes_html="", a001_html=a001)
    assert (result.count, result.status, result.source) == (2, "ok", "a001")
