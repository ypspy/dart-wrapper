"""추출기는 기간을 바꾸지 않고, 신호만 단일 기간 합계를 읽는다."""

from __future__ import annotations

from bs4 import BeautifulSoup

from research.extracting.activity_hours import extract_hours
from research.extracting.constants import EXTRACTOR_VERSION
from research.extracting.hours_period import is_single_period_hours
from research.gold.scoring import _hours_keys
from research.reviewing.candidates import numeric_candidates
from test_reviewing_candidates import view

_LEGACY_SINGLE_PERIOD = """
<html><body>
<table>
<tr>
  <td colspan="2">구분</td>
  <td>품질관리검토자</td>
  <td>담당이사</td>
  <td>등록공인회계사</td>
  <td>수습공인회계사</td>
  <td>전산감사ㆍ세무ㆍ가치평가 등 전문가</td>
  <td>합계</td>
</tr>
<tr>
  <td colspan="2">투입 인원수</td>
  <td>1</td><td>2</td><td>3</td><td>4</td><td>5</td><td>15</td>
</tr>
<tr>
  <td rowspan="3">투입시간</td>
  <td>분·반기검토</td>
  <td>1</td><td>2</td><td>3</td><td>4</td><td>5</td><td>15</td>
</tr>
<tr>
  <td>감사</td>
  <td>10</td><td>20</td><td>30</td><td>4</td><td>5</td><td>100</td>
</tr>
<tr>
  <td>합계</td>
  <td>11</td><td>22</td><td>33</td><td>8</td><td>10</td><td>115</td>
</tr>
</table>
</body></html>
"""

_UNLABELED_COLSPAN = """
<html><body>
<table>
<tr>
  <td colspan="2">구분</td>
  <td colspan="2">품질관리검토자</td>
  <td colspan="2">담당이사</td>
  <td colspan="2">등록공인회계사</td>
  <td colspan="2">수습공인회계사</td>
  <td colspan="2">전산감사ㆍ세무ㆍ가치평가 등 전문가</td>
  <td colspan="2">합계</td>
</tr>
<tr>
  <td colspan="2">투입 인원수</td>
  <td>1</td><td>1</td>
  <td>2</td><td>2</td>
  <td>3</td><td>3</td>
  <td>4</td><td>4</td>
  <td>5</td><td>5</td>
  <td>15</td><td>15</td>
</tr>
<tr>
  <td rowspan="3">투입시간</td>
  <td>분·반기검토</td>
  <td>1</td><td>1</td>
  <td>2</td><td>2</td>
  <td>3</td><td>3</td>
  <td>4</td><td>4</td>
  <td>5</td><td>5</td>
  <td>15</td><td>15</td>
</tr>
<tr>
  <td>감사</td>
  <td>10</td><td>10</td>
  <td>20</td><td>20</td>
  <td>30</td><td>30</td>
  <td>4</td><td>4</td>
  <td>5</td><td>5</td>
  <td>100</td><td>90</td>
</tr>
<tr>
  <td>합계</td>
  <td>11</td><td>11</td>
  <td>22</td><td>22</td>
  <td>33</td><td>33</td>
  <td>8</td><td>8</td>
  <td>10</td><td>10</td>
  <td>115</td><td>105</td>
</tr>
</table>
</body></html>
"""


def test_legacy_single_period_html_is_unknown_and_not_missing() -> None:
    """옛 서식 6열은 추출 뒤에도 전부 unknown이고, 합계 100은 missing이 아니다."""
    assert (
        EXTRACTOR_VERSION == "audit_opinion.v19"
    ), "버전이 오르면 단일 기간 규칙을 추출 단계로 옮길지 다시 판단하라."
    cells, status = extract_hours(_LEGACY_SINGLE_PERIOD)
    assert status == "ok"
    assert len(cells) == 24
    assert {cell["period"] for cell in cells} == {"unknown"}
    assert {cell["period_raw"] for cell in cells} == {""}
    keys = [(cell["role"], cell["role_raw"], cell["metric"]) for cell in cells]
    assert len(keys) == len(set(keys))
    total = next(cell for cell in cells if cell["role"] == "total" and cell["metric"] == "audit")
    assert total["value"] == 100
    fact = view(1, hours=cells, hours_status="ok")
    candidates, summary = numeric_candidates([fact], set())
    assert not any(item.signal == "hours_total_missing" for item in candidates)
    assert not any(row.key == "hours_total_duplicate" for row in summary)


