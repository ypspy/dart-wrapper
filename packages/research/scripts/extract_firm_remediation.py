"""Ⅵ-2 개선권고 이행 표를 JSONL에서 읽어 집계하거나 연구 DB에 저장한다.

기본은 dry-run이다. 대상 DB에 쓰려면 ``--write --target-db``를 함께 준다.
LLM과 DART 네트워크는 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from research.services.firm_remediation_loader import FirmRemediationError
from research.services.firm_remediation_service import SUMMARY_KEYS, run_firm_remediation


def build_parser() -> argparse.ArgumentParser:
    """입력·카탈로그·쓰기 여부를 받는다."""
    parser = argparse.ArgumentParser(
        description=(
            "회계법인 사업보고서 Ⅵ 소제목 2의 개선권고 이행 표를 집계합니다. "
            "기본은 dry-run이며 DB에 쓰지 않습니다."
        )
    )
    parser.add_argument("--input", required=True, help="JSONL 파일 또는 그 파일이 있는 디렉터리")
    parser.add_argument(
        "--catalog",
        default=None,
        help="읽기 전용 dart_catalog.db. year_end로 period_key를 보완합니다.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="집계만 출력합니다. 생략해도 --write가 없으면 dry-run입니다.",
    )
    parser.add_argument("--write", action="store_true", help="대상 DB에 현재 파싱을 저장합니다.")
    parser.add_argument("--target-db", default=None, help="--write 일 때 기록할 SQLite 경로")
    return parser


async def _run(args: argparse.Namespace) -> dict[str, int]:
    """인자를 서비스 호출로 바꾼다."""
    if args.write and args.dry_run:
        raise FirmRemediationError(
            "쓰기와 dry-run을 동시에 지정할 수 없습니다. "
            "기본은 dry-run이고, 저장은 --write --target-db 입니다."
        )
    return await run_firm_remediation(
        input_path=Path(args.input),
        catalog_path=Path(args.catalog) if args.catalog else None,
        write=bool(args.write),
        target_db=Path(args.target_db) if args.target_db else None,
    )


def main(argv: list[str] | None = None) -> int:
    """집계 JSON을 표준 출력에 찍고, 실패하면 0이 아닌 코드로 끝낸다."""
    args = build_parser().parse_args(argv)
    try:
        summary = asyncio.run(_run(args))
    except FirmRemediationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    ordered = {key: summary[key] for key in SUMMARY_KEYS}
    json.dump(ordered, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
