"""골드 표본 생성 CLI. 실카탈로그 실행은 확인 후에만 한다."""

from __future__ import annotations

import argparse
from pathlib import Path

from research.gold.db import migrate, open_gold
from research.gold.sampler import SampleParams, build_sample, render_stats


def main(argv: list[str] | None = None) -> None:
    """gold.db에 층화 표본을 쓴다. 카탈로그는 읽기 전용으로만 연다."""
    parser = argparse.ArgumentParser(description="골드 층화 표본을 만듭니다.")
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--seed", default="gold-2026-10")
    parser.add_argument("--per-period", type=int, default=400)
    args = parser.parse_args(argv)
    conn = open_gold(args.gold, args.catalog)
    try:
        migrate(conn)
        run_id = build_sample(
            conn,
            SampleParams(seed=args.seed, per_period=args.per_period),
        )
        print(render_stats(conn, run_id))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
