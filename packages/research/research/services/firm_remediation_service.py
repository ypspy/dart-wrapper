"""개선권고 이행 추출 오케스트레이션.

파서는 순수 함수로 두고, 기간 키·최신 접수·집계·저장만 여기서 붙인다.
기본은 dry-run이며 ``--write``와 대상 DB가 있을 때만 기록한다.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.db.session import create_db_engine, create_sessionmaker
from research.extracting.firm_remediation import (
    IN_TABLE_UNPARSED_REASONS,
    PARSER_VERSION,
    PreparedDocument,
    normalize_firm_display_name,
    parse_remediation,
)
from research.repositories.firm_remediation_repository import (
    MatchReviewSeed,
    FirmRemediationRepository,
    create_firm_remediation_tables,
)
from research.services.firm_remediation_loader import (
    FirmRemediationError,
    SectionRecord,
    fetch_year_ends,
    load_section_records,
    period_key_from_year_end,
)

SUMMARY_KEYS = (
    "documents",
    "table",
    "empty",
    "no_subsection",
    "comment_documents",
    "dual_table_documents",
    "logical_rows",
    "unparsed_in_table",
    "unique_corp_codes",
    "multi_receipt_groups",
)

# 추측 병합은 하지 않는다. 동명 3쌍과 회사 마스터 미등재 6코드만 확인 목록에 둔다.
_MATCH_REVIEW_SEEDS: tuple[tuple[str, str, str, str, str | None], ...] = (
    ("same_name", "00260125", "00260213", "대성회계법인", "대성회계법인"),
    ("same_name", "00426730", "01889714", "지성회계법인", "지성회계법인"),
    ("same_name", "00546973", "01880555", "회계법인원", "회계법인원"),
    ("missing_from_corps", "01951349", "", "여울", None),
    ("missing_from_corps", "01953550", "", "영신", None),
    ("missing_from_corps", "01983603", "", "대륙아주", None),
    ("missing_from_corps", "01984639", "", "더위즈", None),
    ("missing_from_corps", "01985744", "", "주성", None),
    ("missing_from_corps", "01989874", "", "삼율", None),
)


def match_review_seeds() -> list[MatchReviewSeed]:
    """표시용 상호만 정규화한 확인 목록 시드."""
    seeds: list[MatchReviewSeed] = []
    for reason, corp_code, other_code, name, other_name in _MATCH_REVIEW_SEEDS:
        seeds.append(
            MatchReviewSeed(
                reason=reason,
                corp_code=corp_code,
                other_corp_code=other_code,
                corp_name=normalize_firm_display_name(name),
                other_corp_name=(
                    None if other_name is None else normalize_firm_display_name(other_name)
                ),
            )
        )
    return seeds


def prepare_documents(
    input_path: Path,
    year_ends: dict[str, str | None],
) -> list[PreparedDocument]:
    """JSONL을 파싱하고 카탈로그 결산월로 period_key를 붙인다."""
    return _prepare_loaded(load_section_records(input_path), year_ends)


def apply_is_latest(documents: list[PreparedDocument]) -> None:
    """같은 법인·사업연도 말에서 접수일·접수번호가 가장 큰 문서의 행만 1로 둔다."""
    grouped: dict[tuple[str, str | None], list[PreparedDocument]] = defaultdict(list)
    for document in documents:
        grouped[(document.corp_code, document.period_key)].append(document)
    for group in grouped.values():
        winner = max(group, key=lambda item: (item.rcept_dt, item.rcept_no))
        for document in group:
            flag = 1 if document.rcept_no == winner.rcept_no else 0
            for row in document.rows:
                row.is_latest = flag


def summarize(documents: list[PreparedDocument]) -> dict[str, int]:
    """dry-run과 PR 대조에 쓰는 집계. 키 이름은 스냅샷 크기와 상관없이 같다."""
    grouped: dict[tuple[str, str | None], int] = defaultdict(int)
    for document in documents:
        grouped[(document.corp_code, document.period_key)] += 1
    return {
        "documents": len(documents),
        "table": sum(document.status == "table" for document in documents),
        "empty": sum(document.status == "empty" for document in documents),
        "no_subsection": sum(document.status == "no_subsection" for document in documents),
        "comment_documents": sum(
            any(note.kind == "comment" for note in document.notes) for document in documents
        ),
        "dual_table_documents": sum(document.n_tables >= 2 for document in documents),
        "logical_rows": sum(len(document.rows) for document in documents),
        "unparsed_in_table": sum(
            1
            for document in documents
            for note in document.notes
            if note.in_table and note.reason in IN_TABLE_UNPARSED_REASONS
        ),
        "unique_corp_codes": len({document.corp_code for document in documents}),
        "multi_receipt_groups": sum(count >= 2 for count in grouped.values()),
    }


def assert_write_targets(target_db: Path, catalog_path: Path | None, input_path: Path) -> None:
    """읽기 전용 입력과 같은 경로에는 쓰지 않는다."""
    target = target_db.resolve()
    blocked = [Path(input_path).resolve()]
    if catalog_path is not None:
        blocked.append(Path(catalog_path).resolve())
    if target in blocked:
        raise FirmRemediationError(
            "대상 DB는 카탈로그와 입력 JSONL과 다른 경로여야 합니다. 입력 파일은 바꾸지 않습니다."
        )


async def run_firm_remediation(
    *,
    input_path: Path,
    catalog_path: Path | None = None,
    write: bool = False,
    target_db: Path | None = None,
) -> dict[str, int]:
    """스냅샷을 읽고 집계한다. write가 아니면 대상 DB를 만들거나 수정하지 않는다."""
    if write and target_db is None:
        raise FirmRemediationError(
            "저장하려면 --write 와 --target-db 가 모두 필요합니다. 기본 실행은 dry-run입니다."
        )
    if write and target_db is not None:
        assert_write_targets(target_db, catalog_path, input_path)

    records = await asyncio.to_thread(load_section_records, input_path)
    year_ends: dict[str, str | None] = {}
    if catalog_path is not None:
        year_ends = await asyncio.to_thread(
            fetch_year_ends,
            catalog_path,
            [record.rcept_no for record in records],
        )
    documents = _prepare_loaded(records, year_ends)
    summary = summarize(documents)
    if not write or target_db is None:
        return summary
    await _write(target_db, documents)
    return summary


def _prepare_loaded(
    records: list[SectionRecord], year_ends: dict[str, str | None]
) -> list[PreparedDocument]:
    """이미 읽어 둔 행으로 문서를 만든다. JSONL을 두 번 읽지 않는다."""
    prepared: list[PreparedDocument] = []
    for record in records:
        parsed = parse_remediation(record.rcept_no, record.corp_code, record.body_text)
        prepared.append(
            PreparedDocument(
                rcept_no=record.rcept_no,
                corp_code=record.corp_code,
                corp_name=record.corp_name,
                rcept_dt=record.rcept_dt,
                period_key=period_key_from_year_end(year_ends.get(record.rcept_no)),
                status=parsed.status,
                n_tables=parsed.n_tables,
                rows=parsed.rows,
                notes=parsed.notes,
            )
        )
    apply_is_latest(prepared)
    return prepared


def target_database_url(path: Path) -> str:
    """대상 SQLite 파일의 SQLAlchemy URL."""
    return "sqlite+aiosqlite:///" + Path(path).resolve().as_posix()


async def _write(target_db: Path, documents: list[PreparedDocument]) -> None:
    """연구 테이블만 만들고 현재 파싱으로 교체한다."""
    target_db.parent.mkdir(parents=True, exist_ok=True)
    engine = create_db_engine(target_database_url(target_db))
    try:
        await create_firm_remediation_tables(engine)
        sessionmaker = create_sessionmaker(engine)
        async with sessionmaker() as session:
            async with session.begin():
                repository = FirmRemediationRepository(session)
                await repository.replace_snapshot(
                    documents,
                    match_review_seeds(),
                    extracted_at=datetime.now(timezone.utc),
                    parser_version=PARSER_VERSION,
                )
    finally:
        await engine.dispose()
