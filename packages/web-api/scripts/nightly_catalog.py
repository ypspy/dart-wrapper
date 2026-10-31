"""야간 카탈로그 수집 스크립트.

스케줄러는 이 프로세스 밖에 둔다. Windows 작업 스케줄러나 cron이
아래 명령을 매일 새벽에 한 번 호출하면 된다.

    cd packages\\web-api
    .\\.venv\\Scripts\\python.exe scripts\\nightly_catalog.py --budget-minutes 240

동작은 한 머신에서 직렬이다.

1. 히트맵 유형마다 한국시간 어제까지 수집한다.
2. 시간이 남으면 1999-01-01 쪽으로 빈 날을 거슬러 올라간다.
3. 시간 한도나 연속 차단이면 작업을 부분 완료로 끝내고, 다음 실행이 이어 한다.
4. 오늘과 미래는 수집하지 않는다.

F004(회계법인사업보고서)를 2026-08-14부터 어제까지 다시 받으려면
야간 백필과 겹치지 않게 이 명령만 따로 실행한다.

    .\\.venv\\Scripts\\python.exe scripts\\nightly_catalog.py ^
        --recollect --report-type F004 --start 20260814

이미 완료로 닫힌 날도 목록부터 다시 본다. 성공한 접수번호는 다시 파싱하지 않고,
새로 나타난 접수만 붙인다. 종료일을 생략하면 한국시간 어제가 된다.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.adapters.node_entry_collector import NodeEntryCollector  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.session import create_db_engine, create_sessionmaker, ensure_schema  # noqa: E402
from app.services.catalog_service import CatalogService, parse_slice_date  # noqa: E402
from app.services.nightly_catalog import run_nightly, run_recollect  # noqa: E402
from app.services.slice_query_service import kst_today, last_closed_date  # noqa: E402

LOCK_PATH = ROOT / ".nightly.lock"


def build_parser() -> argparse.ArgumentParser:
    """야간 수집과 F004 같은 구간 재수집 인자를 만든다."""
    parser = argparse.ArgumentParser(
        description="한국시간 어제까지 카탈로그를 직렬로 수집하고, 시간이 남으면 과거를 채웁니다."
    )
    parser.add_argument(
        "--budget-minutes",
        type=float,
        default=240,
        help="이번 실행의 시간 한도(분). 0이면 한도 없이 돈다. 기본 240.",
    )
    parser.add_argument(
        "--report-types",
        default="",
        help="쉼표로 구분한 공시 유형. 비우면 HEATMAP_REPORT_TYPES.",
    )
    parser.add_argument(
        "--floor",
        default="19990101",
        help="백필이 멈추는 가장 이른 날 YYYYMMDD. 기본 19990101.",
    )
    parser.add_argument(
        "--no-backfill",
        action="store_true",
        help="어제를 유형별로 채우기만 하고 과거로 내려가지 않는다.",
    )
    parser.add_argument(
        "--recollect",
        action="store_true",
        help="완료된 날을 포함해 --start부터 어제까지 한 유형만 다시 수집한다.",
    )
    parser.add_argument("--report-type", default="F004", help="재수집 유형. 기본 F004.")
    parser.add_argument("--start", default="20260814", help="재수집 시작일 YYYYMMDD.")
    parser.add_argument(
        "--end",
        default="",
        help="재수집 종료일 YYYYMMDD. 비우면 한국시간 어제.",
    )
    parser.add_argument("--database-url", default="", help="비우면 설정의 DATABASE_URL.")
    return parser


def _pid_alive(pid: int) -> bool:
    """프로세스가 아직 있는지 본다."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _acquire_lock() -> bool:
    """다른 야간 수집이 살아 있으면 끝낸다.

    반환이 참이면 이전 프로세스가 죽어 잠금이 남아 있던 것이다.
    """
    recovered = False
    if LOCK_PATH.exists():
        raw = LOCK_PATH.read_text(encoding="utf-8").strip()
        try:
            pid = int(raw)
        except ValueError:
            pid = -1
        if pid > 0 and _pid_alive(pid):
            print(f"이미 야간 수집이 실행 중입니다 (pid {pid}). 이번 실행은 건너뜁니다.")
            raise SystemExit(0)
        LOCK_PATH.unlink(missing_ok=True)
        recovered = True
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
    return recovered


def _release_lock() -> None:
    """이 프로세스가 만든 잠금만 지운다."""
    if not LOCK_PATH.exists():
        return
    if LOCK_PATH.read_text(encoding="utf-8").strip() == str(os.getpid()):
        LOCK_PATH.unlink(missing_ok=True)


def _report_types(raw: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    """쉼표 목록을 정규화한다. 비어 있으면 설정을 쓴다."""
    if not raw.strip():
        return fallback
    return tuple(dict.fromkeys(part.strip().upper() for part in raw.split(",") if part.strip()))


async def _run(args: argparse.Namespace, *, recovered: bool) -> int:
    """엔진을 열고 야간 수집 또는 구간 재수집을 실행한다."""
    settings = get_settings()
    database_url = args.database_url.strip() or settings.database_url
    engine = create_db_engine(database_url)
    await ensure_schema(engine)
    sessionmaker = create_sessionmaker(engine)
    collector = NodeEntryCollector(
        settings.node_executable,
        settings.entry_collector_script,
        timeout_seconds=settings.collector_timeout_seconds,
    )
    catalog = CatalogService(
        sessionmaker,
        collector,
        max_retries=settings.disclosure_max_retries,
        block_streak_threshold=settings.block_streak_threshold,
        block_wait_seconds=0.0,
    )
    yesterday = last_closed_date(as_of=kst_today())
    budget = None if args.budget_minutes == 0 else args.budget_minutes * 60
    # 죽은 잠금이면 직전에 멈춘 야간 잡을 바로 풀어 이어 한다.
    idle_seconds = 0.0 if recovered else 3600.0
    try:
        if args.recollect:
            end = parse_slice_date(args.end) if args.end.strip() else yesterday
            outcome = await run_recollect(
                catalog,
                sessionmaker,
                report_type=args.report_type.strip().upper(),
                start=parse_slice_date(args.start),
                end=end,
                yesterday=yesterday,
                budget_seconds=budget,
                idle_seconds=idle_seconds,
            )
        else:
            outcome = await run_nightly(
                catalog,
                sessionmaker,
                report_types=_report_types(args.report_types, settings.heatmap_report_type_list),
                yesterday=yesterday,
                floor=parse_slice_date(args.floor),
                budget_seconds=budget,
                backfill=not args.no_backfill,
                idle_seconds=idle_seconds,
            )
    finally:
        await engine.dispose()

    print(
        f"상태 {outcome.status}"
        f" / 멈춤 {outcome.stopped or '없음'}"
        f" / 작업 {outcome.job_id or '없음'}"
    )
    if outcome.message:
        print(outcome.message)
    if outcome.status == "failed":
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """인자를 읽고 잠금을 잡은 뒤 비동기 수집을 돌린다."""
    args = build_parser().parse_args(argv)
    recovered = _acquire_lock()
    try:
        return asyncio.run(_run(args, recovered=recovered))
    finally:
        _release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