def test_unlabeled_colspan_pair_stays_missing() -> None:
    """당기/전기 소제목 없는 colspan 2열은 unknown으로 남고 missing이다.

    의도된 한계, README 한계 1·2 참조.
    """
    assert (
        EXTRACTOR_VERSION == "audit_opinion.v19"
    ), "버전이 오르면 단일 기간 규칙을 추출 단계로 옮길지 다시 판단하라."
    cells, status = extract_hours(_UNLABELED_COLSPAN)
    assert status == "ok"
    assert len(cells) == 48
    assert {cell["period"] for cell in cells} == {"unknown"}
    assert {cell["period_raw"] for cell in cells} == {""}
    keys = [(cell["role"], cell["role_raw"], cell["metric"]) for cell in cells]
    assert len(keys) == 48
    assert len(set(keys)) == 24
    fact = view(2, hours=cells, hours_status="ok")
    candidates, summary = numeric_candidates([fact], set())
    assert [(item.signal, item.raw_value) for item in candidates] == [("hours_total_missing", "")]
    assert not any(row.key == "hours_total_duplicate" for row in summary)


def _append_column(html: str, header: str | None, values: list[str]) -> str:
    """옛 서식 데이터 행 끝에 열을 붙인다. header가 None이면 헤더 칸은 넣지 않는다."""
    soup = BeautifulSoup(html, "lxml")
    rows = soup.find_all("tr")
    if header is not None:
        header_cell = soup.new_tag("td")
        header_cell.string = header
        rows[0].append(header_cell)
    for row, value in zip(rows[1:], values, strict=True):
        cell = soup.new_tag("td")
        cell.string = value
        row.append(cell)
    return str(soup)


def _without_header(html: str) -> str:
    """첫 헤더 행을 뺀다."""
    soup = BeautifulSoup(html, "lxml")
    header = soup.find("tr")
    assert header is not None
    header.decompose()
    return str(soup)


def _read(
    html: str, index: int
) -> tuple[list[dict[str, object]], bool, tuple[object, object], list[str], bool]:
    """추출 칸, 가드, 골드 키, hours 신호, duplicate skip 여부."""
    assert (
        EXTRACTOR_VERSION == "audit_opinion.v19"
    ), "버전이 오르면 단일 기간 규칙을 추출 단계로 옮길지 다시 판단하라."
    cells, status = extract_hours(html)
    assert status == "ok"
    fact = view(index, hours=cells, hours_status="ok")
    candidates, summary = numeric_candidates([fact], set())
    signals = [item.signal for item in candidates if item.bundle == "hours"]
    duplicate = any(row.section == "skip" and row.key == "hours_total_duplicate" for row in summary)
    return cells, is_single_period_hours(cells), _hours_keys(cells), signals, duplicate


def _assert_missing(html: str, index: int) -> list[dict[str, object]]:
    """가드 거짓, 골드 키 (None, None), missing 1건, duplicate 없음."""
    cells, guard, keys, signals, duplicate = _read(html, index)
    assert guard is False
    assert keys == (None, None)
    assert signals == ["hours_total_missing"]
    assert duplicate is False
    return cells


_EXTRA_VALUES = ["1", "1", "90", "1"]


def test_n1_blank_header_column_is_missing() -> None:
    """옛 서식에 헤더가 빈 추가 열(감사 90)이 있으면 missing이다."""
    html = _append_column(_LEGACY_SINGLE_PERIOD, "", _EXTRA_VALUES)
    cells = _assert_missing(html, 11)
    extra = next(cell for cell in cells if cell["role"] == "other" and cell["metric"] == "audit")
    assert extra["role_raw"] == ""
    assert extra["unmapped"] is True
    assert extra["value"] == 90
    total = next(cell for cell in cells if cell["role"] == "total" and cell["metric"] == "audit")
    assert total["value"] == 100


