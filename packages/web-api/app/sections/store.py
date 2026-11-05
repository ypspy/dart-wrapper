"""섹션 본문 SQLite. 카탈로그는 읽기 전용으로만 연다."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SECTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS section_bodies (
    rcept_no TEXT NOT NULL,
    section_code TEXT NOT NULL,
    section_title TEXT,
    body_text TEXT,
    body_hash TEXT,
    source_url TEXT,
    fetched_at TEXT,
    PRIMARY KEY (rcept_no, section_code)
);

CREATE TABLE IF NOT EXISTS section_failures (
    rcept_no TEXT NOT NULL,
    section_code TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('not_found', 'fetch_error')),
    reason TEXT,
    fetched_at TEXT,
    PRIMARY KEY (rcept_no, section_code)
);
"""


def open_catalog_readonly(path: Path) -> sqlite3.Connection:
    """dart_catalog.db를 URI mode=ro로 연다. 쓰기는 거절된다.

    :raises FileNotFoundError: 파일이 없을 때
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"카탈로그 DB를 찾지 못했습니다: {path}. "
            "--catalog-db 에 dart_catalog.db 경로를 넣어 주세요."
        )
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def open_sections_db(path: Path) -> sqlite3.Connection:
    """섹션 DB를 만들고 WAL 모드로 연다. 없으면 테이블을 만든다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(_SECTIONS_SCHEMA)
    connection.commit()
    return connection


def list_disclosures(
    connection: sqlite3.Connection, report_type: str
) -> list[tuple[str, str | None]]:
    """보고서 유형이 같은 접수를 접수번호 순으로 읽는다.

    :return: (rcept_no, disclosure_url) 목록
    :raises RuntimeError: disclosures 테이블을 읽지 못할 때
    """
    code = report_type.strip().upper()
    try:
        rows = connection.execute(
            """
            SELECT rcept_no, disclosure_url
            FROM disclosures
            WHERE upper(trim(report_type)) = ?
            ORDER BY rcept_no
            """,
            (code,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise RuntimeError(
            "카탈로그의 disclosures 테이블을 읽지 못했습니다. "
            "경로가 dart_catalog.db인지 확인해 주세요."
        ) from exc
    found: list[tuple[str, str | None]] = []
    for row in rows:
        rcept_no = str(row["rcept_no"] or "").strip()
        if not rcept_no:
            continue
        url = row["disclosure_url"]
        found.append((rcept_no, str(url) if url else None))
    return found


class SectionStore:
    """section_bodies와 section_failures에 한 건씩 커밋한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def has_body(self, rcept_no: str, section_code: str) -> bool:
        """이미 본문이 있으면 참."""
        row = self._connection.execute(
            """
            SELECT 1 FROM section_bodies
            WHERE rcept_no = ? AND section_code = ?
            """,
            (rcept_no, section_code),
        ).fetchone()
        return row is not None

    def failure_kind(self, rcept_no: str, section_code: str) -> str | None:
        """기록된 실패 종류. 없으면 None."""
        row = self._connection.execute(
            """
            SELECT kind FROM section_failures
            WHERE rcept_no = ? AND section_code = ?
            """,
            (rcept_no, section_code),
        ).fetchone()
        if row is None:
            return None
        return str(row["kind"])

    def upsert_body(
        self,
        *,
        rcept_no: str,
        section_code: str,
        section_title: str,
        body_text: str,
        body_hash: str,
        source_url: str,
        fetched_at: str,
    ) -> None:
        """본문을 넣고 같은 키의 실패 기록은 지운다."""
        self._connection.execute(
            """
            INSERT INTO section_bodies (
                rcept_no, section_code, section_title, body_text,
                body_hash, source_url, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rcept_no, section_code) DO UPDATE SET
                section_title = excluded.section_title,
                body_text = excluded.body_text,
                body_hash = excluded.body_hash,
                source_url = excluded.source_url,
                fetched_at = excluded.fetched_at
            """,
            (
                rcept_no,
                section_code,
                section_title,
                body_text,
                body_hash,
                source_url,
                fetched_at,
            ),
        )
        self._connection.execute(
            """
            DELETE FROM section_failures
            WHERE rcept_no = ? AND section_code = ?
            """,
            (rcept_no, section_code),
        )
        self._connection.commit()

    def upsert_failure(
        self,
        *,
        rcept_no: str,
        section_code: str,
        kind: str,
        reason: str,
        fetched_at: str,
    ) -> None:
        """실패를 기록하고, 갱신 중이면 예전 본문은 지운다."""
        self._connection.execute(
            """
            DELETE FROM section_bodies
            WHERE rcept_no = ? AND section_code = ?
            """,
            (rcept_no, section_code),
        )
        self._connection.execute(
            """
            INSERT INTO section_failures (
                rcept_no, section_code, kind, reason, fetched_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(rcept_no, section_code) DO UPDATE SET
                kind = excluded.kind,
                reason = excluded.reason,
                fetched_at = excluded.fetched_at
            """,
            (rcept_no, section_code, kind, reason, fetched_at),
        )
        self._connection.commit()
