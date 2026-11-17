"""interim_review_facts 테이블 생성 스크립트.

기본은 dry-run이라 실행할 DDL만 출력한다. `--write`일 때만 기존 파일에
테이블 하나와 인덱스 둘을 만든다. 파일이 없으면 새로 만들지 않는다.
1층 테이블과 audit_report_facts가 SQL에 있으면 거부한다.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

_FORBIDDEN_TABLES = (
    "entries",
    "disclosures",
    "corps",
    "slice_progress",
    "catalog_jobs",
    "catalog_job_logs",
    "disclosure_attempts",
    "audit_report_facts",
)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS interim_review_facts (
    rcept_no VARCHAR(32) NOT NULL,
    dcm_no VARCHAR(32) NOT NULL,
    source_report_type VARCHAR(16) NOT NULL,
    review_kind VARCHAR(16) NOT NULL,
    fs_scope VARCHAR(16) NOT NULL,
    doc_kind VARCHAR(32) NOT NULL,
    cover_entry_id VARCHAR(128),
    report_entry_id VARCHAR(128),
    fs_parent_entry_id VARCHAR(128),
    notes_entry_id VARCHAR(128),
    reviewer_raw TEXT,
    reviewer_resolved VARCHAR(255),
    reviewer_status VARCHAR(32),
    conclusion_raw TEXT,
    conclusion_code VARCHAR(32),
    conclusion_status VARCHAR(32),
    review_report_date_raw TEXT,
    review_report_date VARCHAR(16),
    review_report_date_status VARCHAR(32),
    review_report_date_candidates TEXT NOT NULL DEFAULT '[]',
    review_period_raw TEXT,
    review_period_resolved VARCHAR(64),
    review_period_status VARCHAR(32),
    gaap_code VARCHAR(32),
    gaap_status VARCHAR(32),
    emphasis_of_matter INTEGER NOT NULL DEFAULT 0,
    going_concern INTEGER NOT NULL DEFAULT 0,
    emphasis_raw TEXT,
    emphasis_status VARCHAR(32),
    fetch_status VARCHAR(32) NOT NULL,
    conflicts TEXT NOT NULL DEFAULT '[]',
    extracted_at DATETIME NOT NULL,
    extractor_version VARCHAR(32) NOT NULL,
    PRIMARY KEY (rcept_no, dcm_no)
)
""".strip()

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_interim_review_facts_source_report_type "
    "ON interim_review_facts (source_report_type)",
    "CREATE INDEX IF NOT EXISTS ix_interim_review_facts_extracted_at "
    "ON interim_review_facts (extracted_at)",
)


class InterimTableError(RuntimeError):
    """테이블 생성 스크립트가 실행을 거절할 때."""


def build_statements() -> list[str]:
    """실행할 DDL. 테이블 하나와 인덱스 둘뿐이다."""
    return [_CREATE_TABLE, *_CREATE_INDEXES]


def assert_statements_safe(statements: list[str]) -> None:
    """1층 이름이나 audit_report_facts가 있으면 예외로 거부한다."""
    for statement in statements:
        folded = statement.casefold()
        for name in _FORBIDDEN_TABLES:
            if re.search(rf"\b{re.escape(name)}\b", folded):
                raise InterimTableError(
                    f"실행할 SQL에 금지된 테이블 이름({name})이 있습니다. "
                    "interim_review_facts만 만들 수 있습니다."
                )


def _require_existing_file(path: Path) -> None:
    """대상 파일이 이미 있을 때만 진행한다. 새 데이터베이스는 만들지 않는다."""
    if path.is_file():
        return
    raise InterimTableError(
        "대상 데이터베이스 파일이 없습니다. 새 데이터베이스는 만들지 않습니다: " f"{path}"
    )


def apply_statements(
    path: Path,
    statements: list[str],
    *,
    write: bool,
    confirm_backup: bool = False,
) -> None:
    """dry-run은 DDL만 출력하고, write는 백업 확인이 있는 기존 파일에만 실행한다."""
    _require_existing_file(path)
    if write and not confirm_backup:
        raise InterimTableError(
            "쓰려면 대상 데이터베이스를 백업한 뒤 --confirm-backup을 함께 주세요."
        )
    assert_statements_safe(statements)
    if not write:
        for statement in statements:
            sys.stdout.write(statement.rstrip() + ";\n")
        return
    connection = sqlite3.connect(path)
    try:
        for statement in statements:
            connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    """대상 경로와 쓰기 여부를 받는다."""
    parser = argparse.ArgumentParser(
        description=(
            "interim_review_facts 테이블 DDL을 출력합니다. "
            "기본은 dry-run이고, --write일 때만 기존 파일에 만듭니다."
        )
    )
    parser.add_argument("--target-db", required=True, type=Path, help="이미 있는 SQLite 파일")
    parser.add_argument(
        "--write",
        action="store_true",
        help="DDL을 실행합니다. 없으면 출력만 합니다. --confirm-backup이 필요합니다.",
    )
    parser.add_argument(
        "--confirm-backup",
        action="store_true",
        help="대상 파일을 이미 백업했음을 확인합니다. --write와 함께 필요합니다.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """DDL을 출력하거나 기존 파일에 적용한다. 거절하면 1을 돌려준다."""
    args = build_parser().parse_args(argv)
    try:
        apply_statements(
            args.target_db,
            build_statements(),
            write=bool(args.write),
            confirm_backup=bool(args.confirm_backup),
        )
    except InterimTableError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