def test_n2_fiscal_period_header_column_is_missing() -> None:
    """옛 서식에 「제47기」 한 열이 있으면 role이 other라 missing이다.

    unmapped는 False다. 가드는 unmapped가 아니라 role로 거절한다.
    """
    html = _append_column(_LEGACY_SINGLE_PERIOD, "제47기", _EXTRA_VALUES)
    cells = _assert_missing(html, 12)
    extra = next(cell for cell in cells if cell["metric"] == "audit" and cell["value"] == 90)
    assert extra["role"] == "other"
    assert extra["role_raw"] == "제47기"
    assert extra["unmapped"] is False


def test_n3_unattached_value_column_is_missing() -> None:
    """헤더 칸 없이 남는 값 열(감사 90)이 있으면 missing이다."""
    html = _append_column(_LEGACY_SINGLE_PERIOD, None, _EXTRA_VALUES)
    cells = _assert_missing(html, 13)
    extra = next(cell for cell in cells if cell["role"] == "other" and cell["metric"] == "audit")
    assert extra["role_raw"] == ""
    assert extra["unmapped"] is True
    assert extra["value"] == 90


def test_n4_two_total_headers_are_missing() -> None:
    """「합계」100/15와 「합 계」90/14가 같이 있으면 missing이다."""
    html = _append_column(_LEGACY_SINGLE_PERIOD, "합 계", ["14", "1", "90", "1"])
    cells = _assert_missing(html, 14)
    audits = {
        (cell["role_raw"], cell["value"])
        for cell in cells
        if cell["role"] == "total" and cell["metric"] == "audit"
    }
    heads = {
        (cell["role_raw"], cell["value"])
        for cell in cells
        if cell["role"] == "total" and cell["metric"] == "headcount"
    }
    assert audits == {("합계", 100), ("합 계", 90)}
    assert heads == {("합계", 15), ("합 계", 14)}


def test_n5_headerless_six_value_columns_stay_missing() -> None:
    """헤더가 없는 6값 열은 키가 겹쳐 missing이다."""
    cells = _assert_missing(_without_header(_LEGACY_SINGLE_PERIOD), 15)
    role_keys = [(cell["role"], cell["role_raw"], cell["metric"]) for cell in cells]
    assert len(role_keys) != len(set(role_keys))
    assert {cell["role"] for cell in cells} == {"other"}


_FISCAL_COLSPAN = """
<html><body>
<table>
<tr>
  <td colspan="2" rowspan="2">구분</td>
  <td colspan="2">품질관리검토자</td>
  <td colspan="2">담당이사</td>
  <td colspan="2">등록공인회계사</td>
  <td colspan="2">수습공인회계사</td>
  <td colspan="2">전산감사ㆍ세무ㆍ가치평가 등 전문가</td>
  <td colspan="2">합계</td>
</tr>
<tr>
  <td>제48기</td><td>제47기</td>
  <td>제48기</td><td>제47기</td>
  <td>제48기</td><td>제47기</td>
  <td>제48기</td><td>제47기</td>
  <td>제48기</td><td>제47기</td>
  <td>제48기</td><td>제47기</td>
</tr>
<tr>
  <td colspan="2">투입 인원수</td>
  <td>1</td><td>1</td>
  <td>2</td><td>2</td>
  <td>3</td><td>3</td>
  <td>4</td><td>4</td>
  <td>5</td><td>5</td>
  <td>15</td><td>14</td>
</tr>
<tr>
  <td rowspan="3">투입시간</td>
  <td>분·반기검토</td>
  <td>1</td><td>1</td>
  <td>2</td><td>2</td>
  <td>3</td><td>3</td>
  <td>4</td><td>4</td>
  <td>5</td><td>5</td>
  <td>15</td><td>14</td>
</tr>
<tr>
  <td>감사</td>
  <td>10</td><td>10</td>
  <td>20</td><td>20</td>
  <td>30</td><td>30</td>
  <td>4</td><td>4</td>
  <td>5</td><td>5</td>
  <td>100</td><td>90</td>
</tr>
<tr>
  <td>합계</td>
  <td>11</td><td>11</td>
  <td>22</td><td>22</td>
  <td>33</td><td>33</td>
  <td>8</td><td>8</td>
  <td>10</td><td>10</td>
  <td>115</td><td>104</td>
</tr>
</table>
</body></html>
"""


