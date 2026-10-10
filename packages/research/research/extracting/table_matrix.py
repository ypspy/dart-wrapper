"""실시내용 표의 rowspan/colspan을 격자로 펼친다."""

from __future__ import annotations

from bs4 import Tag


def _span(cell: Tag, name: str) -> int:
    try:
        return max(int(cell.get(name, 1)), 1)
    except (TypeError, ValueError):
        return 1


def expand_table_matrix(table: Tag) -> list[list[str]]:
    """colspan/rowspan을 칸에 복제한 2차원 리스트를 반환한다.

    셀은 strip만 한다. 매칭용 compact는 호출측에서 한다.
    마지막 행을 넘는 rowspan·빈 칸보다 많은 셀은 쓰지 않고 건너뛴다.
    """
    rows = table.find_all("tr")
    column_count = 0
    for row in rows:
        width = 0
        for cell in row.find_all(["th", "td"]):
            width += _span(cell, "colspan")
        column_count = max(column_count, width)

    matrix = [["#" for _ in range(column_count)] for _ in rows]
    for row_index, row in enumerate(rows):
        locator = [i for i, value in enumerate(matrix[row_index]) if value == "#"]
        offset = 0
        for cell in row.find_all(["th", "td"]):
            text = cell.get_text(" ", strip=True)
            row_span = _span(cell, "rowspan")
            col_span = _span(cell, "colspan")
            for down in range(row_span):
                target_row = row_index + down
                if target_row >= len(matrix):
                    break
                for right in range(col_span):
                    loc_index = offset + right
                    if loc_index >= len(locator):
                        break
                    matrix[target_row][locator[loc_index]] = text
            offset += col_span
    return matrix
