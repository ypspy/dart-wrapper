"""audit_report_facts를 entries/disclosures와 조인해 TSV로 내보낸다."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.session import create_db_engine, create_sessionmaker
from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
from app.models.entry import Entry
from app.models.extraction_review import ExtractionReview

JOIN_COLUMNS: tuple[str, ...] = (
    "corp_name",
    "year_end",
    "rcept_dt",
    "correction_type",
)
FACT_COLUMNS: tuple[str, ...] = tuple(column.name for column in AuditReportFact.__table__.columns)
COLUMN_NAMES: tuple[str, ...] = JOIN_COLUMNS + FACT_COLUMNS


def build_parser() -> argparse.ArgumentParser:
    """--database-url, --out, --with-reviews를 받는다. 최종 접수 필터는 두지 않는다."""
    parser = argparse.ArgumentParser(
        description=(
            "audit_report_facts를 회사명·결산월·접수일·정정구분과 함께 TSV로 내보냅니다. "
            "정정 전·후 접수를 모두 포함합니다."
        )
    )
    parser.add_argument(
        "--database-url",
        default=Settings().database_url,
        help="SQLAlchemy DB URL. 기본값은 앱 Settings와 같습니다.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="출력 파일 경로. 생략하면 표준 출력으로 씁니다.",
    )
    parser.add_argument(
        "--with-reviews",
        action="store_true",
        help="active 소스 태그를 source_tags 열로 붙입니다.",
    )
    return parser


async def _source_tags_by_document(
    session: AsyncSession,
) -> dict[tuple[str, str], str]:
    """active 소스 판정 중 태그가 있는 행을 문서별로 이어 붙인다.

    로직 판정과 빈 태그는 빼며, bundle·subject·tag 순으로 정렬해
    ``bundle:subject:tag``를 ``;``로 잇는다.
    """
    statement = select(
        ExtractionReview.rcept_no,
        ExtractionReview.dcm_no,
        ExtractionReview.bundle,
        ExtractionReview.subject,
        ExtractionReview.tag,
    ).where(
        ExtractionReview.active.is_(True),
        ExtractionReview.verdict == "source",
        ExtractionReview.tag != "",
    )
    result = await session.execute(statement)
    grouped: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    for rcept_no, dcm_no, bundle, subject, tag in result:
        grouped.setdefault((rcept_no, dcm_no), []).append((bundle, subject, tag))
    tags: dict[tuple[str, str], str] = {}
    for key, parts in grouped.items():
        ordered = sorted(parts)
        tags[key] = ";".join(f"{bundle}:{subject}:{tag}" for bundle, subject, tag in ordered)
    return tags


async def iter_rows(
    session: AsyncSession, *, with_reviews: bool = False
) -> Iterable[dict[str, Any]]:
    """facts 전 행을 카탈로그 필드와 조인해 dict로 반환한다.

    disclosure가 있으면 그 값을 쓰고, 없으면 같은 rcept_no·dcm_no entry로 폴백한다.
    최종 접수만 남기는 필터는 적용하지 않는다.
    with_reviews가 참이면 각 행에 source_tags 문자열을 붙인다. 맞는 태그가 없으면 빈 문자열이다.
    """
    entry_alias = (
        select(
            Entry.rcept_no,
            Entry.dcm_no,
            func.max(Entry.corp_name).label("corp_name"),
            func.max(Entry.year_end).label("year_end"),
            func.max(Entry.rcept_dt).label("rcept_dt"),
            func.max(Entry.correction_type).label("correction_type"),
        )
        .group_by(Entry.rcept_no, Entry.dcm_no)
        .subquery()
    )
    has_disclosure = Disclosure.rcept_no.is_not(None)

    def catalog_value(disc_col: Any, entry_col: Any, name: str) -> Any:
        """disclosure 행이 있으면 그 컬럼을 쓰고, 없으면 entry로 폴백한다."""
        return case((has_disclosure, disc_col), else_=entry_col).label(name)

    statement = (
        select(
            AuditReportFact,
            catalog_value(Disclosure.corp_name, entry_alias.c.corp_name, "corp_name"),
            catalog_value(Disclosure.year_end, entry_alias.c.year_end, "year_end"),
            catalog_value(Disclosure.rcept_dt, entry_alias.c.rcept_dt, "rcept_dt"),
            catalog_value(
                Disclosure.correction_type,
                entry_alias.c.correction_type,
                "correction_type",
            ),
        )
        .outerjoin(Disclosure, AuditReportFact.rcept_no == Disclosure.rcept_no)
        .outerjoin(
            entry_alias,
            (AuditReportFact.rcept_no == entry_alias.c.rcept_no)
            & (AuditReportFact.dcm_no == entry_alias.c.dcm_no),
        )
        .order_by(AuditReportFact.rcept_no, AuditReportFact.dcm_no)
    )
    result = await session.execute(statement)
    rows: list[dict[str, Any]] = []
    for fact, corp_name, year_end, rcept_dt, correction_type in result:
        row = {name: getattr(fact, name) for name in FACT_COLUMNS}
        row["corp_name"] = corp_name
        row["year_end"] = year_end
        row["rcept_dt"] = rcept_dt
        row["correction_type"] = correction_type
        rows.append(row)
    if with_reviews:
        tags_by_document = await _source_tags_by_document(session)
        for row in rows:
            key = (str(row["rcept_no"]), str(row["dcm_no"]))
            row["source_tags"] = tags_by_document.get(key, "")
    return rows


def _cell(value: Any) -> str:
    """TSV 칸 문자열. None은 빈 칸, JSON·날짜는 직렬화한다."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def write_tsv(
    rows: Sequence[dict[str, Any]],
    dest: TextIO,
    columns: Sequence[str] | None = None,
) -> None:
    """헤더와 행을 탭 구분으로 쓴다. columns가 없으면 COLUMN_NAMES를 쓴다."""
    names = COLUMN_NAMES if columns is None else columns
    writer = csv.writer(dest, delimiter="\t", lineterminator="\n")
    writer.writerow(names)
    for row in rows:
        writer.writerow(_cell(row.get(name)) for name in names)


async def _export(database_url: str, out: str | None, with_reviews: bool = False) -> None:
    """DB를 열어 TSV를 파일 또는 표준 출력에 쓴다."""
    engine = create_db_engine(database_url)
    sessionmaker = create_sessionmaker(engine)
    columns = (*COLUMN_NAMES, "source_tags") if with_reviews else None
    try:
        async with sessionmaker() as session:
            rows = list(await iter_rows(session, with_reviews=with_reviews))
        if out is None:
            stdout = sys.stdout
            reconfigure = getattr(stdout, "reconfigure", None)
            if callable(reconfigure):
                reconfigure(encoding="utf-8")
            write_tsv(rows, stdout, columns)
            return
        path = Path(out)
        with path.open("w", encoding="utf-8", newline="") as handle:
            write_tsv(rows, handle, columns)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    """CLI 진입점."""
    args = build_parser().parse_args(argv)
    asyncio.run(_export(args.database_url, args.out, args.with_reviews))


if __name__ == "__main__":
    main()
