"""추출기는 기간을 바꾸지 않고, 신호만 단일 기간 합계를 읽는다."""

from __future__ import annotations

from research.extracting.activity_hours import extract_hours
from research.extracting.constants import EXTRACTOR_VERSION
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
