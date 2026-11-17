"""테스트용 임시 카탈로그 DB 헬퍼.

파일 이름이 test_로 시작하지 않아 pytest가 이 모듈을 수집하지 않는다.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_all, create_db_engine


def url_for(path: Path) -> str:
    """임시 SQLite 파일의 비동기 URL을 만든다."""
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def file_sha256(path: Path) -> str:
    """파일 바이트의 sha256을 돌려준다."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def connect_ro(path: Path) -> sqlite3.Connection:
    """읽기 전용으로 SQLite 파일에 연결한다."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def master_rows(path: Path) -> list[tuple[str, str, str | None]]:
    """sqlite_master의 type·name·sql을 정렬해 돌려준다."""
    connection = connect_ro(path)
    try:
        rows = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
    finally:
        connection.close()
    return [(row[0], row[1], row[2]) for row in rows]


def pragma_columns(path: Path, table: str) -> list[tuple[object, ...]]:
    """PRAGMA table_info 행을 그대로 돌려준다."""
    connection = connect_ro(path)
    try:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    finally:
        connection.close()
    return [tuple(row) for row in rows]


async def build_catalog(path: Path, *, keep_engine: bool = False) -> AsyncEngine | None:
    """카탈로그 스키마를 만든다.

    keep_engine이 참이면 엔진을 닫지 않고 돌려준다. 거짓이면 닫고 None이다.
    """
    engine = create_db_engine(url_for(path))
    await create_all(engine)
    if keep_engine:
        return engine
    await engine.dispose()
    return None
