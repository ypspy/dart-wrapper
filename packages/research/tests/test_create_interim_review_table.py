"""검토보고서 테이블 생성 스크립트. 임시 SQLite만 쓴다."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from research.models.interim_review_fact import InterimReviewFact
from scripts.create_interim_review_table import (
    InterimTableError,
    apply_statements,
    assert_statements_safe,
    build_statements,
    main,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _table_names(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    finally:
        connection.close()
    return {row[0] for row in rows}


def test_dry_run_keeps_file_bytes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """dry-run은 DDL만 출력하고 파일 해시는 그대로다."""
    path = tmp_path / "catalog.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE scratch (id INTEGER)")
    connection.commit()
    connection.close()
    before = _sha256(path)

    assert main(["--target-db", str(path)]) == 0

    assert _sha256(path) == before
    assert "interim_review_facts" not in _table_names(path)
    output = capsys.readouterr().out
    assert "CREATE TABLE IF NOT EXISTS interim_review_facts" in output
    assert "ix_interim_review_facts_source_report_type" in output
    assert "ix_interim_review_facts_extracted_at" in output


def test_write_adds_only_interim_table(tmp_path: Path) -> None:
    """--write는 interim_review_facts만 추가하고 다시 실행해도 테이블은 하나다."""
    path = tmp_path / "catalog.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE entries (id INTEGER)")
    connection.execute("INSERT INTO entries (id) VALUES (1)")
    connection.commit()
    connection.close()
    before = _table_names(path)

    assert main(["--target-db", str(path), "--write", "--confirm-backup"]) == 0
    assert main(["--target-db", str(path), "--write", "--confirm-backup"]) == 0

    names = _table_names(path)
    assert names - before == {"interim_review_facts"}
    connection = sqlite3.connect(path)
    try:
        count = connection.execute("SELECT COUNT(*) FROM entries").fetchone()
        columns = [row[1] for row in connection.execute("PRAGMA table_info(interim_review_facts)")]
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ?",
                ("interim_review_facts",),
            )
        }
    finally:
        connection.close()
    assert count == (1,)
    assert set(columns) == set(InterimReviewFact.__table__.columns.keys())
    assert "ix_interim_review_facts_source_report_type" in indexes
    assert "ix_interim_review_facts_extracted_at" in indexes


def test_refuses_sql_that_names_first_layer_or_audit_facts() -> None:
    """1층 이름이나 audit_report_facts가 있는 SQL은 실행 전에 거부한다."""
    with pytest.raises(InterimTableError, match="entries"):
        assert_statements_safe(["CREATE INDEX ix ON entries (id)"])
    with pytest.raises(InterimTableError, match="audit_report_facts"):
        assert_statements_safe(["INSERT INTO audit_report_facts (rcept_no) VALUES ('x')"])
    assert_statements_safe(build_statements())


def test_write_without_backup_confirmation_leaves_file_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--write만으로는 쓰지 않고 백업 확인을 요구한다."""
    path = tmp_path / "catalog.db"
    sqlite3.connect(path).close()
    before = _sha256(path)

    assert main(["--target-db", str(path), "--write"]) == 1

    assert _sha256(path) == before
    assert "interim_review_facts" not in _table_names(path)
    assert "백업" in capsys.readouterr().err


def test_missing_file_is_rejected_and_not_created(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """없는 경로는 실패하고 파일을 만들지 않는다."""
    path = tmp_path / "missing" / "catalog.db"
    assert main(["--target-db", str(path), "--write"]) == 1
    assert not path.exists()
    assert "없습니다" in capsys.readouterr().err
    with pytest.raises(InterimTableError, match="없습니다"):
        apply_statements(path, build_statements(), write=False)
