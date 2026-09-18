"""제11차 연계표 엑셀을 ksic11.json으로 변환한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.ksic import (
    KSIC11_PATH,
    dump_ksic_table,
    hierarchy_rows_from_ksic11_link,
    table_from_hierarchy_rows,
)
from build_ksic10 import read_first_sheet_rows


def build_parser() -> argparse.ArgumentParser:
    """입력 엑셀과 출력 JSON 경로를 받는다."""
    parser = argparse.ArgumentParser(
        description="KSIC 제11차 연계표에서 표준산업분류 칸을 ksic11.json으로 만듭니다."
    )
    parser.add_argument("xlsx", type=Path, help="한국표준 산업분류코드표 - 11차.xlsx 경로")
    parser.add_argument(
        "--out",
        type=Path,
        default=KSIC11_PATH,
        help="출력 JSON. 기본값은 앱 11차 코드표 경로입니다.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """엑셀을 읽어 11차 코드표를 덮어쓴다."""
    args = build_parser().parse_args(argv)
    sheet = read_first_sheet_rows(args.xlsx)
    table = table_from_hierarchy_rows(hierarchy_rows_from_ksic11_link(sheet))
    payload = dump_ksic_table(table)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"코드 {len(table)}개를 {args.out}에 썼습니다.")


if __name__ == "__main__":
    main()
