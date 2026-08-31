"""외부감사 실시내용 3절 주요감사실시내용 추출."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from app.extracting.activity_schedule import parse_headcount, parse_schedule
from app.extracting.table_matrix import expand_table_matrix
from app.extracting.text import compact

_HEADING_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6")
_DATE = re.compile(r"\d{2,4}\.\d{1,2}\.\d{1,2}")
_PADDING = {"", "#"}
_SECTION_RULES: tuple[tuple[str, str], ...] = (
    ("전반감사계획", "planning"),
    ("현장감사", "fieldwork"),
    ("재고자산실사", "inventory_observation"),
    ("금융자산실사", "financial_asset_observation"),
    ("외부조회", "external_confirmations"),
    ("지배기구와의커뮤니케이션", "tcwg_communication"),
    ("외부전문가", "expert"),
)
_OBSERVATION = {"inventory_observation", "financial_asset_observation"}
_KNOWN_LABELS = (
    "수행시기",
    "주요내용",
    "투입인원",
    "주요투입업무",
    "주요감사업무수행내용",
    "금융거래조회",
    "채권채무조회",
    "변호사조회",
    "기타조회",
    "커뮤니케이션횟수",
    "횟수",
    "수행내용",
    "감사활용내용",
)
_OBS_TIMING = "실사(입회)시기"
_OBS_PLACE = "실사(입회)장소"
_OBS_TARGET = "실사(입회)대상"


def extract_activities(html: str) -> tuple[list[dict[str, object]], str]:
    """3절 표를 회차·항목 목록으로 읽는다.

    표를 찾으면 칸이 '-'이거나 비어도 상태는 ok다.
    제목과 표가 없으면 not_found와 빈 목록이다.
    """
    soup = BeautifulSoup(html, "lxml")
    table = _find_activities_table(soup)
    if table is None:
        return [], "not_found"
    return _parse_matrix(expand_table_matrix(table)), "ok"


def _find_activities_table(soup: BeautifulSoup) -> Tag | None:
    """주요감사실시내용 제목 다음 표, 없으면 구분·내역 표를 고른다."""
    for node in soup.find_all(_HEADING_TAGS):
        if "주요감사실시내용" not in compact(node.get_text()):
            continue
        table = node.find_next("table")
        if table is not None:
            return table
    for table in soup.find_all("table"):
        matrix = expand_table_matrix(table)
        if not matrix:
            continue
        tokens = [compact(cell) for cell in matrix[0]]
        blob = "".join(tokens)
        if "구분" in blob and "내역" in blob and "투입인원수" not in blob:
            return table
    return None


def _parse_matrix(matrix: list[list[str]]) -> list[dict[str, object]]:
    """펼친 격자를 섹션별로 회차·블록으로 읽는다."""
    activities: list[dict[str, object]] = []
    section = ""
    section_raw = ""
    current_block: dict[str, object] | None = None
    current_visit: dict[str, object] | None = None
    fw_kinds: list[str] = []
    fw_subs: list[str] = []
    fw_work_label = "주요 감사업무 수행내용"
    obs_had_label = False
    obs_unmapped: list[str] = []

    def close_observation() -> None:
        nonlocal current_visit, obs_had_label, obs_unmapped
        _close_observation_visit(activities, current_visit)
        if not obs_had_label and obs_unmapped:
            activities.append(_unmapped_block(section, section_raw, obs_unmapped))
        current_visit = None
        obs_had_label = False
        obs_unmapped = []

    for row in matrix:
        if _is_table_header(row) or _is_blank(row):
            continue
        col0 = row[0] if row else ""
        token0 = compact(col0)
        if token0 not in _PADDING:
            new_section, new_raw = _section_of(col0)
            if (new_section, new_raw) != (section, section_raw):
                if section in _OBSERVATION:
                    close_observation()
                current_block = None
                current_visit = None
                fw_kinds = []
                fw_subs = []
                section, section_raw = new_section, new_raw

        if not section:
            continue
        if section == "fieldwork":
            current_visit, fw_kinds, fw_subs, fw_work_label = _consume_fieldwork_row(
                activities,
                row,
                section_raw,
                current_visit,
                fw_kinds,
                fw_subs,
                fw_work_label,
            )
            continue
        if section in _OBSERVATION:
            current_visit, had, leftover = _consume_observation_row(
                activities, row, section, section_raw, current_visit
            )
            obs_had_label = obs_had_label or had
            obs_unmapped.extend(leftover)
            continue
        current_block = _consume_block_row(activities, row, section, section_raw, current_block)

    if section in _OBSERVATION:
        close_observation()
    return activities


def _section_of(raw: str) -> tuple[str, str]:
    """1열 compact로 section 키를 고른다. 모르면 other다."""
    token = compact(raw)
    for needle, key in _SECTION_RULES:
        if needle in token:
            return key, raw.strip()
    return "other", raw.strip()


def _is_table_header(row: list[str]) -> bool:
    """구분·내역 표 머리행은 섹션이 아니다."""
    if not row:
        return False
    tokens = [compact(cell) for cell in row]
    return tokens[0] == "구분" and any("내역" in token for token in tokens)


def _is_blank(row: list[str]) -> bool:
    """펼친 뒤에도 의미 칸이 없는 행이다."""
    return all(compact(cell) in _PADDING for cell in row)


def _consume_fieldwork_row(
    activities: list[dict[str, object]],
    row: list[str],
    section_raw: str,
    current_visit: dict[str, object] | None,
    fw_kinds: list[str],
    fw_subs: list[str],
    fw_work_label: str,
) -> tuple[dict[str, object] | None, list[str], list[str], str]:
    """현장감사 헤더·회차 행을 원소화한다. '-'만 있는 줄은 건너뛴다."""
    if _is_fieldwork_column_header(row):
        labels, kinds, work_label = _fieldwork_header_labels(row)
        activities.append(
            {
                "section": "fieldwork",
                "section_raw": section_raw,
                "row_type": "column_header",
                "labels": labels,
            }
        )
        return None, kinds, fw_subs, work_label
    if _is_fieldwork_sub_header(row):
        labels, subs = _fieldwork_sub_labels(row)
        activities.append(
            {
                "section": "fieldwork",
                "section_raw": section_raw,
                "row_type": "sub_header",
                "parent_label": "투입인원",
                "labels": labels,
            }
        )
        return current_visit, fw_kinds, subs, fw_work_label
    if not _row_has_date(row) and _row_is_dash_only(row):
        return current_visit, fw_kinds, fw_subs, fw_work_label
    if _row_has_date(row):
        visit = _fieldwork_visit(row, section_raw, fw_kinds, fw_subs, fw_work_label)
        activities.append(visit)
        return visit, fw_kinds, fw_subs, fw_work_label
    if current_visit is not None:
        extra = _fieldwork_visit(row, section_raw, fw_kinds, fw_subs, fw_work_label)
        _merge_fieldwork_fields(current_visit["fields"], extra["fields"])
    return current_visit, fw_kinds, fw_subs, fw_work_label


def _is_fieldwork_column_header(row: list[str]) -> bool:
    """수행시기·투입인원·수행내용 헤더 행이면 True다."""
    tokens = [compact(cell) for cell in row]
    has_when = any("수행시기" in token for token in tokens)
    has_people = any("투입인원" in token for token in tokens)
    has_work = any("주요감사업무수행내용" in token or token == "주요내용" for token in tokens)
    return has_when and has_people and has_work


def _is_fieldwork_sub_header(row: list[str]) -> bool:
    """상주·비상주 2행 헤더이면 True다. 비상주는 상주와 구분한다."""
    has_resident = False
    has_nonresident = False
    for cell in row:
        token = compact(cell)
        if "비상주" in token:
            has_nonresident = True
        elif "상주" in token:
            has_resident = True
    return has_resident and has_nonresident


def _fieldwork_header_labels(row: list[str]) -> tuple[list[str], list[str], str]:
    """구분 열을 뺀 헤더 라벨과 열 종류를 반환한다."""
    labels: list[str] = []
    kinds: list[str] = []
    work_label = "주요 감사업무 수행내용"
    for index, cell in enumerate(row):
        token = compact(cell)
        if index == 0 or token in _PADDING:
            kinds.append("")
            continue
        text = cell.strip()
        if not labels or labels[-1] != text:
            labels.append(text)
        if "수행시기" in token:
            kinds.append("수행시기")
        elif "투입인원" in token:
            kinds.append("투입인원")
        elif "주요감사업무수행내용" in token or token == "주요내용":
            kinds.append("수행내용")
            work_label = text
        else:
            kinds.append("")
    return labels, kinds, work_label


def _fieldwork_sub_labels(row: list[str]) -> tuple[list[str], list[str]]:
    """상주·비상주 열 위치를 기록한다."""
    labels: list[str] = []
    subs: list[str] = []
    for cell in row:
        token = compact(cell)
        if "비상주" in token:
            subs.append("비상주")
            if "비상주" not in labels:
                labels.append(cell.strip() or "비상주")
        elif "상주" in token:
            subs.append("상주")
            if "상주" not in labels:
                labels.append(cell.strip() or "상주")
        else:
            subs.append("")
    return labels, subs


def _fieldwork_visit(
    row: list[str],
    section_raw: str,
    fw_kinds: list[str],
    fw_subs: list[str],
    work_label: str,
) -> dict[str, object]:
    """수행시기·투입인원·수행내용을 한 회차 fields로 묶는다."""
    schedule_parts: list[str] = []
    work_parts: list[str] = []
    resident: str | None = None
    nonresident: str | None = None
    for index, cell in enumerate(row):
        if index == 0:
            continue
        token = compact(cell)
        kind = fw_kinds[index] if index < len(fw_kinds) else ""
        sub = fw_subs[index] if index < len(fw_subs) else ""
        if sub == "상주" and token not in _PADDING:
            resident = cell.strip()
        elif sub == "비상주" and token not in _PADDING:
            nonresident = cell.strip()
        elif kind == "수행시기" and token not in _PADDING:
            schedule_parts.append(cell.strip())
        elif kind == "수행내용" and token not in _PADDING:
            work_parts.append(cell.strip())
    fields: dict[str, object] = {}
    schedule_raw = _join_unique(schedule_parts)
    if schedule_raw:
        fields["수행시기"] = parse_schedule(schedule_raw)
    headcount: dict[str, object] = {}
    if resident is not None:
        headcount["상주"] = parse_headcount(resident)
    if nonresident is not None:
        headcount["비상주"] = parse_headcount(nonresident)
    if headcount:
        fields["투입인원"] = headcount
    work_raw = _join_unique(work_parts)
    if work_raw:
        fields[work_label] = work_raw
    return {
        "section": "fieldwork",
        "section_raw": section_raw,
        "row_type": "visit",
        "fields": fields,
    }


def _merge_fieldwork_fields(target: dict[str, object], extra: dict[str, object]) -> None:
    """같은 회차에 이어지는 상주·수행내용 칸을 붙인다."""
    for key, value in extra.items():
        if key == "투입인원" and isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key].update(value)
        elif key not in target:
            target[key] = value


def _consume_observation_row(
    activities: list[dict[str, object]],
    row: list[str],
    section: str,
    section_raw: str,
    current_visit: dict[str, object] | None,
) -> tuple[dict[str, object] | None, bool, list[str]]:
    """실사 시기 라벨마다 visit을 열고 장소·대상을 items에 붙인다."""
    had_label = False
    leftover: list[str] = []
    index = 1
    while index < len(row):
        token = compact(row[index])
        label = _observation_label(token)
        if label is None:
            if token not in _PADDING:
                leftover.append(row[index].strip())
            index += 1
            continue
        had_label = True
        value, index = _take_until_obs_label(row, index + 1)
        if label == _OBS_TIMING:
            current_visit = _close_observation_visit(activities, current_visit)
            current_visit = _new_observation_visit(section, section_raw)
            parsed = parse_schedule(value)
            current_visit["items"].append(
                {
                    "label": _OBS_TIMING,
                    "raw": parsed["raw"],
                    "start_date": parsed["start_date"],
                    "end_date": parsed["end_date"],
                    "days": parsed["days"],
                }
            )
            continue
        if current_visit is None:
            current_visit = _new_observation_visit(section, section_raw)
        elif label == _OBS_PLACE and _visit_has_item(current_visit, _OBS_PLACE):
            current_visit = _close_observation_visit(activities, current_visit)
            current_visit = _new_observation_visit(section, section_raw)
        current_visit["items"].append({"label": label, "raw": value})
    return current_visit, had_label, leftover if not had_label else []


def _new_observation_visit(section: str, section_raw: str) -> dict[str, object]:
    """실사 회차 하나를 만든다."""
    return {
        "section": section,
        "section_raw": section_raw,
        "row_type": "visit",
        "items": [],
    }


def _close_observation_visit(
    activities: list[dict[str, object]], visit: dict[str, object] | None
) -> None:
    """시기만 '-'인 빈 서식 칸은 버리고, 그 밖 회차는 목록에 넣는다."""
    if visit is None:
        return None
    if not _is_empty_timing_only(visit):
        activities.append(visit)
    return None


def _is_empty_timing_only(visit: dict[str, object]) -> bool:
    """시기만 '-'이고 장소·대상이 없으면 True다."""
    items = visit.get("items")
    if not isinstance(items, list) or len(items) != 1:
        return False
    item = items[0]
    if not isinstance(item, dict) or item.get("label") != _OBS_TIMING:
        return False
    return compact(str(item.get("raw", ""))) in {"", "-"}


def _visit_has_item(visit: dict[str, object], label: str) -> bool:
    """회차 items에 해당 라벨이 있으면 True다."""
    items = visit.get("items")
    if not isinstance(items, list):
        return False
    return any(isinstance(item, dict) and item.get("label") == label for item in items)


def _observation_label(token: str) -> str | None:
    """짧은 시기/장소/대상만으로는 매칭하지 않는다."""
    if _OBS_TIMING in token:
        return _OBS_TIMING
    if _OBS_PLACE in token:
        return _OBS_PLACE
    if _OBS_TARGET in token:
        return _OBS_TARGET
    return None


def _take_until_obs_label(row: list[str], start: int) -> tuple[str, int]:
    """다음 실사 라벨 전까지 값 칸을 이어 붙인다."""
    parts: list[str] = []
    index = start
    while index < len(row):
        token = compact(row[index])
        if _observation_label(token) is not None:
            break
        if token not in _PADDING:
            text = row[index].strip()
            if not parts or parts[-1] != text:
                parts.append(text)
        index += 1
    return " ".join(parts), index


def _consume_block_row(
    activities: list[dict[str, object]],
    row: list[str],
    section: str,
    section_raw: str,
    current_block: dict[str, object] | None,
) -> dict[str, object]:
    """알려진 라벨 다음 칸을 fields에 넣고, 구분당 block 하나다."""
    if current_block is None:
        current_block = {
            "section": section,
            "section_raw": section_raw,
            "row_type": "block",
            "fields": {},
        }
        activities.append(current_block)
    fields = current_block["fields"]
    assert isinstance(fields, dict)
    fields.update(_block_fields(row, start_unmapped=_next_unmapped_index(fields)))
    return current_block


def _block_fields(row: list[str], start_unmapped: int) -> dict[str, object]:
    """알려진 라벨은 다음 칸, 남은 칸은 unmapped_N이다."""
    fields: dict[str, object] = {}
    consumed: set[int] = set()
    index = 1
    while index < len(row):
        token = compact(row[index])
        if token in _PADDING:
            index += 1
            continue
        if _known_label(token) is None:
            index += 1
            continue
        key = row[index].strip()
        value, next_index, value_at = _next_block_value(row, index + 1)
        consumed.add(index)
        if value_at is not None:
            consumed.add(value_at)
        fields[key] = value
        index = next_index
    unmapped_n = start_unmapped
    for index, cell in enumerate(row):
        if index == 0 or index in consumed:
            continue
        token = compact(cell)
        if token in _PADDING:
            continue
        fields[f"unmapped_{unmapped_n}"] = cell.strip()
        unmapped_n += 1
    return fields


def _next_block_value(row: list[str], start: int) -> tuple[str, int, int | None]:
    """다음 비어 있지 않은 칸을 값으로 쓴다. 다음 라벨은 소비하지 않는다."""
    index = start
    while index < len(row):
        token = compact(row[index])
        if token in _PADDING:
            index += 1
            continue
        if _known_label(token) is not None:
            return "", index, None
        return row[index].strip(), index + 1, index
    return "", index, None


def _known_label(token: str) -> str | None:
    """블록 알려진 라벨이면 그 키를 반환한다. 앞이 이긴다."""
    for label in _KNOWN_LABELS:
        if label in token:
            return label
    return None


def _next_unmapped_index(fields: dict[str, object]) -> int:
    """이미 쓴 unmapped 키 다음 번호를 반환한다."""
    used = [int(key.split("_")[1]) for key in fields if key.startswith("unmapped_")]
    return max(used, default=0) + 1


def _unmapped_block(section: str, section_raw: str, cells: list[str]) -> dict[str, object]:
    """실사 라벨이 하나도 없으면 칸을 unmapped로 접는다."""
    fields: dict[str, object] = {}
    unique: list[str] = []
    for cell in cells:
        if not unique or unique[-1] != cell:
            unique.append(cell)
    for index, cell in enumerate(unique, start=1):
        fields[f"unmapped_{index}"] = cell
    return {
        "section": section,
        "section_raw": section_raw,
        "row_type": "block",
        "fields": fields,
    }


def _row_has_date(row: list[str]) -> bool:
    """구분 열 이후에 날짜 표기가 있으면 True다."""
    return any(_DATE.search(cell) for cell in row[1:])


def _row_is_dash_only(row: list[str]) -> bool:
    """날짜 없이 '-'만 있는 빈 서식 줄이면 True다."""
    tokens = [compact(cell) for cell in row[1:] if compact(cell) not in _PADDING]
    return bool(tokens) and all(token == "-" for token in tokens)


def _join_unique(parts: list[str]) -> str:
    """colspan 복제 칸을 한 번만 이어 붙인다."""
    unique: list[str] = []
    for part in parts:
        if not part or compact(part) in _PADDING:
            continue
        if unique and unique[-1] == part:
            continue
        unique.append(part)
    return " ".join(unique)
