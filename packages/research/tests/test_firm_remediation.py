"""Ⅵ-2 개선권고 이행 추출. 실제 카탈로그와 2,984행 스냅샷은 쓰지 않는다."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db.session import create_db_engine, ensure_schema
from research.extracting.firm_remediation import (
    PARSER_VERSION,
    normalize_firm_display_name,
    parse_remediation,
)
from research.schema import ensure_research_schema
from research.services.firm_remediation_loader import (
    REQUIRED_FIELDS,
    FirmRemediationError,
    FirmRemediationLoadError,
    connect_catalog,
    load_section_records,
    readonly_file_uri,
    require_readonly_uri,
)
from research.services.firm_remediation_service import (
    SUMMARY_KEYS,
    prepare_documents,
    run_firm_remediation,
)

FIXTURE = Path(__file__).parent / "fixtures" / "f004" / "f004_section6.jsonl"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract_firm_remediation.py"
CATALOG_ROWS = (
    ("20160630000531", "00260295", "(2016.03)"),
    ("20200929000485", "00260295", "(2020.06)"),
    ("20220930000262", "00260295", "(2022.06)"),
    ("20220630000456", "00260365", "(2022.03)"),
    ("20230630000442", "01138744", "(2023.03)"),
    ("20200630000215", "00607609", "(2020.03)"),
    ("20201202000259", "00607609", "(2020.03)"),
    ("20260630000168", "01138744", "(2026.03)"),
)
EXPECTED_SUMMARY = {
    "documents": 8,
    "table": 5,
    "empty": 2,
    "no_subsection": 1,
    "comment_documents": 2,
    "dual_table_documents": 2,
    "logical_rows": 33,
    "unparsed_in_table": 0,
    "unique_corp_codes": 4,
    "multi_receipt_groups": 1,
}


def _catalog(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE disclosures (rcept_no TEXT PRIMARY KEY, corp_code TEXT, year_end TEXT)"
    )
    connection.executemany("INSERT INTO disclosures VALUES (?, ?, ?)", CATALOG_ROWS)
    connection.commit()
    connection.close()


def _year_ends(path: Path) -> dict[str, str | None]:
    from research.services.firm_remediation_loader import fetch_year_ends

    nos = [row[0] for row in CATALOG_ROWS]
    return fetch_year_ends(path, nos)


def _dump(path: Path, table: str, columns: str) -> list[tuple]:
    connection = sqlite3.connect(path)
    rows = connection.execute(f"SELECT {columns} FROM {table} ORDER BY {columns}").fetchall()
    connection.close()
    return rows


def test_reassembly_keeps_component_across_five_four_and_three_cells() -> None:
    """5칸 그룹 라벨, 빈 3칸, 4칸 새 구분, 이어지는 3칸을 한 표로 맞춘다."""
    documents = {item.rcept_no: item for item in load_section_records(FIXTURE)}
    result = parse_remediation(
        "20220930000262",
        "00260295",
        documents["20220930000262"].body_text,
    )
    assert result.status == "table"
    assert result.n_tables == 1
    assert result.notes == []
    expected = [
        ("회계법인내 품질에 대한 리더십 책임", 5, "ok"),
        ("회계법인내 품질에 대한 리더십 책임", 3, "empty"),
        ("윤리적 요구사항", 4, "ok"),
        ("윤리적 요구사항", 3, "continuation_merged"),
    ]
    assert [(row.component, row.source_cells, row.parse_status) for row in result.rows] == expected
    assert "품질지향 문화" in result.rows[0].finding
    assert result.rows[1].action_date == "-"
    assert "자기검토위협" in result.rows[3].finding


def test_empty_table_and_boilerplate_comment_are_not_substantive() -> None:
    documents = {item.rcept_no: item for item in load_section_records(FIXTURE)}
    empty = parse_remediation(
        "20200929000485",
        "00260295",
        documents["20200929000485"].body_text,
    )
    assert empty.status == "empty"
    assert empty.rows
    assert all(row.parse_status == "empty" for row in empty.rows)
    assert any("외부공개를 결정한 사항이 없습니다" in note.raw_text for note in empty.notes)
    assert all(note.kind == "comment" for note in empty.notes)

    plain = parse_remediation(
        "20200630000215",
        "00607609",
        documents["20200630000215"].body_text,
    )
    assert plain.status == "empty"
    assert plain.notes == []


def test_missing_subsection_ignores_supervision_rows() -> None:
    documents = {item.rcept_no: item for item in load_section_records(FIXTURE)}
    body = documents["20160630000531"].body_text
    assert "감리지적사항" in body
    assert body.count("|") >= 7
    result = parse_remediation("20160630000531", "00260295", body)
    assert result.status == "no_subsection"
    assert result.rows == []
    assert result.notes == []
    assert result.n_tables == 0


def test_comment_keeps_source_typo() -> None:
    documents = {item.rcept_no: item for item in load_section_records(FIXTURE)}
    result = parse_remediation(
        "20220630000456",
        "00260365",
        documents["20220630000456"].body_text,
    )
    assert result.status == "table"
    assert any("품질괸리" in note.raw_text and note.kind == "comment" for note in result.notes)


def test_dual_tables_and_supervision_block_stay_out_of_logical_rows() -> None:
    documents = {item.rcept_no: item for item in load_section_records(FIXTURE)}
    early = parse_remediation(
        "20230630000442",
        "01138744",
        documents["20230630000442"].body_text,
    )
    assert early.status == "table"
    assert early.n_tables == 2
    assert {row.table_idx for row in early.rows} == {0, 1}
    assert early.rows[0].row_idx == 0
    assert any(row.table_idx == 1 and row.component == "개별 감사보고서 관련" for row in early.rows)

    later = parse_remediation(
        "20260630000168",
        "01138744",
        documents["20260630000168"].body_text,
    )
    assert later.status == "table"
    assert later.n_tables == 2
    assert later.rows[0].component == "모니터링"
    assert all("2025-10-21" not in row.action_date for row in later.rows)
    assert all("동일이사" not in row.finding for row in later.rows)
    blocked = [note for note in later.notes if "2025-10-21" in note.raw_text]
    assert len(blocked) == 1
    assert blocked[0].kind == "unparsed"
    assert blocked[0].in_table is False
    assert any(note.reason == "supervision_block" for note in later.notes)


def test_odd_shapes_inside_an_open_table_are_unparsed() -> None:
    body = "\n".join(
        (
            "2. 품질관리 감리결과",
            "구분 | 조치일자 | 개선권고사항 | 개선권고 이행상황",
            "리더십 | 2022.01.01 | 권고A | 이행A",
            "- | 2022.01.02 | 권고B | 이행B",
            "2022.01.03 | 날짜가 구분칸 | 이행C | 추가",
            "2025-10-21 | 한공회 | 지적 | 조치 | 추가",
        )
    )
    result = parse_remediation("synthetic", "00000001", body)
    assert result.status == "table"
    assert [(row.source_cells, row.parse_status, row.component) for row in result.rows] == [
        (4, "ok", "리더십"),
        (4, "ok", "리더십"),
    ]
    assert result.rows[1].action_date == "2022.01.02"
    assert result.rows[1].finding == "권고B"
    reasons = [note.reason for note in result.notes if note.in_table]
    assert reasons == ["date_in_first_cell", "not_group_label"]


def test_line_heading_wins_over_an_earlier_inline_mention() -> None:
    body = "\n".join(
        (
            "설명에 2. 품질관리 감리결과 가 적혀 있다",
            "조치일자 | 조치자 | 감리지적사항 | 조치내역",
            "2013.04.24 | 위원회 | 회사 | 기타 | 기간 | 지적 | 조치 | -",
            "2. 감사인 감리결과",
            "구분 | 조치일자 | 개선권고사항 | 이행상황",
            "리더십 | 2022.01.01 | 권고 | 이행",
        )
    )
    result = parse_remediation("synthetic", "00000001", body)
    assert result.status == "table"
    assert len(result.rows) == 1
    assert result.rows[0].component == "리더십"
    assert result.notes == []


def test_date_only_row_keeps_the_document_empty() -> None:
    body = "\n".join(
        (
            "2. 품질관리 감리결과",
            "구분 | 조치일자 | 개선권고사항 | 개선권고 이행상황",
            "리더십 | 2022.01.01 | - | -",
        )
    )
    result = parse_remediation("synthetic", "00000001", body)
    assert result.status == "empty"
    assert result.rows[0].parse_status == "empty"
    assert result.rows[0].action_date == "2022.01.01"


def test_display_name_normalization_is_not_a_corp_key() -> None:
    assert normalize_firm_display_name("주식회사 한빛회계법인") == "한빛회계법인"
    assert normalize_firm_display_name("한빛 회계법인") == "한빛회계법인"
    assert normalize_firm_display_name("(주)한빛회계법인") == "한빛회계법인"
    assert normalize_firm_display_name("㈜한빛회계법인") == "한빛회계법인"
    body = "\n".join(
        (
            "2. 품질관리 감리결과",
            "구분 | 조치일자 | 개선권고사항 | 개선권고 이행상황",
            "리더십 | 2022.01.01 | 권고 | 이행",
        )
    )
    result = parse_remediation("1", "00607609", body)
    assert result.corp_code == "00607609"


def test_fixture_summary_and_latest_flag(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.db"
    _catalog(catalog)
    documents = prepare_documents(FIXTURE, _year_ends(catalog))
    from research.services.firm_remediation_service import summarize

    summary = summarize(documents)
    assert list(summary) == list(SUMMARY_KEYS)
    assert summary == EXPECTED_SUMMARY
    by_rcept = {item.rcept_no: item for item in documents}
    assert by_rcept["20220930000262"].period_key == "2022-06"
    assert by_rcept["20160630000531"].period_key == "2016-03"
    assert by_rcept["20200630000215"].status == "empty"
    assert {row.is_latest for row in by_rcept["20200630000215"].rows} == {0}
    assert {row.is_latest for row in by_rcept["20201202000259"].rows} == {1}
    assert by_rcept["20200630000215"].rows
    assert by_rcept["20201202000259"].rows
    assert {row.is_latest for row in by_rcept["20220930000262"].rows} == {1}


def test_loader_stops_on_schema_hash_and_manifest(tmp_path: Path) -> None:
    original = json.loads(FIXTURE.read_text(encoding="utf-8").splitlines()[0])
    version = dict(original)
    version["schema_version"] = 2
    bad_version = tmp_path / "version.jsonl"
    bad_version.write_text(json.dumps(version, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(FirmRemediationLoadError, match="schema_version"):
        load_section_records(bad_version)

    hashed = dict(original)
    hashed["body_hash"] = "0" * 64
    bad_hash = tmp_path / "hash.jsonl"
    bad_hash.write_text(json.dumps(hashed, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(FirmRemediationLoadError, match="해시"):
        load_section_records(bad_hash)

    payload = FIXTURE.read_bytes()
    folder = tmp_path / "snap"
    folder.mkdir()
    (folder / "f004_section6.jsonl").write_bytes(payload)
    manifest = {
        "schema_version": 1,
        "jsonl": {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)},
        "fields": list(REQUIRED_FIELDS),
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert len(load_section_records(folder)) == 8

    manifest["jsonl"]["sha256"] = "f" * 64
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FirmRemediationLoadError, match="sha256"):
        load_section_records(folder)

    manifest["jsonl"]["sha256"] = hashlib.sha256(payload).hexdigest()
    manifest["jsonl"]["bytes"] = len(payload) + 1
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FirmRemediationLoadError, match="bytes"):
        load_section_records(folder)

    manifest["jsonl"]["bytes"] = len(payload)
    manifest["schema_version"] = 2
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FirmRemediationLoadError, match="schema_version"):
        load_section_records(folder)

    flat = tmp_path / "flat"
    flat.mkdir()
    (flat / "custom.jsonl").write_bytes(payload)
    (flat / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "jsonl.sha256": hashlib.sha256(payload).hexdigest(),
                "jsonl.bytes": len(payload),
            }
        ),
        encoding="utf-8",
    )
    assert len(load_section_records(flat)) == 8


def test_catalog_connection_is_read_only(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.db"
    _catalog(catalog)
    uri = readonly_file_uri(catalog)
    require_readonly_uri(uri)
    assert "mode=ro" in uri
    with pytest.raises(FirmRemediationLoadError, match="mode=ro"):
        require_readonly_uri(catalog.resolve().as_uri())
    with pytest.raises(FirmRemediationLoadError, match="mode=ro"):
        require_readonly_uri(f"{catalog.resolve().as_uri()}?mode=rw")
    connection = connect_catalog(catalog)
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("UPDATE disclosures SET year_end = '(2099.01)'")
    finally:
        connection.close()


async def test_dry_run_does_not_write_and_write_is_idempotent(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.db"
    target = tmp_path / "out" / "firm.db"
    _catalog(catalog)
    summary = await run_firm_remediation(
        input_path=FIXTURE,
        catalog_path=catalog,
        write=False,
        target_db=target,
    )
    assert summary == EXPECTED_SUMMARY
    assert not target.exists()

    untouched = tmp_path / "empty.db"
    sqlite3.connect(untouched).close()
    await run_firm_remediation(
        input_path=FIXTURE,
        catalog_path=catalog,
        write=False,
        target_db=untouched,
    )
    names = {
        row[0]
        for row in sqlite3.connect(untouched).execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert "extraction_firm_remediation" not in names

    await run_firm_remediation(
        input_path=FIXTURE, catalog_path=catalog, write=True, target_db=target
    )
    columns = (
        "rcept_no, table_idx, row_idx, corp_code, period_key, component, "
        "action_date, finding, action, is_latest, parse_status, source_cells, parser_version"
    )
    first_rows = _dump(target, "extraction_firm_remediation", columns)
    first_notes = _dump(
        target,
        "extraction_firm_remediation_notes",
        "rcept_no, note_idx, kind, raw_text, reason, parser_version",
    )
    doc_columns = (
        "rcept_no, corp_code, period_key, status, n_tables, "
        "n_logical_rows, n_notes, parser_version"
    )
    first_docs = _dump(target, "extraction_firm_remediation_documents", doc_columns)
    await run_firm_remediation(
        input_path=FIXTURE, catalog_path=catalog, write=True, target_db=target
    )
    assert _dump(target, "extraction_firm_remediation", columns) == first_rows
    assert (
        _dump(
            target,
            "extraction_firm_remediation_notes",
            "rcept_no, note_idx, kind, raw_text, reason, parser_version",
        )
        == first_notes
    )
    assert (
        _dump(
            target,
            "extraction_firm_remediation_documents",
            "rcept_no, corp_code, period_key, status, n_tables, "
            "n_logical_rows, n_notes, parser_version",
        )
        == first_docs
    )
    assert len(first_rows) == 33
    assert all(row[-1] == PARSER_VERSION for row in first_rows)
    statuses = {row[0]: row[3] for row in first_docs}
    assert statuses["20160630000531"] == "no_subsection"
    assert statuses["20200929000485"] == "empty"
    assert statuses["20201202000259"] == "table"
    latest = {
        row[0]: row[1]
        for row in sqlite3.connect(target).execute(
            "SELECT rcept_no, is_latest FROM extraction_firm_remediation "
            "WHERE corp_code = '00607609' GROUP BY rcept_no, is_latest"
        )
    }
    assert latest == {"20200630000215": 0, "20201202000259": 1}
    stored_tables = {
        row[0]
        for row in sqlite3.connect(target).execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert "entries" not in stored_tables
    assert "extraction_firm_remediation" in stored_tables
    reviews = _dump(
        target,
        "extraction_firm_match_review",
        "reason, corp_code, other_corp_code, corp_name, other_corp_name",
    )
    assert ("same_name", "00260125", "00260213", "대성회계법인", "대성회계법인") in reviews
    assert ("same_name", "00426730", "01889714", "지성회계법인", "지성회계법인") in reviews
    assert ("same_name", "00546973", "01880555", "회계법인원", "회계법인원") in reviews
    missing = {
        "01951349": "여울",
        "01953550": "영신",
        "01983603": "대륙아주",
        "01984639": "더위즈",
        "01985744": "주성",
        "01989874": "삼율",
    }
    for code, name in missing.items():
        assert ("missing_from_corps", code, "", name, None) in reviews
    assert len(reviews) == 9
    assert sum(1 for row in reviews if row[0] == "same_name") == 3


async def test_failed_load_does_not_create_target_and_paths_stay_separate(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.db"
    target = tmp_path / "firm.db"
    _catalog(catalog)
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"schema_version": 2}\n', encoding="utf-8")
    with pytest.raises(FirmRemediationLoadError):
        await run_firm_remediation(input_path=bad, write=True, target_db=target)
    assert not target.exists()
    with pytest.raises(FirmRemediationError, match="다른 경로"):
        await run_firm_remediation(
            input_path=FIXTURE, catalog_path=catalog, write=True, target_db=catalog
        )
    count = sqlite3.connect(catalog).execute("SELECT count(*) FROM disclosures").fetchone()[0]
    assert count == len(CATALOG_ROWS)


async def test_startup_schema_does_not_create_firm_tables() -> None:
    """연구 모델이 메타에 있어도 기동 스키마와 연구 열 보정은 테이블을 만들지 않는다."""
    import research.models.firm_remediation  # noqa: F401

    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await ensure_schema(engine)
    await ensure_research_schema(engine)
    async with engine.begin() as connection:
        names = {
            row[0]
            for row in (
                await connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'table'")
                )
            ).fetchall()
        }
    await engine.dispose()
    assert "extraction_firm_remediation" not in names
    assert "extraction_firm_remediation_notes" not in names
    assert "extraction_firm_remediation_documents" not in names
    assert "extraction_firm_match_review" not in names
    assert "entries" in names


def test_new_modules_do_not_call_network_llm_or_section_db() -> None:
    root = Path(__file__).resolve().parents[1] / "research"
    paths = [
        root / "extracting" / "firm_remediation.py",
        root / "models" / "firm_remediation.py",
        root / "repositories" / "firm_remediation_repository.py",
        root / "services" / "firm_remediation_loader.py",
        root / "services" / "firm_remediation_service.py",
        Path(__file__).resolve().parents[1] / "scripts" / "extract_firm_remediation.py",
    ]
    banned = ("import httpx", "openai", "anthropic", "dart.fss.or.kr", "playwright")
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in source
        assert "dart_sections.db" not in source or "읽지 않는다" in source


def test_cli_dry_run_prints_summary_keys(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.db"
    target = tmp_path / "not-created.db"
    _catalog(catalog)
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(FIXTURE.parent),
            "--catalog",
            str(catalog),
            "--target-db",
            str(target),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "DART_LLM_ENABLED": "false"},
    )
    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert list(summary) == list(SUMMARY_KEYS)
    assert summary == EXPECTED_SUMMARY
    assert not target.exists()

    both = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(FIXTURE), "--write", "--dry-run"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert both.returncode == 1
    assert "dry-run" in both.stderr
