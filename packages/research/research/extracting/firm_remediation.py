"""Ⅵ 소제목 2(품질관리·감사인 감리결과) 개선권고 이행 표 파서.

``parse_remediation``은 문서 하나를 다루며 파일·DB·네트워크에 접근하지 않는다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

PARSER_VERSION = "f004-remediation-0.1"

_SUBSECTION_LINE = re.compile(r"^2\.\s*(품질관리 감리결과|감사인 감리결과)\s*$")
_SUBSECTION_PHRASES = ("2. 품질관리 감리결과", "2. 감사인 감리결과")
_SUBHEAD = re.compile(r"^(\d+)\)\s*")
_DATE = re.compile(
    r"^(?:\d{4}\s*[.\-/]\s*\d{1,2}(?:\s*[.\-/]\s*\d{1,2})?|\d{4}\s*년\s*\d{1,2}\s*월)"
)
_STAR_LINE = re.compile(r"^\s*[*※]")
_COMMENT = re.compile(
    "|".join(
        (
            r"주\s*\)",
            r"\(\*\)",
            r"※",
            r"합계",
            r"주석",
            r"\(주\)",
            r"해당\s*사항\s*없",
            r"해당사항없",
            r"해당\s*없음",
            r"외부공개를\s*결정한\s*사항이\s*없",
            r"외부\s*공개를\s*결정한\s*사항",
            r"품질관리감리\s*수검을\s*받지",
            r"기재할\s*예정",
            r"개시할\s*예정",
            r"적용되므로\s*당해",
            r"통보되지\s*않았",
        )
    )
)
_HEADER_EXACT = "구분|조치일자|개선권고사항|개선권고이행상황"
_HEADER_TOKENS = ("구분", "조치일자", "개선권고사항", "이행상황")
_BLANK_VALUES = {
    "",
    "-",
    "—",
    "–",
    "－",
    "해당없음",
    "없음",
    "해당사항없음",
    "해당사항없",
    "해당사항없습니다",
    "해당사항이없습니다",
    "해당없습니다",
}
_WRAPPING_QUOTES = set("\"'“”‘’＂＇「」『』")
_COMMENT_HEADS = {"(주)", "（주）", "주)", "(*)", "※", "*", "주석"}
_LEGAL_PREFIXES = (
    "유한책임회사",
    "주식회사",
    "유한회사",
    "사단법인",
    "재단법인",
    "（주）",
    "(주)",
    "㈜",
)
# 개선권고 표 안에서 4칸으로 재조립하지 못한 행만 집계한다. 3) 블록은 제외한다.
IN_TABLE_UNPARSED_REASONS = frozenset({"bad_cell_count", "date_in_first_cell", "not_group_label"})


@dataclass
class LogicalRow:
    """재조립된 개선권고 논리 행. ``is_latest``는 파서 밖에서 채운다."""

    table_idx: int
    row_idx: int
    component: str
    action_date: str
    finding: str
    action: str
    parse_status: str
    source_cells: int
    is_latest: int = 0


@dataclass
class Note:
    """주석 또는 해석하지 않은 원문 한 줄."""

    note_idx: int
    table_idx: int | None
    kind: str
    raw_text: str
    reason: str
    in_table: bool


@dataclass
class RemediationParseResult:
    """문서 하나의 파싱 결과. 기간 키와 최신 여부는 포함하지 않는다."""

    rcept_no: str
    corp_code: str
    status: str
    n_tables: int
    rows: list[LogicalRow] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)


@dataclass
class PreparedDocument:
    """카탈로그 기간 키를 붙인 뒤 저장·집계에 쓰는 문서."""

    rcept_no: str
    corp_code: str
    corp_name: str
    rcept_dt: str
    period_key: str | None
    status: str
    n_tables: int
    rows: list[LogicalRow]
    notes: list[Note]


def normalize_firm_display_name(name: str) -> str:
    """공백과 법정 접두만 정리한 표시용 상호. 법인 키로 쓰지 않는다."""
    text = unicodedata.normalize("NFC", name)
    text = text.replace("\u00a0", "").replace("\u3000", "")
    text = re.sub(r"\s+", "", text)
    changed = True
    while changed and text:
        changed = False
        for prefix in _LEGAL_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :]
                changed = True
    return text


def parse_remediation(rcept_no: str, corp_code: str, body_text: str) -> RemediationParseResult:
    """문서 하나. 파일/DB/네트워크에 접근하지 않는다."""
    lines = _subsection_lines(body_text)
    if lines is None:
        return RemediationParseResult(
            rcept_no=rcept_no,
            corp_code=corp_code,
            status="no_subsection",
            n_tables=0,
        )

    rows: list[LogicalRow] = []
    notes: list[Note] = []
    table_idx = -1
    row_idx = 0
    component = ""
    active = False
    header_seen = False
    closed = False
    tables_with_header: set[int] = set()

    def add_note(kind: str, raw_text: str, reason: str, *, in_table: bool) -> None:
        current = table_idx if active and header_seen else None
        notes.append(
            Note(
                note_idx=len(notes),
                table_idx=current,
                kind=kind,
                raw_text=raw_text,
                reason=reason,
                in_table=in_table,
            )
        )

    def open_table() -> None:
        nonlocal table_idx, row_idx, component, active, header_seen
        table_idx += 1
        row_idx = 0
        component = ""
        active = True
        header_seen = False

    for raw_line in lines:
        line = _clean_line(raw_line)
        if not line:
            continue
        if closed:
            kind = "comment" if _is_comment(line) else "unparsed"
            add_note(kind, line, "comment" if kind == "comment" else "closed_block", in_table=False)
            continue

        subhead = _subhead_number(line)
        if subhead is not None:
            if subhead >= 3:
                closed = True
                active = False
                add_note("unparsed", line, "supervision_block", in_table=False)
                continue
            if subhead in (1, 2):
                open_table()
                continue

        if "|" not in line:
            if _is_comment(line):
                add_note("comment", line, "comment", in_table=False)
            elif active and header_seen:
                add_note("unparsed", line, "orphan_line", in_table=True)
            else:
                add_note("unparsed", line, "outside_table", in_table=False)
            continue

        if _is_nonstandard_header(line):
            closed = True
            active = False
            add_note("unparsed", line, "nonstandard_header", in_table=False)
            continue

        if _is_standard_header(line):
            # 헤더를 이미 본 표에서 표준 헤더가 다시 나오면 새 표다. 1)/2)와 같다.
            if header_seen or not active:
                open_table()
            header_seen = True
            tables_with_header.add(table_idx)
            continue

        cells = _split_cells(line)
        if _is_pipe_comment(cells):
            add_note("comment", line, "comment", in_table=False)
            continue

        if not header_seen:
            add_note("unparsed", line, "before_header", in_table=False)
            continue

        assembled = _assemble(cells, component)
        if assembled is None:
            add_note("unparsed", line, _unparsed_reason(cells), in_table=True)
            continue
        component = assembled[0]
        status, source_cells = assembled[4], assembled[5]
        rows.append(
            LogicalRow(
                table_idx=table_idx,
                row_idx=row_idx,
                component=assembled[0],
                action_date=assembled[1],
                finding=assembled[2],
                action=assembled[3],
                parse_status=status,
                source_cells=source_cells,
            )
        )
        row_idx += 1

    status = _document_status(rows)
    return RemediationParseResult(
        rcept_no=rcept_no,
        corp_code=corp_code,
        status=status,
        n_tables=len(tables_with_header),
        rows=rows,
        notes=notes,
    )


def _subsection_lines(body_text: str) -> list[str] | None:
    """소제목 2 다음 줄부터 반환한다. 소제목이 없으면 None."""
    lines = body_text.splitlines()
    for index, line in enumerate(lines):
        if _SUBSECTION_LINE.match(_clean_line(line)):
            return lines[index + 1 :]
    earliest: int | None = None
    phrase_length = 0
    for phrase in _SUBSECTION_PHRASES:
        found = body_text.find(phrase)
        if found != -1 and (earliest is None or found < earliest):
            earliest = found
            phrase_length = len(phrase)
    if earliest is None:
        return None
    return body_text[earliest + phrase_length :].splitlines()


def _clean_line(line: str) -> str:
    """비교용으로 끝 공백과 특수 공백을 정리한다."""
    return line.replace("\u00a0", " ").replace("\u3000", " ").strip()


def _compact(value: str) -> str:
    """공백을 모두 뺀 비교 문자열."""
    return re.sub(r"\s+", "", value)


def _split_cells(line: str) -> list[str]:
    """반각 파이프만 칸 구분자로 쓴다."""
    return [part.strip() for part in line.split("|")]


def _subhead_number(line: str) -> int | None:
    """``1)`` ``2)`` ``3)`` 소제목 번호. 파이프 행은 소제목이 아니다."""
    if "|" in line:
        return None
    match = _SUBHEAD.match(line)
    if match is None:
        return None
    return int(match.group(1))


def _is_comment(line: str) -> bool:
    """표 밖 주석·안내 문장인지 본다."""
    return _STAR_LINE.match(line) is not None or _COMMENT.search(line) is not None


def _is_pipe_comment(cells: list[str]) -> bool:
    """첫 칸이 ``(주)`` 같은 주석 표식인 파이프 줄. 긴 권고 문장은 빼지 않는다."""
    if not cells:
        return False
    head = _compact(cells[0])
    if head in _COMMENT_HEADS:
        return True
    return len(head) <= 8 and _is_comment(cells[0])


def _is_standard_header(line: str) -> bool:
    """표준 개선권고 헤더. 첫 칸이 구성요소명인 데이터 행은 제외한다."""
    compact = _compact(line)
    if compact == _HEADER_EXACT:
        return True
    cells = _split_cells(line)
    if not cells or _compact(cells[0]) != "구분":
        return False
    return all(token in compact for token in _HEADER_TOKENS)


def _is_nonstandard_header(line: str) -> bool:
    """감리 조치 표 헤더. 개선권고 논리 행으로 바꾸지 않는다."""
    return "감리지적사항" in line and "조치내역" in line


def _is_group_label(cell: str) -> bool:
    return _compact(cell) == "품질관리구성요소"


def _is_date(cell: str) -> bool:
    return _DATE.match(cell.strip()) is not None


def is_blank_cell(cell: str) -> bool:
    """권고·이행 칸이 비어 있는지. 감싼 따옴표만 걷고, 긴 문장 안은 건드리지 않는다."""
    text = cell.strip()
    while len(text) >= 2 and text[0] in _WRAPPING_QUOTES and text[-1] in _WRAPPING_QUOTES:
        text = text[1:-1].strip()
    return _compact(text) in _BLANK_VALUES


def _filled_status(finding: str, action: str, filled: str) -> str:
    if is_blank_cell(finding) and is_blank_cell(action):
        return "empty"
    return filled


def _assemble(cells: list[str], component: str) -> tuple[str, str, str, str, str, int] | None:
    """칸 배열을 (구분, 조치일자, 개선권고, 이행, 상태, 원본 칸 수)로 맞춘다."""
    count = len(cells)
    if count == 5 and _is_group_label(cells[0]):
        comp = cells[1]
        action_date, finding, action = cells[2], cells[3], cells[4]
        return (comp, action_date, finding, action, _filled_status(finding, action, "ok"), 5)
    if count == 4 and is_blank_cell(cells[0]):
        action_date, finding, action = cells[1], cells[2], cells[3]
        status = _filled_status(finding, action, "ok")
        return (component, action_date, finding, action, status, 4)
    if count == 4 and not _is_date(cells[0]):
        comp = cells[0]
        action_date, finding, action = cells[1], cells[2], cells[3]
        status = _filled_status(finding, action, "ok")
        return (comp, action_date, finding, action, status, 4)
    if count == 3:
        action_date, finding, action = cells[0], cells[1], cells[2]
        status = _filled_status(finding, action, "continuation_merged")
        return (component, action_date, finding, action, status, 3)
    return None


def _unparsed_reason(cells: list[str]) -> str:
    if len(cells) == 5 and not _is_group_label(cells[0]):
        return "not_group_label"
    if len(cells) == 4 and _is_date(cells[0]):
        return "date_in_first_cell"
    return "bad_cell_count"


def _document_status(rows: list[LogicalRow]) -> str:
    """권고 또는 이행이 있는 논리 행이 하나라도 있으면 table이다."""
    for row in rows:
        if not is_blank_cell(row.finding) or not is_blank_cell(row.action):
            return "table"
    return "empty"
