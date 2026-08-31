"""비동기 DB 엔진·세션 팩토리와 스키마 보강.

create_all만으로는 기존 테이블에 새 컬럼이 생기지 않으므로,
기동 시 알려진 누락 컬럼을 ALTER로 보완한다.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import Base

logger = logging.getLogger(__name__)

# 뼈대 단계에서 Alembic 대신 쓰는 최소 마이그레이션.
# (테이블명, 컬럼명, SQLite DDL 조각, PostgreSQL DDL 조각)
_COLUMN_PATCHES: tuple[tuple[str, str, str, str], ...] = (
    (
        "catalog_jobs",
        "mode",
        "VARCHAR(16) NOT NULL DEFAULT 'collect'",
        "VARCHAR(16) NOT NULL DEFAULT 'collect'",
    ),
    (
        "entries",
        "ordinal",
        "INTEGER",
        "INTEGER",
    ),
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
        # JSON 기본값의 :false 도 text() 바인드로 해석되므로 이스케이프한다.
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
)


def create_db_engine(database_url: str) -> AsyncEngine:
    """DATABASE_URL로 비동기 엔진을 만든다."""
    return create_async_engine(database_url, future=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """요청 단위 세션을 만드는 세션메이커를 반환한다."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def create_all(engine: AsyncEngine) -> None:
    """모델 기준으로 테이블을 만들고 알려진 스키마 누락을 보강한다.

    기존 이름은 유지한다. 실제로는 `ensure_schema`와 같다.
    """
    await ensure_schema(engine)


async def ensure_schema(engine: AsyncEngine) -> None:
    """없는 테이블을 만들고, 알려진 누락 컬럼만 안전하게 추가한다."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
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
    """테이블에 컬럼이 없으면 ALTER TABLE로 추가한다."""
    if not await _table_exists(connection, table, dialect):
        return
    if await _column_exists(connection, table, column, dialect):
        return

    statement = text(f"ALTER TABLE {table} ADD COLUMN {column} {column_ddl}")
    await connection.execute(statement)
    logger.info("스키마 보강: %s.%s 컬럼을 추가했습니다.", table, column)


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