def test_n6_fiscal_colspan_pair_stays_missing() -> None:
    """「제48기」/「제47기」 colspan은 역할명이 복제되어 missing이다."""
    cells = _assert_missing(_FISCAL_COLSPAN, 16)
    audits = [
        cell["value"] for cell in cells if cell["role"] == "total" and cell["metric"] == "audit"
    ]
    assert audits == [100, 90]
    assert {cell["period"] for cell in cells} == {"unknown"}
    role_keys = [(cell["role"], cell["role_raw"], cell["metric"]) for cell in cells]
    assert len(role_keys) != len(set(role_keys))


_PRIOR_ONLY = """
<html><body>
<table>
<tr>
  <td rowspan="2">구분</td>
  <td>품질관리검토자</td>
  <td>담당이사</td>
  <td>등록공인회계사</td>
  <td>수습공인회계사</td>
  <td>전산감사ㆍ세무ㆍ가치평가 등 전문가</td>
  <td>합계</td>
</tr>
<tr>
  <td>전기</td><td>전기</td><td>전기</td><td>전기</td><td>전기</td><td>전기</td>
</tr>
<tr>
  <td>투입 인원수</td>
  <td>1</td><td>2</td><td>3</td><td>4</td><td>5</td><td>15</td>
</tr>
<tr>
  <td rowspan="3">투입시간</td>
  <td>분·반기검토</td>
  <td>1</td><td>2</td><td>3</td><td>4</td><td>5</td><td>15</td>
</tr>
<tr>
  <td>감사</td>
  <td>10</td><td>20</td><td>30</td><td>4</td><td>5</td><td>90</td>
</tr>
<tr>
  <td>합계</td>
  <td>11</td><td>22</td><td>33</td><td>8</td><td>10</td><td>105</td>
</tr>
</table>
</body></html>
"""


def test_n7_prior_only_table_stays_missing() -> None:
    """전기만 있는 표(합계 90)는 missing이다."""
    cells = _assert_missing(_PRIOR_ONLY, 17)
    total = next(cell for cell in cells if cell["role"] == "total" and cell["metric"] == "audit")
    assert total["period"] == "prior"
    assert total["value"] == 90


def _assert_accepted(html: str, index: int, keys: tuple[object, object]) -> list[dict[str, object]]:
    """가드 참, 지정한 골드 키, 신호 없음, duplicate 없음."""
    cells, guard, got, signals, duplicate = _read(html, index)
    assert guard is True
    assert got == keys
    assert signals == []
    assert duplicate is False
    return cells


_K1_TWO_FISCAL = """
<html><body><table>
<tr><td>구분</td><td>담당이사 제48기</td><td>담당이사 제47기</td><td>합계</td></tr>
<tr><td>투입 인원수</td><td>1</td><td>2</td><td>3</td></tr>
<tr><td>감사</td><td>80</td><td>100</td><td>180</td></tr>
</table></body></html>
"""

_K4_ONE_FISCAL = """
<html><body><table>
<tr><td>구분</td><td>담당이사 제48기</td><td>등록공인회계사</td><td>합계</td></tr>
<tr><td>투입 인원수</td><td>1</td><td>4</td><td>5</td></tr>
<tr><td>감사</td><td>40</td><td>50</td><td>90</td></tr>
</table></body></html>
"""

_K6_SPACED_FISCAL = """
<html><body><table>
<tr><td>구분</td><td>담당이사 제 48 기</td><td>등록공인회계사</td><td>합계</td></tr>
<tr><td>투입 인원수</td><td>1</td><td>4</td><td>5</td></tr>
<tr><td>감사</td><td>40</td><td>50</td><td>90</td></tr>
</table></body></html>
"""

_K5_TWO_SPACED_FISCAL = """
<html><body><table>
<tr><td>구분</td><td>담당이사 제 48 기</td><td>담당이사 (제47기)</td><td>합계</td></tr>
<tr><td>투입 인원수</td><td>1</td><td>2</td><td>3</td></tr>
<tr><td>감사</td><td>80</td><td>100</td><td>180</td></tr>
</table></body></html>
"""

