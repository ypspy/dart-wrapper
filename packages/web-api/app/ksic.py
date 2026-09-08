"""KSIC 제10차 코드표로 OpenDART 업종코드에 이름을 붙인다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

KSIC_PATH = Path(__file__).resolve().parent / "data" / "ksic10.json"

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
