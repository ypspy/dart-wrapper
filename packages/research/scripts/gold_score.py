"""골드 재채점과 정밀도 CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from research.extracting.constants import EXTRACTOR_VERSION
from research.gold.db import open_gold
from research.gold.scoring import metrics, score


def main(argv: list[str] | None = None) -> None:
    """스냅샷으로 다시 채점하고 정밀도 CSV를 쓴다."""
    parser = argparse.ArgumentParser(description="골드 정밀도를 계산합니다.")
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--version", default=EXTRACTOR_VERSION)
    parser.add_argument("--run", default="gold-2026-10")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    conn = open_gold(args.gold, None)
    try:
        written = score(conn, args.version)
        rows = metrics(conn, args.run, args.version)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "scope",
                    "period",
                    "bundle",
                    "subject",
                    "n_claim",
                    "tp",
                    "fp",
                    "precision",
                    "wilson_lo",
                    "wilson_hi",
                    "weighted_lo",
                    "passed",
                    "flag_period_report",
                    "note",
                ]
            )
            for row in rows:
                writer.writerow(
                    [
                        row.scope,
                        row.period,
                        row.bundle,
                        row.subject,
                        row.n_claim,
                        row.tp,
                        row.fp,
                        f"{row.precision:.6f}",
                        f"{row.lo:.6f}",
                        f"{row.hi:.6f}",
                        f"{row.weighted_lo:.6f}",
                        int(row.passed),
                        int(row.flag_period_report),
                        row.note,
                    ]
                )
        print(f"채점 {written}건, 지표 {len(rows)}행 → {args.out}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
