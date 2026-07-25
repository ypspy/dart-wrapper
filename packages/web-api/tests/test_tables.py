"""HTML 표 → JSON 변환 테스트."""

from __future__ import annotations

from app.parsing.tables import extract_tables

TABLE_HTML = """
<body>
  <table>
    <tr><th>과목</th><th>당기</th></tr>
    <tr><td>자산총계</td><td>1,000</td></tr>
    <tr><td>부채총계</td><td>400</td></tr>
  </table>
  <table>
    <tr><td>비고</td><td>단위: 백만원&nbsp;</td></tr>
  </table>
  <table></table>
</body>
"""


def test_extract_tables_splits_headers_and_rows() -> None:
    tables = extract_tables(TABLE_HTML)

    assert len(tables) == 2
    assert tables[0] == {
        "headers": ["과목", "당기"],
        "rows": [["자산총계", "1,000"], ["부채총계", "400"]],
    }


def test_extract_tables_keeps_all_rows_when_no_header() -> None:
    tables = extract_tables(TABLE_HTML)

    assert tables[1] == {"headers": [], "rows": [["비고", "단위: 백만원"]]}


def test_extract_tables_returns_empty_list_without_tables() -> None:
    assert extract_tables("<body><p>표 없음</p></body>") == []
