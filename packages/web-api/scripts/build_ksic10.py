"""제10차 분류 엑셀을 ksic10.json으로 변환한다."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from app.ksic import KSIC_PATH, dump_ksic_table, table_from_hierarchy_rows

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _col_row(cell_ref: str) -> tuple[int, int]:
    """A1 주소를 0부터의 열·행 인덱스로 바꾼다."""
    col = ""
    row = ""
    for char in cell_ref:
        if char.isalpha():
            col += char
        else:
            row += char
    number = 0
    for char in col:
        number = number * 26 + (ord(char.upper()) - 64)
    return number - 1, int(row) - 1


def read_first_sheet_rows(path: Path) -> list[list[object | None]]:
    """xlsx 첫 시트를 행 목록으로 읽는다. 수식 대신 저장된 값을 쓴다."""
    with zipfile.ZipFile(path) as archive:
        strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("m:si", _NS):
                strings.append("".join(node.text or "" for node in item.findall(".//m:t", _NS)))
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        first = workbook.find("m:sheets/m:sheet", _NS)
        if first is None:
            raise ValueError("엑셀에 시트가 없습니다.")
        rid = first.attrib.get(f"{_REL_NS}id")
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = None
        for rel in rels:
            if rel.attrib.get("Id") == rid:
                target = rel.attrib.get("Target")
                break
        if not target:
            raise ValueError("첫 시트 경로를 찾지 못했습니다.")
        if not target.startswith("xl/"):
            target = "xl/" + target.lstrip("/")
        sheet = ET.fromstring(archive.read(target))
        cells: dict[int, dict[int, object | None]] = {}
        max_r = 0
        max_c = 0
        for cell in sheet.findall(".//m:c", _NS):
            ref = cell.attrib.get("r")
            if not ref:
                continue
            col_i, row_i = _col_row(ref)
            max_r = max(max_r, row_i)
            max_c = max(max_c, col_i)
            kind = cell.attrib.get("t")
            value_node = cell.find("m:v", _NS)
            value: object | None = value_node.text if value_node is not None else None
            if kind == "s" and value is not None:
                value = strings[int(value)]
            inline = cell.find("m:is", _NS)
            if inline is not None:
                value = "".join(node.text or "" for node in inline.findall(".//m:t", _NS))
            cells.setdefault(row_i, {})[col_i] = value
    rows: list[list[object | None]] = []
    width = max(10, max_c + 1)
    for row_i in range(max_r + 1):
        rows.append([cells.get(row_i, {}).get(col_i) for col_i in range(width)])
    return rows


def data_rows(rows: list[list[object | None]]) -> list[list[object | None]]:
    """제목·머리글을 건너뛰고 코드 행만 남긴다."""
    start = 0
    for index, row in enumerate(rows):
        first = str(row[0]).strip() if row and row[0] is not None else ""
        if first == "A":
            start = index
            break
    return rows[start:]


def build_parser() -> argparse.ArgumentParser:
    """입력 엑셀과 출력 JSON 경로를 받는다."""
    parser = argparse.ArgumentParser(description="KSIC 제10차 분류표를 ksic10.json으로 만듭니다.")
    parser.add_argument("xlsx", type=Path, help="한국표준산업분류10차_표.xlsx 경로")
    parser.add_argument(
        "--out",
        type=Path,
        default=KSIC_PATH,
        help="출력 JSON. 기본값은 앱 코드표 경로입니다.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """엑셀을 읽어 코드표를 덮어쓴다."""
    args = build_parser().parse_args(argv)
    rows = data_rows(read_first_sheet_rows(args.xlsx))
    table = table_from_hierarchy_rows(rows)
    payload = dump_ksic_table(table)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"코드 {len(table)}개를 {args.out}에 썼습니다.")


if __name__ == "__main__":
    main()
