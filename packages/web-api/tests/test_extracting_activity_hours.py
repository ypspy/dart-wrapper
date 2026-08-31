from app.extracting.activity_hours import extract_hours

_COMPARATIVE = """
<html><body>
<table>
<tr>
  <td rowspan="2">구분</td>
  <td colspan="2">담당이사<br/>(업무수행이사)</td>
  <td colspan="2">합계</td>
</tr>
<tr><td>당기</td><td>전기</td><td>당기</td><td>전기</td></tr>
<tr><td>투입 인원수</td><td></td><td>1</td><td>1</td><td>2</td><td>2</td></tr>
<tr><td rowspan="3">투입시간</td><td>분·반기검토</td><td>10</td><td>-</td><td>10</td><td>-</td></tr>
<tr><td>감사</td><td>100</td><td>80</td><td>100</td><td>80</td></tr>
<tr><td>합계</td><td>110</td><td>80</td><td>110</td><td>80</td></tr>
</table>
</body></html>
"""


def test_extract_hours_comparative_roles_and_metrics() -> None:
    """비교표시 표에서 역할·지표·기간과 '-'→0을 피벗한다."""
    cells, status = extract_hours(_COMPARATIVE)
    assert status == "ok"
    audit_partner = next(
        c
        for c in cells
        if c["role"] == "engagement_partner" and c["metric"] == "audit" and c["period"] == "current"
    )
    assert audit_partner["value"] == 100
    dash = next(
        c
        for c in cells
        if c["metric"] == "interim_review"
        and c["period"] == "prior"
        and c["role"] == "engagement_partner"
    )
    assert dash["raw"] == "-"
    assert dash["value"] == 0
    totals = [c for c in cells if c["role"] == "total" and c["metric"] == "total"]
    assert len(totals) == 2


def test_extract_hours_missing_table_is_not_found() -> None:
    """투입인원수 표가 없으면 not_found와 빈 목록이다."""
    cells, status = extract_hours("<html><body><p>없음</p></body></html>")
    assert status == "not_found"
    assert cells == []


def test_extract_hours_legacy_other_role() -> None:
    """옛 서식 '기타' 열은 role=other로 매칭한다."""
    html = """
    <html><body>
    <table>
    <tr><td></td><td>기타</td></tr>
    <tr><td>투입 인원수</td><td>3</td></tr>
    </table>
    </body></html>
    """
    cells, status = extract_hours(html)
    assert status == "ok"
    assert any(c["role"] == "other" and c["value"] == 3 for c in cells)
