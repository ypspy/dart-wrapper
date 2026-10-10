"""연구 테이블의 열 보정. 수집·열람 앱은 호출하지 않는다."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = logging.getLogger(__name__)

# (테이블명, 컬럼명, SQLite DDL 조각, PostgreSQL DDL 조각)
_COLUMN_PATCHES: tuple[tuple[str, str, str, str], ...] = (
    (
        "audit_report_facts",
        "hours",
        "TEXT NOT NULL DEFAULT '[]'",
        # text()가 :jsonb 를 바인드로 오인하지 않도록 콜론을 이스케이프한다.
        "JSONB NOT NULL DEFAULT '[]'\\:\\:jsonb",
    ),
    (
        "audit_report_facts",
        "activities",
        "TEXT NOT NULL DEFAULT '[]'",
        "JSONB NOT NULL DEFAULT '[]'\\:\\:jsonb",
    ),
    (
        "audit_report_facts",
        "communications",
        'TEXT NOT NULL DEFAULT \'{"has_audit_committee"\\:false,"items"\\:[]}\'',
        'JSONB NOT NULL DEFAULT \'{"has_audit_committee"\\:false,"items"\\:[]}\'\\:\\:jsonb',
    ),
    (
        "audit_report_facts",
        "hours_status",
        "VARCHAR(32)",
        "VARCHAR(32)",
    ),
    (
        "audit_report_facts",
        "activities_status",
        "VARCHAR(32)",
        "VARCHAR(32)",
    ),
    (
        "audit_report_facts",
        "communications_status",
        "VARCHAR(32)",
        "VARCHAR(32)",
    ),
    (
        "audit_report_facts",
        "accounts",
        "TEXT NOT NULL DEFAULT '[]'",
        "JSONB NOT NULL DEFAULT '[]'\\:\\:jsonb",
    ),
    (
        "audit_report_facts",
        "accounts_status",
        "VARCHAR(32)",
        "VARCHAR(32)",
    ),
    (
        "audit_report_facts",
        "bs_entry_id",
        "VARCHAR(128)",
        "VARCHAR(128)",
    ),
    (
        "audit_report_facts",
        "is_entry_id",
        "VARCHAR(128)",
        "VARCHAR(128)",
    ),
    (
        "audit_report_facts",
        "fs_parent_entry_id",
        "VARCHAR(128)",
        "VARCHAR(128)",
    ),
    (
        "audit_report_facts",
        "icfr_entry_id",
        "VARCHAR(128)",
        "VARCHAR(128)",
    ),
    (
        "audit_report_facts",
        "icfr_engagement",
        "VARCHAR(16)",
        "VARCHAR(16)",
    ),
    (
        "audit_report_facts",
        "icfr_opinion_raw",
        "TEXT",
        "TEXT",
    ),
    (
        "audit_report_facts",
        "icfr_opinion_code",
        "VARCHAR(32)",
        "VARCHAR(32)",
    ),
    (
        "audit_report_facts",
        "icfr_status",
        "VARCHAR(32)",
        "VARCHAR(32)",
    ),
    (
        "audit_report_facts",
        "going_concern",
        "INTEGER",
        "INTEGER",
    ),
    (
        "audit_report_facts",
        "going_concern_status",
        "VARCHAR(32)",
        "VARCHAR(32)",
    ),
    (
        "audit_report_facts",
        "going_concern_raw",
        "TEXT",
        "TEXT",
    ),
    (
        "audit_report_facts",
        "going_concern_source",
        "VARCHAR(32)",
        "VARCHAR(32)",
    ),
    (
        "audit_report_facts",
        "subsidiary_count",
        "INTEGER",
        "INTEGER",
    ),
    (
        "audit_report_facts",
        "subsidiary_status",
        "VARCHAR(32)",
        "VARCHAR(32)",
    ),
    (
        "audit_report_facts",
        "subsidiary_source",
        "VARCHAR(32)",
        "VARCHAR(32)",
    ),
    (
        "audit_report_facts",
        "notes_entry_id",
        "VARCHAR(128)",
        "VARCHAR(128)",
    ),
    (
        "audit_report_facts",
        "a001_affiliate_entry_id",
        "VARCHAR(128)",
        "VARCHAR(128)",
    ),
)


async def ensure_research_schema(engine: AsyncEngine) -> None:
    """있는 연구 테이블에만 빠진 열을 추가한다. 테이블은 만들지 않는다."""
    async with engine.begin() as connection:
        dialect = connection.dialect.name
        for table, column, sqlite_ddl, postgres_ddl in _COLUMN_PATCHES:
            ddl = sqlite_ddl if dialect == "sqlite" else postgres_ddl
            await _add_column_if_missing(connection, table, column, ddl, dialect)


async def _add_column_if_missing(
    connection: AsyncConnection,
    table: str,
    column: str,
    column_ddl: str,
    dialect: str,
) -> None:
    """테이블이 있고 컬럼이 없으면 ALTER TABLE로 추가한다."""
    if not await _table_exists(connection, table, dialect):
        return
    if await _column_exists(connection, table, column, dialect):
        return

    statement = text(f"ALTER TABLE {table} ADD COLUMN {column} {column_ddl}")
    await connection.execute(statement)
    logger.info("연구 스키마 보강: %s.%s 컬럼을 추가했습니다.", table, column)


async def _table_exists(connection: AsyncConnection, table: str, dialect: str) -> bool:
    """테이블 존재 여부를 확인한다."""
    if dialect == "sqlite":
        result = await connection.execute(
            text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"),
            {"name": table},
        )
        return result.first() is not None

    result = await connection.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :name"
        ),
        {"name": table},
    )
    return result.first() is not None


async def _column_exists(
    connection: AsyncConnection, table: str, column: str, dialect: str
) -> bool:
    """컬럼 존재 여부를 확인한다."""
    if dialect == "sqlite":
        result = await connection.execute(text(f"PRAGMA table_info({table})"))
        return any(row[1] == column for row in result.fetchall())

    result = await connection.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return result.first() is not None
