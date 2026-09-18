"""KSIC 제10·11차 코드표로 OpenDART 업종코드에 이름을 붙인다."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

KSIC_PATH = Path(__file__).resolve().parent / "data" / "ksic10.json"
KSIC11_PATH = Path(__file__).resolve().parent / "data" / "ksic11.json"
_DIV_RANGE_SUFFIX = re.compile(r"\(\d{2}(?:~\d{2})?\)$")
_HIERARCHY: tuple[tuple[str, int, int, str | None], ...] = (
    ("div", 0, 1, None),
    ("group", 2, 3, "div"),
    ("class", 4, 5, "group"),
    ("subclass", 6, 7, "class"),
    ("item", 8, 9, "subclass"),
)
_LEVEL_FIELD = {
    "div": "induty_name_div",
    "group": "induty_name_group",
    "class": "induty_name_class",
    "subclass": "induty_name_subclass",
    "item": "induty_name_item",
}


@dataclass(frozen=True)
class KsicEntry:
    """코드표 한 줄."""

    name: str
    parent: str | None
    level: str


@dataclass(frozen=True)
class KsicNames:
    """회사 행에 붙일 계층 이름. 없는 단계는 None."""

    induty_name_div: str | None = None
    induty_name_group: str | None = None
    induty_name_class: str | None = None
    induty_name_subclass: str | None = None
    induty_name_item: str | None = None


def strip_division_range(name: str) -> str:
    """대분류 이름 끝의 중분류 범위 표기 `(10~34)`·`(35)`를 뗀다."""
    return _DIV_RANGE_SUFFIX.sub("", name.strip()).strip()


def _cell(value: object | None) -> str | None:
    """엑셀 칸을 빈 문자열·nbsp 없이 정규화한다."""
    if value is None:
        return None
    text = str(value).replace("\xa0", " ").strip()
    return text or None


def table_from_hierarchy_rows(
    rows: Sequence[Sequence[object | None]],
) -> dict[str, KsicEntry]:
    """10열(대·중·소·세·세세 코드/이름) 행을 parent가 있는 코드표로 만든다."""
    carry: dict[str, str | None] = {level: None for level, *_ in _HIERARCHY}
    table: dict[str, KsicEntry] = {}
    for row in rows:
        cells = list(row) + [None] * max(0, 10 - len(row))
        for level, code_i, name_i, parent_level in _HIERARCHY:
            code = _cell(cells[code_i] if code_i < len(cells) else None)
            name = _cell(cells[name_i] if name_i < len(cells) else None)
            if not code:
                continue
            carry[level] = code
            parent = carry[parent_level] if parent_level else None
            if level == "div":
                name = strip_division_range(name or "")
            table[code] = KsicEntry(name=name or "", parent=parent, level=level)
    return table


def hierarchy_rows_from_ksic11_link(
    sheet_rows: Sequence[Sequence[object | None]],
) -> list[list[object | None]]:
    """11차 연계표에서 오른쪽 표준산업분류만 10열 계층 행으로 뽑는다."""
    rows: list[list[object | None]] = []
    for raw in sheet_rows[5:]:
        cells = list(raw) + [None] * max(0, 23 - len(raw))
        if not _cell(cells[13] if len(cells) > 13 else None):
            continue
        rows.append(
            [
                cells[14],
                cells[15],
                cells[16],
                cells[17],
                cells[18],
                cells[19],
                cells[20],
                cells[21],
                cells[13],
                cells[22],
            ]
        )
    return rows


def dump_ksic_table(table: dict[str, KsicEntry]) -> dict[str, dict[str, str | None]]:
    """JSON으로 쓸 수 있게 코드표를 직렬화한다."""
    return {
        code: {"name": entry.name, "parent": entry.parent, "level": entry.level}
        for code, entry in table.items()
    }


def load_ksic_table(path: Path | None = None) -> dict[str, KsicEntry]:
    """JSON 코드표를 읽어 코드 → 항목 사전을 만든다."""
    payload = json.loads((path or KSIC_PATH).read_text(encoding="utf-8"))
    table: dict[str, KsicEntry] = {}
    for code, raw in payload.items():
        parent = raw.get("parent")
        table[str(code)] = KsicEntry(
            name=str(raw["name"]),
            parent=str(parent) if parent else None,
            level=str(raw["level"]),
        )
    return table


def load_ksic_tables() -> tuple[dict[str, KsicEntry], dict[str, KsicEntry]]:
    """OpenDART 조회용으로 11차·10차 표를 이 순서대로 반환한다."""
    return load_ksic_table(KSIC11_PATH), load_ksic_table(KSIC_PATH)


def names_for(code: str | None, table: dict[str, KsicEntry]) -> KsicNames:
    """정확 일치한 코드부터 parent를 따라 이름을 채운다. 없으면 전부 None."""
    if code is None:
        return KsicNames()
    normalized = code.strip()
    if not normalized or normalized not in table:
        return KsicNames()

    values: dict[str, str | None] = {field: None for field in _LEVEL_FIELD.values()}
    current: str | None = normalized
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        entry = table.get(current)
        if entry is None:
            break
        field = _LEVEL_FIELD.get(entry.level)
        if field is not None and values[field] is None:
            values[field] = entry.name
        current = entry.parent
    return KsicNames(**values)


def names_for_preferred(
    code: str | None, *tables: dict[str, KsicEntry]
) -> KsicNames:
    """앞 표에 코드가 있으면 그 표만 따라가고, 없으면 다음 표로 간다."""
    if code is None:
        return KsicNames()
    normalized = code.strip()
    if not normalized:
        return KsicNames()
    for table in tables:
        if normalized in table:
            return names_for(normalized, table)
    return KsicNames()
