"""외부감사 실시내용 2절 투입시간·인원 피벗."""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.extracting.table_matrix import expand_table_matrix
from app.extracting.text import compact

_PERIOD_CURRENT = "당기"
_PERIOD_PRIOR = "전기"
_LABEL_TOKENS = {"", "#", "구분", _PERIOD_CURRENT, _PERIOD_PRIOR}
_ROW_LABEL_TOKENS = {"", "#", "구분", "투입시간"}
_INTERIM_LABELS = ("분ㆍ반기검토", "분·반기검토", "분기검토", "반기검토")
_AUDIT_EXCLUDES = ("감사참여자", "감사업무", "감사시간")


def extract_hours(html: str) -> tuple[list[dict[str, object]], str]:
    """2절 표의 역할×지표×기간 칸을 피벗한다.

    표를 찾으면 일부 칸이 매칭되지 않아도 상태는 ok다.
    투입인원수 행이 있는 표가 없으면 not_found와 빈 목록이다.
    """
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        matrix = expand_table_matrix(table)
        headcount_row = _headcount_row_index(matrix)
        if headcount_row is None:
            continue
        return _pivot(matrix, headcount_row), "ok"
    return [], "not_found"


def _headcount_row_index(matrix: list[list[str]]) -> int | None:
    """앞 두 열 compact에 투입인원수가 있는 첫 행 인덱스를 반환한다."""
    for index, row in enumerate(matrix):
        if any("투입인원수" in compact(cell) for cell in row[:2]):
            return index
    return None


def _role_from_token(token: str) -> str | None:
    """스펙 표 순서대로 역할을 고른다. 당기/전기·빈 칸은 None."""
    if token in _LABEL_TOKENS:
        return None
    if "품질관리검토자" in token or "심리실" in token:
        return "qcr"
    if "담당이사" in token or "업무수행이사" in token:
        return "engagement_partner"
    if "등록공인회계사" in token:
        return "cpa"
    if "수습공인회계사" in token:
        return "junior_cpa"
    if "수주산업" in token or "건설계약" in token:
        return "construction_specialist"
    if "전산감사" in token or "가치평가" in token or "세무" in token:
        return "specialist"
    if token == "합계":
        return "total"
    return "other"


def _metric_from_token(token: str) -> str | None:
    """앞 두 열 토큰에서 지표를 고른다. 라벨이 아니면 None."""
    if "투입인원수" in token:
        return "headcount"
    if any(label in token for label in _INTERIM_LABELS):
        return "interim_review"
    if token == "합계":
        return "total"
    if token == "감사" and not any(excl in token for excl in _AUDIT_EXCLUDES):
        return "audit"
    return None


def _match_role(header_texts: list[str]) -> tuple[str, str, bool]:
    """열 헤더에서 역할과 원문을 읽는다. 헤더가 비면 unmapped이다."""
    for text in header_texts:
        role = _role_from_token(compact(text))
        if role is None:
            continue
        return role, text, False
    return "other", "", True


def _match_period(header_texts: list[str], cell: str) -> tuple[str, str]:
    """열 헤더 또는 칸에서 당기/전기 기간을 읽는다."""
    for text in (*header_texts, cell):
        token = compact(text)
        if _PERIOD_CURRENT in token:
            return "current", text
        if _PERIOD_PRIOR in token:
            return "prior", text
    return "unknown", ""


def _match_metric(col0: str, col1: str) -> tuple[str, str]:
    """앞 두 열에서 알려진 지표를 고른다. 없으면 other."""
    other_raw = ""
    for text in (col0, col1):
        token = compact(text)
        if not token or token == "#":
            continue
        metric = _metric_from_token(token)
        if metric is not None:
            return metric, text
        if not other_raw:
            other_raw = text
    return "other", other_raw


def _parse_value(raw: str) -> int | None:
    """쉼표를 뺀 정수. '-'·공백은 0, 숫자가 아니면 None."""
    token = compact(raw)
    if token in {"", "-", "#"}:
        return 0
    try:
        return int(token.replace(",", ""))
    except ValueError:
        return None


def _is_label_column(header_texts: list[str]) -> bool:
    """구분·기간만 있거나 비어 있는 열은 역할 열이 아니다."""
    meaningful = [compact(text) for text in header_texts]
    meaningful = [token for token in meaningful if token and token != "#"]
    if not meaningful:
        return True
    return all(token in {"구분", _PERIOD_CURRENT, _PERIOD_PRIOR} for token in meaningful)


def _is_row_label_cell(text: str, col_index: int) -> bool:
    """지표 행의 앞 두 열에서 라벨·빈 칸을 건너뛴다."""
    if col_index >= 2:
        return False
    token = compact(text)
    if token in _ROW_LABEL_TOKENS:
        return True
    return _metric_from_token(token) is not None


def _column_headers(matrix: list[list[str]], header_end: int) -> list[list[str]]:
    """투입인원수 행 위 헤더를 열별 텍스트 목록으로 모은다."""
    if not matrix:
        return []
    width = len(matrix[0])
    columns: list[list[str]] = [[] for _ in range(width)]
    for row in matrix[:header_end]:
        for col_index, text in enumerate(row):
            columns[col_index].append(text)
    return columns


def _pivot(matrix: list[list[str]], headcount_row: int) -> list[dict[str, object]]:
    """헤더 역할 열과 지표 행을 교차해 hours 원소를 만든다."""
    headers = _column_headers(matrix, headcount_row)
    role_columns: list[tuple[str, str, bool, list[str]]] = []
    for header_texts in headers:
        if _is_label_column(header_texts):
            continue
        role, role_raw, unmapped = _match_role(header_texts)
        role_columns.append((role, role_raw, unmapped, header_texts))

    cells: list[dict[str, object]] = []
    for row in matrix[headcount_row:]:
        col0 = row[0] if row else ""
        col1 = row[1] if len(row) > 1 else ""
        metric, metric_raw = _match_metric(col0, col1)
        values = [cell for index, cell in enumerate(row) if not _is_row_label_cell(cell, index)]
        for (role, role_raw, unmapped, header_texts), raw in zip(role_columns, values):
            period, period_raw = _match_period(header_texts, raw)
            cells.append(
                {
                    "role": role,
                    "role_raw": role_raw,
                    "metric": metric,
                    "metric_raw": metric_raw,
                    "period": period,
                    "period_raw": period_raw,
                    "raw": raw,
                    "value": _parse_value(raw),
                    "unmapped": unmapped,
                }
            )
    return cells
