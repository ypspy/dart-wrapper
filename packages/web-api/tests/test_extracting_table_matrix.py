from bs4 import BeautifulSoup

from app.extracting.table_matrix import expand_table_matrix
from app.parsing.blocks import extract_blocks


def _table(html: str):
    soup = BeautifulSoup(f"<html><body>{html}</body></html>", "lxml")
    return soup.find("table")


def test_expand_repeats_rowspan_and_colspan() -> None:
    """병합 칸이 격자의 각 칸에 복제된다."""
    table = _table("""
        <table>
          <tr><td rowspan="2">투입 인원수</td><td>당기</td><td>10</td></tr>
          <tr><td>전기</td><td>8</td></tr>
          <tr><td colspan="2">합계</td><td>18</td></tr>
        </table>
        """)
    matrix = expand_table_matrix(table)
    assert matrix[0][0] == "투입 인원수"
    assert matrix[1][0] == "투입 인원수"
    assert matrix[2][0] == "합계"
    assert matrix[2][1] == "합계"
    assert matrix[0][2] == "10"


def test_expand_clamps_rowspan_past_last_row() -> None:
    """마지막 행을 넘는 rowspan은 IndexError 없이 잘린다."""
    table = _table("""
        <table>
          <tr><td rowspan="3">A</td><td>1</td></tr>
          <tr><td>2</td></tr>
        </table>
        """)
    matrix = expand_table_matrix(table)
    assert len(matrix) == 2
    assert matrix[0][0] == "A"
    assert matrix[1][0] == "A"
    assert matrix[0][1] == "1"
    assert matrix[1][1] == "2"


def test_expand_skips_extra_cells_under_rowspan() -> None:
    """윗행 rowspan 아래 칸이 더 있어도 IndexError가 나지 않는다."""
    table = _table("""
        <table>
          <tr><td rowspan="2">A</td><td>1</td></tr>
          <tr><td>2</td><td>EXTRA</td></tr>
        </table>
        """)
    matrix = expand_table_matrix(table)
    assert matrix[0][0] == "A"
    assert matrix[1][0] == "A"
    assert matrix[0][1] == "1"
    assert matrix[1][1] == "2"


def test_viewer_parse_table_does_not_expand_span() -> None:
    """D-4 격자와 달리 Viewer는 행 길이가 제각각이다."""
    html = """
    <html><body>
    <table>
      <tr><td rowspan="2">A</td><td>1</td></tr>
      <tr><td>2</td></tr>
    </table>
    </body></html>
    """
    blocks = extract_blocks(html)
    table = next(b for b in blocks if b.type == "table")
    assert len(table.rows[0]) == 2
    assert len(table.rows[1]) == 1
