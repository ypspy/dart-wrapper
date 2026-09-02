"""첨부 재무제표 HTML에서 E-4 연구 계정(당기·전기)을 추출한다."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from app.extracting.table_matrix import expand_table_matrix
from app.extracting.text import compact

_GI_RE = re.compile(r"제(\d+)기")
_PERIOD_SUFFIXES = frozenset({"기말", "기초", "말"})


def cut_notes(html: str) -> str:
    """부모 제표 HTML에서 '주석 ' 이후를 잘라 본표만 남긴다."""
    return html.split("주석 ", 1)[0]


_EIGHT_ACCOUNTS: tuple[str, ...] = (
    "total_asset",
    "total_equity",
    "net_income",
    "inventory",
    "receivable",
    "long_term_receivable",
    "contract_asset",
    "unbilled",
)

_TOTAL_ACCOUNTS = frozenset({"total_asset", "total_equity", "net_income"})

_NET_INCOME_EXCLUDES: tuple[str, ...] = (
    "계속",
    "중단",
    "귀속",
    "미처분",
    "미처리",
    "처분전",
    "지배",
    "비지배",
    "관계",
    "공동",
    "차감전",
    "이익잉여금",
    "총포괄",
)


@dataclass(frozen=True)
class _PeriodGroup:
    """헤더에서 읽은 당기/전기 금액 칸 묶음."""

    period: str
    period_raw: str
    detail_col: int
    total_col: int | None


def extract_accounts(
    *, bs_html: str | None, is_html: str | None
) -> tuple[list[dict[str, object]], str]:
    """재무상태표·손익계산서 HTML에서 여덟 계정×기간 레코드를 만든다.

    둘 다 없으면 skipped, 쓸 수 있는 기간 헤더를 못 읽으면 not_found, 읽으면 ok.
    """
    if not bs_html and not is_html:
        return [], "skipped"

    records: dict[tuple[str, str], dict[str, object]] = {}
    found_accounts: set[str] = set()
    periods_ordered: list[str] = []
    period_raws: dict[str, str] = {}
    unit_raw: str | None = None
    unit_scale: int | None = None

    for kind, html in (("bs", bs_html), ("is", is_html)):
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        table = _find_bs_table(soup) if kind == "bs" else _find_is_table(soup)
        if table is None:
            continue
        stmt_unit_raw, stmt_unit_scale = _unit_before(table)
        if unit_raw is None and stmt_unit_raw is not None:
            unit_raw, unit_scale = stmt_unit_raw, stmt_unit_scale
        _extract_from_table(
            table,
            records=records,
            found_accounts=found_accounts,
            periods_ordered=periods_ordered,
            period_raws=period_raws,
            unit_raw=stmt_unit_raw,
            unit_scale=stmt_unit_scale,
        )

    if not periods_ordered:
        return [], "not_found"

    return (
        _finalize_records(
            records,
            found_accounts=found_accounts,
            periods_ordered=periods_ordered,
            period_raws=period_raws,
            unit_raw=unit_raw,
            unit_scale=unit_scale,
        ),
        "ok",
    )


def _account_of(label: str) -> str | None:
    """compact 라벨을 E-4 계정 키로 바꾼다. 앞 규칙이 이긴다."""
    token = compact(label)
    if not token:
        return None
    if "자산총계" in token:
        return "total_asset"
    if "자본총계" in token:
        if "부채와자본총계" in token or "부채및자본총계" in token:
            return None
        return "total_equity"
    if "당기순" in token and not any(ex in token for ex in _NET_INCOME_EXCLUDES):
        return "net_income"
    if "재고" in token and "충당" not in token:
        return "inventory"
    if "장기매출" in token or "장기성매출" in token:
        return "long_term_receivable"
    if "매출채" in token or "매출금" in token:
        return "receivable"
    if "계약자산" in token:
        return "contract_asset"
    if "미청구공사" in token:
        return "unbilled"
    return None


def _find_bs_table(soup: BeautifulSoup) -> Tag | None:
    """재무상태표 제목 다음 표, 없으면 부채/자산총계 표를 고른다."""
    for el in soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "td", "div"]):
        if "재무상태표" not in compact(el.get_text(" ", strip=True)):
            continue
        for table in el.find_all_next("table"):
            if _table_width(table) >= 3:
                return table
        break
    for table in soup.find_all("table"):
        if _matrix_has(table, "부채"):
            return table
    for table in soup.find_all("table"):
        if _matrix_has(table, "자산총계"):
            return table
    return None


def _find_is_table(soup: BeautifulSoup) -> Tag | None:
    """손익·포괄손익 제목 다음 표, 없으면 당기순 표를 고른다."""
    for el in soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "td", "div"]):
        token = compact(el.get_text(" ", strip=True))
        if "손익계산서" not in token and "포괄손익계산서" not in token:
            continue
        for table in el.find_all_next("table"):
            if _table_width(table) >= 3:
                return table
        break
    for table in soup.find_all("table"):
        flat = _matrix_flat(table)
        if "자본변동" in flat:
            continue
        if "당기순" not in flat:
            continue
        if any(ex in flat for ex in ("미처분", "미처리", "이익잉여금")):
            continue
        return table
    return None


def _table_width(table: Tag) -> int:
    matrix = expand_table_matrix(table)
    if not matrix:
        return 0
    return max(len(row) for row in matrix)


def _matrix_has(table: Tag, needle: str) -> bool:
    return needle in _matrix_flat(table)


def _matrix_flat(table: Tag) -> str:
    matrix = expand_table_matrix(table)
    return "".join(compact(cell) for row in matrix for cell in row)


def _unit_before(table: Tag) -> tuple[str | None, int | None]:
    """표 앞 p/td에서 단위 줄을 읽어 (unit_raw, unit_scale)을 반환한다."""
    for el in table.find_all_previous(["p", "td"]):
        token = compact(el.get_text(" ", strip=True))
        if "단위" not in token:
            continue
        if "백만원" in token:
            return "백만원", 1_000_000
        if "천원" in token:
            return "천원", 1000
        if "원" in token:
            return "원", 1
        return None, None
    return None, None


def _is_excluded_period_cell(token: str) -> bool:
    """과목·당기순 칸은 기간 열로 보지 않는다."""
    return "과목" in token or "당기순" in token


def _is_gi_period_column_label(token: str) -> bool:
    """제N기 토큰이 기간 열 라벨인지 본다. 제목 문장(제N기 뒤에 추가 텍스트)은 제외."""
    match = _GI_RE.search(token)
    if not match:
        return False
    remainder = token[match.end() :]
    if not remainder:
        return True
    return remainder in _PERIOD_SUFFIXES


def _is_header_row(row: list[str]) -> bool:
    """과목·당기/전기·제n기 헤더 행인지 판별한다."""
    tokens = [compact(cell) for cell in row]
    if any("과목" in token for token in tokens):
        return True
    for token in tokens:
        if _is_excluded_period_cell(token):
            continue
        if "당기" in token or "(당)기" in token:
            return True
        if "전기" in token or "(전)기" in token:
            return True
        if _is_gi_period_column_label(token):
            return True
    return False


def _col_role(header_text: str) -> str | None:
    """헤더 칸을 note/current/prior로 분류한다. 라벨 칸은 None."""
    token = compact(header_text)
    if "주석" in token or "주기" in token:
        return "note"
    if _is_excluded_period_cell(token):
        return None
    if "당기" in token or "(당)기" in token:
        return "current"
    if "전기" in token or "(전)기" in token:
        return "prior"
    return None


def _groups_from_roles(
    header: list[str], roles: list[str | None]
) -> list[_PeriodGroup]:
    groups: list[_PeriodGroup] = []
    index = 0
    while index < len(roles):
        role = roles[index]
        if role not in ("current", "prior"):
            index += 1
            continue
        end = index
        while end < len(roles) and roles[end] == role:
            end += 1
        cols = list(range(index, end))
        period_raw = header[index]
        if len(cols) == 1:
            groups.append(_PeriodGroup(role, period_raw, cols[0], None))
        else:
            groups.append(_PeriodGroup(role, period_raw, cols[0], cols[1]))
        index = end
    return groups


def _period_groups(header: list[str]) -> tuple[list[_PeriodGroup], list[int]]:
    """기간 그룹과 라벨 열 인덱스를 만든다."""
    roles = [_col_role(cell) for cell in header]
    groups = _groups_from_roles(header, roles)
    if not groups:
        roles = _roles_from_gi_or_position(header, roles)
        groups = _groups_from_roles(header, roles)
    label_cols = [i for i, role in enumerate(roles) if role is None]
    return groups, label_cols


def _roles_from_gi_or_position(
    header: list[str], base_roles: list[str | None]
) -> list[str | None]:
    """당기/전기 그룹이 없을 때 기수 또는 왼쪽·오른쪽으로 채운다."""
    roles = list(base_roles)
    amount_cols = [
        i
        for i, role in enumerate(roles)
        if role != "note" and not _is_excluded_period_cell(compact(header[i]))
    ]
    gi_cols: list[tuple[int, int]] = []
    for index, cell in enumerate(header):
        if roles[index] == "note":
            continue
        token = compact(cell)
        if _is_excluded_period_cell(token):
            continue
        match = _GI_RE.search(token)
        if match:
            gi_cols.append((index, int(match.group(1))))
    numbers = {n for _i, n in gi_cols}
    if len(gi_cols) == 1:
        roles[gi_cols[0][0]] = "current"
        return roles
    if len(gi_cols) >= 2 and len(numbers) >= 2:
        lo, hi = min(numbers), max(numbers)
        for index, number in gi_cols:
            if number == hi:
                roles[index] = "current"
            elif number == lo:
                roles[index] = "prior"
        return roles
    if not amount_cols:
        return roles
    roles[amount_cols[0]] = "current"
    if len(amount_cols) >= 2:
        roles[amount_cols[1]] = "prior"
    return roles


def _row_label(row: list[str], label_cols: list[int]) -> tuple[str, str]:
    """라벨 열의 비어 있지 않은 셀을 (compact, 원문)으로 반환한다."""
    parts: list[str] = []
    for col in label_cols:
        if col >= len(row):
            continue
        text = row[col].strip()
        if text:
            parts.append(text)
    raw = " ".join(parts)
    return compact(raw), raw


def _parse_amount(cell: str) -> tuple[str, int] | None:
    """금액 칸을 (raw, value)로 읽는다. 공란은 None, 대시만 있으면 0."""
    raw = cell.strip()
    if not raw:
        return None
    token = compact(raw)
    if token in ("-", "－"):
        return raw, 0

    cleaned = raw.replace("=", "").strip()
    token = compact(cleaned)
    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        negative = True
        cleaned = cleaned[1:-1].strip()
    elif token.startswith("△"):
        negative = True
        cleaned = re.sub(r"△", "", cleaned, count=1)
    elif token.startswith("-") and re.search(r"\d", token):
        negative = True
        cleaned = re.sub(r"^\s*-", "", cleaned, count=1)

    digits = re.sub(r"[^\d]", "", compact(cleaned))
    if not digits:
        return None
    value = int(digits)
    if negative:
        value = -value
    return raw, value


def _pick_amount(
    row: list[str], group: _PeriodGroup, account: str
) -> tuple[str, int] | None:
    """기간 그룹에서 내역/합계 규칙으로 금액을 고른다."""
    detail = row[group.detail_col] if group.detail_col < len(row) else ""
    if group.total_col is None:
        return _parse_amount(detail)

    total = row[group.total_col] if group.total_col < len(row) else ""
    detail_parsed = _parse_amount(detail)
    total_parsed = _parse_amount(total)
    if detail_parsed is not None and total_parsed is not None:
        if account in _TOTAL_ACCOUNTS:
            return total_parsed
        return detail_parsed
    return detail_parsed if detail_parsed is not None else total_parsed


def _row_is_aligned(row: list[str], header_width: int) -> bool:
    """짧은 행이 왼쪽으로 밀려 헤더 열과 어긋났는지 본다.

    expand_table_matrix는 채우지 못한 칸을 '#'로 남기므로, 그 칸이 있으면
    열 수가 헤더보다 부족한 잘못 정렬된 행이다.
    """
    if len(row) != header_width:
        return False
    return "#" not in row


def _extract_from_table(
    table: Tag,
    *,
    records: dict[tuple[str, str], dict[str, object]],
    found_accounts: set[str],
    periods_ordered: list[str],
    period_raws: dict[str, str],
    unit_raw: str | None,
    unit_scale: int | None,
) -> None:
    """한 표에서 아직 없는 계정의 기간 금액을 채운다."""
    matrix = expand_table_matrix(table)
    if not matrix:
        return

    header_index: int | None = None
    groups: list[_PeriodGroup] = []
    label_cols: list[int] = []

    for index, candidate in enumerate(matrix):
        if not _is_header_row(candidate):
            continue
        roles = [_col_role(cell) for cell in candidate]
        candidate_groups = _groups_from_roles(candidate, roles)
        if not candidate_groups:
            continue
        periods = {group.period for group in candidate_groups}
        if periods != {"current", "prior"}:
            continue
        header_index = index
        groups = candidate_groups
        label_cols = [i for i, role in enumerate(roles) if role is None]
        break

    if header_index is None:
        for index, candidate in enumerate(matrix):
            if not _is_header_row(candidate):
                continue
            candidate_groups, candidate_labels = _period_groups(candidate)
            if not candidate_groups:
                continue
            header_index = index
            groups = candidate_groups
            label_cols = candidate_labels
            break

    if header_index is None:
        return

    header = matrix[header_index]
    header_width = len(header)

    for group in groups:
        if group.period not in periods_ordered:
            periods_ordered.append(group.period)
            period_raws[group.period] = group.period_raw

    for row in matrix[header_index + 1 :]:
        if not _row_is_aligned(row, header_width):
            continue
        label_compact, label_raw = _row_label(row, label_cols)
        account = _account_of(label_compact)
        if account is None or account in found_accounts:
            continue
        picked_any = False
        for group in groups:
            key = (account, group.period)
            if key in records:
                continue
            parsed = _pick_amount(row, group, account)
            if parsed is None:
                continue
            picked_any = True
            raw, value = parsed
            value_won = value * unit_scale if unit_scale is not None else None
            records[key] = {
                "account": account,
                "account_raw": label_raw,
                "period": group.period,
                "period_raw": group.period_raw,
                "raw": raw,
                "value": value,
                "unit_raw": unit_raw,
                "unit_scale": unit_scale,
                "value_won": value_won,
                "status": "ok",
            }
        if picked_any:
            found_accounts.add(account)


def _finalize_records(
    records: dict[tuple[str, str], dict[str, object]],
    *,
    found_accounts: set[str],
    periods_ordered: list[str],
    period_raws: dict[str, str],
    unit_raw: str | None,
    unit_scale: int | None,
) -> list[dict[str, object]]:
    """여덟 계정×기간 순으로 정렬하고 미발견 계정은 not_found를 채운다."""
    result: list[dict[str, object]] = []
    for account in _EIGHT_ACCOUNTS:
        for period in periods_ordered:
            key = (account, period)
            if key in records:
                result.append(records[key])
                continue
            if account in found_accounts:
                continue
            result.append(
                {
                    "account": account,
                    "account_raw": None,
                    "period": period,
                    "period_raw": period_raws.get(period),
                    "raw": None,
                    "value": None,
                    "unit_raw": unit_raw,
                    "unit_scale": unit_scale,
                    "value_won": None,
                    "status": "not_found",
                }
            )
    return result
