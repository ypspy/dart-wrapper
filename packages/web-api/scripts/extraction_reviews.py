"""12묶음 추출 진단과 검토 TSV를 주고받는다."""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path
from typing import TextIO

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.session import create_db_engine, create_sessionmaker
from app.reviewing.candidates import SummaryRow, format_summary
from app.services.extraction_review_service import (
    EXPORT_COLUMNS,
    ExtractionReviewError,
    diagnose,
    export_tsv,
    import_tsv,
)


def build_parser() -> argparse.ArgumentParser:
    """진단 CLI. 하위 명령은 diagnose, export-tsv, import-tsv."""
    parser = argparse.ArgumentParser(description="12묶음 추출 진단")
    parser.add_argument(
        "--database-url",
        default=Settings().database_url,
        help="SQLAlchemy DB URL. 기본값은 앱 Settings와 같습니다.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    diagnose_parser = sub.add_parser("diagnose", help="후보를 계산해 검토 테이블에 맞춥니다.")
    diagnose_parser.add_argument("--summary-out", default=None, help="요약 TSV 경로.")
    export_parser = sub.add_parser("export-tsv", help="활성 검토 행을 TSV로 내보냅니다.")
    export_parser.add_argument("--out", default=None, help="출력 파일 경로. 생략하면 표준 출력.")
    export_parser.add_argument(
        "--next", dest="next_slice", action="store_true", help="다음 IQR 구간."
    )
    import_parser = sub.add_parser("import-tsv", help="판정·태그·메모만 다시 적재합니다.")
    import_parser.add_argument("--in", dest="path", required=True, help="입력 TSV 경로.")
    return parser


def _reconfigure_stdout() -> None:
    """표준 출력을 UTF-8로 맞춘다. 지원하지 않으면 그대로 둔다."""
    stdout = sys.stdout
    reconfigure = getattr(stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def _write_export(rows: list[dict[str, str]], dest: TextIO) -> None:
    """헤더는 항상 EXPORT_COLUMNS. 탭과 LF로 쓴다."""
    writer = csv.writer(dest, delimiter="\t", lineterminator="\n")
    writer.writerow(EXPORT_COLUMNS)
    for row in rows:
        writer.writerow(row[column] for column in EXPORT_COLUMNS)


def _write_summary(rows: list[SummaryRow], dest: TextIO) -> None:
    """요약 TSV. 헤더는 section, key, n, detail."""
    writer = csv.writer(dest, delimiter="\t", lineterminator="\n")
    writer.writerow(("section", "key", "n", "detail"))
    for row in rows:
        writer.writerow((row.section, row.key, row.n, row.detail))


async def _diagnose(
    sessionmaker: async_sessionmaker[AsyncSession],
    summary_out: str | None,
) -> None:
    """진단을 저장하고 요약을 표준 출력과 선택적 TSV에 쓴다."""
    async with sessionmaker() as session:
        summary = await diagnose(session)
        await session.commit()
    _reconfigure_stdout()
    for row in summary:
        print(format_summary(row))
    if summary_out is None:
        return
    with Path(summary_out).open("w", encoding="utf-8", newline="") as handle:
        _write_summary(summary, handle)


async def _export(
    sessionmaker: async_sessionmaker[AsyncSession],
    out: str | None,
    next_slice: bool,
) -> None:
    """검토 TSV를 파일 또는 표준 출력에 쓴다. 행이 없어도 헤더는 쓴다."""
    async with sessionmaker() as session:
        rows = await export_tsv(session, next_slice=next_slice)
    if next_slice and not rows:
        print("소스와 로직이 같이 있는 층이 없습니다.", file=sys.stderr)
    if out is None:
        _reconfigure_stdout()
        _write_export(rows, sys.stdout)
        return
    with Path(out).open("w", encoding="utf-8", newline="") as handle:
        _write_export(rows, handle)


async def _import(sessionmaker: async_sessionmaker[AsyncSession], path: str) -> None:
    """UTF-8 TSV의 판정을 반영하고 commit한다. 오류면 rollback한다."""
    text = Path(path).read_text(encoding="utf-8")
    async with sessionmaker() as session:
        try:
            await import_tsv(session, text)
            await session.commit()
        except ExtractionReviewError:
            await session.rollback()
            raise


async def _dispatch(args: argparse.Namespace, next_slice: bool) -> None:
    """엔진을 열고 하위 명령을 실행한 뒤 닫는다."""
    engine = create_db_engine(args.database_url)
    sessionmaker = create_sessionmaker(engine)
    try:
        if args.command == "diagnose":
            await _diagnose(sessionmaker, args.summary_out)
            return
        if args.command == "export-tsv":
            await _export(sessionmaker, args.out, next_slice)
            return
        await _import(sessionmaker, args.path)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    """CLI 진입점. 진단·적재 오류는 표준 오류에 적고 종료 코드 1로 끝낸다."""
    args = build_parser().parse_args(argv)
    next_slice = getattr(args, "next_slice", False)
    try:
        asyncio.run(_dispatch(args, next_slice))
    except ExtractionReviewError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
