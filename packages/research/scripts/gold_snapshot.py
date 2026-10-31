"""골드 표본의 추출 스냅샷 CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from research.extracting.constants import EXTRACTOR_VERSION
from research.gold.db import open_gold
from research.gold.snapshots import capture


def main(argv: list[str] | None = None) -> None:
    """지정한 실행의 표본을 추출기 버전 스냅샷으로 복사한다."""
    parser = argparse.ArgumentParser(description="골드 문서 스냅샷을 저장합니다.")
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--run", default="gold-2026-10")
    parser.add_argument("--version", default=EXTRACTOR_VERSION)
    args = parser.parse_args(argv)
    conn = open_gold(args.gold, args.catalog)
    try:
        added = capture(conn, args.run, args.version)
        print(f"새로 저장한 스냅샷: {added}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
