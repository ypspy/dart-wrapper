"""원문 캐시 계획·박스 복사·누락 목록. DART 수집 명령은 두지 않는다."""

from __future__ import annotations

import argparse
from pathlib import Path

from research.gold.cache import (
    CACHE_ROOT,
    import_from_box,
    plan_cache,
    write_missing_list,
)
from research.gold.db import open_gold


def main(argv: list[str] | None = None) -> None:
    """plan, import, missing 중 하나를 실행한다."""
    parser = argparse.ArgumentParser(description="골드 원문 캐시를 준비합니다.")
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--run", default="gold-2026-10")
    parser.add_argument("--cache", type=Path, default=CACHE_ROOT)
    parser.add_argument("--box", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    sub.add_parser("import")
    missing = sub.add_parser("missing")
    missing.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    conn = open_gold(args.gold, args.catalog)
    try:
        plan = plan_cache(conn, args.run, args.cache, args.box)
        if args.command == "plan":
            print(
                f"캐시 {len(plan.present)}건, 박스 {len(plan.from_box)}건, "
                f"없음 {len(plan.missing)}건"
            )
            return
        if args.command == "import":
            copied = import_from_box(plan)
            print(f"박스에서 복사 {copied}건")
            return
        write_missing_list(plan, args.out)
        print(f"누락 목록 {len(plan.missing)}건 → {args.out}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