_K3_SPECIALISTS = """
<html><body><table>
<tr><td>구분</td><td>전산감사 전문가</td><td>세무 전문가</td><td>합계</td></tr>
<tr><td>투입 인원수</td><td>1</td><td>1</td><td>2</td></tr>
<tr><td>감사</td><td>40</td><td>60</td><td>100</td></tr>
</table></body></html>
"""

_K2_SUBTITLE_FISCAL = """
<html><body><table>
<tr>
  <td rowspan="2">구분</td>
  <td>담당이사</td><td>등록공인회계사</td><td>합계</td>
</tr>
<tr><td>제47기</td><td>제47기</td><td>제47기</td></tr>
<tr><td>투입 인원수</td><td>1</td><td>4</td><td>5</td></tr>
<tr><td>감사</td><td>40</td><td>50</td><td>90</td></tr>
</table></body></html>
"""


def test_n18_two_fiscal_marks_in_role_raw_are_missing() -> None:
    """담당이사 제48기·제47기와 합계가 있으면 missing이다."""
    cells = _assert_missing(_K1_TWO_FISCAL, 21)
    raws = {cell["role_raw"] for cell in cells}
    assert "담당이사 제48기" in raws
    assert "담당이사 제47기" in raws
    total = next(cell for cell in cells if cell["role"] == "total" and cell["metric"] == "audit")
    assert total["value"] == 180


def test_n19_one_fiscal_mark_in_role_raw_is_missing() -> None:
    """기수가 한 종류(담당이사 제48기)여도 missing이다."""
    cells = _assert_missing(_K4_ONE_FISCAL, 22)
    assert any(cell["role_raw"] == "담당이사 제48기" for cell in cells)
    total = next(cell for cell in cells if cell["role"] == "total" and cell["metric"] == "audit")
    assert total["value"] == 90


def test_n20_spaced_fiscal_mark_is_missing() -> None:
    """「제 48 기」처럼 공백이 있어도 공백을 빼고 보면 missing이다."""
    cells = _assert_missing(_K6_SPACED_FISCAL, 23)
    assert any(cell["role_raw"] == "담당이사 제 48 기" for cell in cells)


def test_n21_two_spaced_fiscal_marks_are_missing() -> None:
    """띄어 쓴 제48기와 괄호 안 제47기가 같이 있으면 missing이다."""
    cells = _assert_missing(_K5_TWO_SPACED_FISCAL, 24)
    raws = {cell["role_raw"] for cell in cells}
    assert "담당이사 제 48 기" in raws
    assert "담당이사 (제47기)" in raws


def test_n22_distinct_specialist_headers_stay_single_period() -> None:
    """전산감사·세무처럼 기수가 없는 다른 원문은 가드가 참이고 합계는 (100, 2)다."""
    cells = _assert_accepted(_K3_SPECIALISTS, 25, (100, 2))
    assert {cell["role_raw"] for cell in cells} == {"전산감사 전문가", "세무 전문가", "합계"}


def test_n23_subtitle_only_fiscal_mark_stays_single_period() -> None:
    """소제목 행의 제47기만 있는 표는 가드가 참이다.

    추출기 후속 전까지의 알려진 한계다. 칸의 role_raw에는 기수가 남지 않는다.
    추출기를 고치면 이 기대값을 바꿔야 한다.
    """
    cells = _assert_accepted(_K2_SUBTITLE_FISCAL, 26, (90, 5))
    assert {cell["role_raw"] for cell in cells} == {"담당이사", "등록공인회계사", "합계"}
    assert {cell["period"] for cell in cells} == {"unknown"}
    assert all("제" not in str(cell["role_raw"]) for cell in cells)


def test_n14_equal_unlabeled_colspan_totals_stay_missing() -> None:
    """colspan 무라벨 2열은 감사 합계가 100/100으로 같아도 missing이다."""
    html = _UNLABELED_COLSPAN.replace("<td>100</td><td>90</td>", "<td>100</td><td>100</td>", 1)
    assert html != _UNLABELED_COLSPAN
    cells = _assert_missing(html, 18)
    audits = [
        cell["value"] for cell in cells if cell["role"] == "total" and cell["metric"] == "audit"
    ]
    assert audits == [100, 100]
