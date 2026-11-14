"""Ⅵ 소제목 2 열 규격. 저장소 fixture만 쓰고 실제 카탈로그에는 쓰지 않는다."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

from app.db.session import create_db_engine
from research.extracting.firm_remediation import (
    FINDING_VI_STATUSES,
    PARSER_VERSION,
    LogicalRow,
    _recommend_date,
    normalize_firm_display_name,
    normalize_spaced_text,
    parse_remediation,
    vi_row_fields,
)
from research.repositories.firm_remediation_repository import (
    _ensure_vi_view,
    create_firm_remediation_tables,
)
from research.services.firm_remediation_loader import (
    FirmRemediationLoadError,
    fetch_year_ends,
    load_section_records,
)
from research.services.firm_remediation_service import (
    SUMMARY_KEYS,
    prepare_documents,
    run_firm_remediation,
    summarize,
)

SAMPLES = Path(__file__).parent / "fixtures" / "f004" / "f004_vi_colspec_samples.jsonl"
OLD_FIXTURE = Path(__file__).parent / "fixtures" / "f004" / "f004_section6.jsonl"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract_firm_remediation.py"
SAMPLE_SHA256 = "18814fc62931290d71acc9860085f321a6c4095a8e3c2cf7137122af54e9587b"
VIEW_COLUMNS = (
    "rcept_no",
    "rcept_dt",
    "corp_code",
    "corp_name",
    "fiscal_year",
    "fiscal_year_src",
    "period_key",
    "subsection",
    "table_idx",
    "row_idx",
    "category_raw",
    "category_inherited",
    "finding_text",
    "action_text",
    "recommend_date_raw",
    "recommend_date_iso",
    "recommend_date_format",
    "action_date",
    "action_date_in_text",
    "inspection_year",
    "inspection_year_note",
    "multi_finding_flag",
    "source_line_raw",
    "parse_status",
    "parse_reason",
    "is_latest",
    "body_hash",
    "parser_version",
)
_SAMPLE_COUNTS = {
    "20190628000221": {
        "subsection": "quality_control",
        "n_tables": 1,
        "logical": 15,
        "finding": 11,
        "second": 0,
        "inherited": 5,
        "multi": 0,
        "kor": 11,
        "dot": 0,
        "partial": 1,
        "in_text": 1,
    },
    "20190701000113": {
        "subsection": "quality_control",
        "n_tables": 1,
        "logical": 14,
        "finding": 6,
        "second": 0,
        "inherited": 0,
        "multi": 4,
        "kor": 6,
        "dot": 0,
        "partial": 0,
        "in_text": 0,
    },
    "20230630000442": {
        "subsection": "auditor",
        "n_tables": 2,
        "logical": 24,
        "finding": 21,
        "second": 10,
        "inherited": 14,
        "multi": 0,
        "kor": 0,
        "dot": 21,
        "partial": 0,
        "in_text": 0,
    },
    "20250630000327": {
        "subsection": "auditor",
        "n_tables": 2,
        "logical": 27,
        "finding": 25,
        "second": 14,
        "inherited": 13,
        "multi": 0,
        "kor": 11,
        "dot": 14,
        "partial": 0,
        "in_text": 0,
    },
    "20260630000168": {
        "subsection": "auditor",
        "n_tables": 2,
        "logical": 30,
        "finding": 28,
        "second": 15,
        "inherited": 21,
        "multi": 0,
        "kor": 0,
        "dot": 28,
        "partial": 0,
        "in_text": 0,
    },
}
_OLD_CATALOG = (
    ("20160630000531", "00260295", "(2016.03)"),
    ("20200929000485", "00260295", "(2020.06)"),
    ("20220930000262", "00260295", "(2022.06)"),
    ("20220630000456", "00260365", "(2022.03)"),
    ("20230630000442", "01138744", "(2023.03)"),
    ("20200630000215", "00607609", "(2020.03)"),
    ("20201202000259", "00607609", "(2020.03)"),
    ("20260630000168", "01138744", "(2026.03)"),
)
_SAMPLE_CATALOG = (
    ("20190628000221", "00512657", "(2019.06)"),
    ("20190701000113", "00475763", "(2019.06)"),
    ("20230630000442", "01138744", "(2023.03)"),
    ("20250630000327", "00759896", "(2025.03)"),
    ("20260630000168", "01138744", "(2026.03)"),
)


def _records() -> list[dict]:
    """manifest 없이 샘플 JSONL을 읽는다."""
    return [
        json.loads(line)
        for line in SAMPLES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _finding(parsed, rcept_dt: str):
    """발견행과 계산된 Ⅵ 열."""
    pairs = []
    for row in parsed.rows:
        if row.parse_status == "empty":
            continue
        pairs.append((row, vi_row_fields(row, rcept_dt=rcept_dt)))
    return pairs


def _catalog(path: Path, rows: tuple[tuple[str, str, str], ...]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE disclosures (rcept_no TEXT PRIMARY KEY, corp_code TEXT, year_end TEXT)"
    )
    connection.executemany("INSERT INTO disclosures VALUES (?, ?, ?)", rows)
    connection.commit()
    connection.close()


def _manifest(folder: Path, payload: bytes) -> Path:
    """테스트 안에서만 manifest를 만든다."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "f004_vi_colspec_samples.jsonl"
    target.write_bytes(payload)
    manifest = {
        "schema_version": 1,
        "jsonl": {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)},
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return target


def test_sample_fixture_bytes_match_the_snapshot_excerpt() -> None:
    """지시서의 5줄 fixture와 바이트가 같다."""
    payload = SAMPLES.read_bytes()
    assert len(payload) == 31344
    assert hashlib.sha256(payload).hexdigest() == SAMPLE_SHA256
    assert payload.endswith(b"\n")
    assert b"\r" not in payload
    assert payload.count(b"\n") == 5


def test_sample_rows_match_vi_column_counts() -> None:
    """5개 접수본의 소제목·발견행·날짜·상속·다건 플래그가 기대와 같다."""
    seen: list[tuple[str, int, int]] = []
    totals = {name: 0 for name in ("logical", "finding", "second", "inherited", "multi")}
    dates = {"ymd_kor": 0, "ymd_dot": 0, "blank": 0, "other": 0}
    partial = 0
    in_text = 0
    for record in _records():
        parsed = parse_remediation(record["rcept_no"], record["corp_code"], record["body_text"])
        expected = _SAMPLE_COUNTS[record["rcept_no"]]
        finding = _finding(parsed, record["rcept_dt"])
        assert parsed.subsection == expected["subsection"]
        assert parsed.status == "table"
        assert parsed.n_tables == expected["n_tables"]
        assert len(parsed.rows) == expected["logical"]
        assert len(finding) == expected["finding"]
        assert parsed.inspection_year_note is None
        assert sum(row.table_idx == 1 for row, _fields in finding) == expected["second"]
        assert sum(fields.category_inherited for _row, fields in finding) == expected["inherited"]
        assert sum(fields.multi_finding_flag for _row, fields in finding) == expected["multi"]
        assert (
            sum(fields.recommend_date_format == "ymd_kor" for _row, fields in finding)
            == expected["kor"]
        )
        assert (
            sum(fields.recommend_date_format == "ymd_dot" for _row, fields in finding)
            == expected["dot"]
        )
        assert sum(fields.vi_status == "partial" for _row, fields in finding) == expected["partial"]
        assert sum(fields.action_date_in_text for _row, fields in finding) == expected["in_text"]
        for row, fields in finding:
            assert fields.category_raw
            assert "|" in fields.source_line_raw
            assert fields.source_line_raw in record["body_text"]
            assert fields.vi_status in {"ok", "merged", "partial"}
            seen.append((record["rcept_no"], row.table_idx, row.row_idx))
        totals["logical"] += len(parsed.rows)
        totals["finding"] += len(finding)
        totals["second"] += expected["second"]
        totals["inherited"] += expected["inherited"]
        totals["multi"] += expected["multi"]
        for _row, fields in finding:
            dates[fields.recommend_date_format] += 1
            partial += fields.vi_status == "partial"
            in_text += fields.action_date_in_text
        assert "넥스모" not in " ".join(row.finding for row, _fields in finding)
    assert len(seen) == len(set(seen))
    assert totals == {
        "logical": 110,
        "finding": 91,
        "second": 39,
        "inherited": 53,
        "multi": 4,
    }
    assert dates == {"ymd_kor": 28, "ymd_dot": 63, "blank": 0, "other": 0}
    assert partial == 1
    assert in_text == 1


def test_partial_multi_and_supervision_samples_keep_source_lines() -> None:
    """partial·다건·제재 블록 샘플은 행을 나누거나 제재 행을 발견행으로 올리지 않는다."""
    by_no = {record["rcept_no"]: record for record in _records()}

    partial_doc = by_no["20190628000221"]
    partial = parse_remediation(
        partial_doc["rcept_no"], partial_doc["corp_code"], partial_doc["body_text"]
    )
    row = next(item for item in partial.rows if item.table_idx == 0 and item.row_idx == 8)
    fields = vi_row_fields(row, rcept_dt=partial_doc["rcept_dt"])
    assert row.component == "인적자원"
    assert fields.category_raw == "인적자원"
    assert fields.recommend_date_raw == "2106년 11월 18일"
    assert fields.recommend_date_iso is None
    assert fields.recommend_date_format == "ymd_kor"
    assert fields.vi_status == "partial"
    assert fields.vi_status_reason == "recommend_date_out_of_range"
    assert fields.source_line_raw.startswith("2106년 11월 18일 |")
    assert (
        sum(
            vi_row_fields(item, rcept_dt=partial_doc["rcept_dt"]).action_date_in_text
            for item in partial.rows
            if item.parse_status != "empty"
        )
        == 1
    )

    multi_doc = by_no["20190701000113"]
    multi = parse_remediation(multi_doc["rcept_no"], multi_doc["corp_code"], multi_doc["body_text"])
    multi_rows = [item for item in multi.rows if item.row_idx in {4, 6, 8, 12}]
    assert [item.row_idx for item in multi_rows] == [4, 6, 8, 12]
    for item in multi_rows:
        fields = vi_row_fields(item, rcept_dt=multi_doc["rcept_dt"])
        assert fields.multi_finding_flag == 1
        assert "①" in item.finding and "②" in item.finding
        assert fields.source_line_raw in multi_doc["body_text"]

    early = by_no["20230630000442"]
    parsed = parse_remediation(early["rcept_no"], early["corp_code"], early["body_text"])
    first = next(
        item for item in parsed.rows if item.table_idx == 1 and item.parse_status != "empty"
    )
    fields = vi_row_fields(first, rcept_dt=early["rcept_dt"])
    assert fields.category_raw == "개별 감사보고서 관련"
    assert fields.recommend_date_raw == "2022.07.15"
    assert fields.recommend_date_iso == "2022-07-15"
    assert fields.recommend_date_format == "ymd_dot"

    dotted = by_no["20250630000327"]
    parsed = parse_remediation(dotted["rcept_no"], dotted["corp_code"], dotted["body_text"])
    first = next(
        item for item in parsed.rows if item.table_idx == 1 and item.parse_status != "empty"
    )
    fields = vi_row_fields(first, rcept_dt=dotted["rcept_dt"])
    assert fields.category_raw == "회계법인내 품질에 대한 리더십 책임"
    assert fields.recommend_date_raw == "2023. 04.25"
    assert fields.recommend_date_iso == "2023-04-25"
    assert fields.recommend_date_format == "ymd_dot"

    blocked = by_no["20260630000168"]
    parsed = parse_remediation(blocked["rcept_no"], blocked["corp_code"], blocked["body_text"])
    assert sum(note.reason == "supervision_block" for note in parsed.notes) == 1
    assert sum(note.reason == "closed_block" for note in parsed.notes) == 3
    assert all("2025-10-21" not in row.action_date for row in parsed.rows)
    assert all("2025-10-21" not in row.finding for row in parsed.rows)
    assert any(
        "2025-10-21" in note.raw_text and note.reason == "closed_block" for note in parsed.notes
    )


def test_date_inheritance_and_inspection_year_rules() -> None:
    """공란은 partial이 아니고, 잘못된 날짜·상속·산문 감리연도는 규칙대로 남긴다."""
    body = "\n".join(
        (
            "2. 감사인 감리결과",
            "품질관리감리는 2019년 이후 시행되는 제도입니다",
            "2020년 회계연도 감리에서 지적을 받았습니다",
            "2018년 감리 결과 증권선물위원회 안내",
            "감리를 받은 2021년 사업에 대한 보완입니다",
            "'19년 감리 지적",
            "2020년 | 감리 따로",
            "구분 | 조치일자 | 개선권고사항 | 개선권고 이행상황",
            "품질관리 구성요소 | 리더십 | 2010년 1월 2일 | 권고A | 이행A",
            "- | 2022.02.31 | 권고B | 이행B",
            "윤리 | 2022/07/15 | 권고C | 이행C",
            "인적 | - | 권고D | 2019. 3 반영",
            "2023년 01월 01일 | 이어진 지적 | 이행E",
            "모니터링 | 2100년 13월 40일 | - | -",
        )
    )
    parsed = parse_remediation("synthetic-vi", "00000001", body)
    assert parsed.subsection == "auditor"
    assert parsed.inspection_year_note == " ⏎ ".join(
        (
            "2020년 회계연도 감리에서 지적을 받았습니다",
            "감리를 받은 2021년 사업에 대한 보완입니다",
            "'19년 감리 지적",
        )
    )
    assert "이후 시행되는" not in (parsed.inspection_year_note or "")
    assert "증권선물" not in (parsed.inspection_year_note or "")
    fields = [vi_row_fields(row, rcept_dt="2022-06-30") for row in parsed.rows]
    assert [
        (row.source_cells, row.leading_blank, item.category_inherited)
        for row, item in zip(parsed.rows, fields)
    ] == [
        (5, False, 0),
        (4, True, 1),
        (4, False, 0),
        (4, False, 0),
        (3, False, 1),
        (4, False, 0),
    ]
    assert fields[0].recommend_date_iso == "2010-01-02"
    assert fields[0].vi_status == "ok"
    assert fields[1].recommend_date_format == "ymd_dot"
    assert fields[1].vi_status == "partial"
    assert fields[1].vi_status_reason == "recommend_date_invalid"
    assert fields[1].category_raw == "리더십"
    assert fields[2].recommend_date_format == "other"
    assert fields[2].vi_status_reason == "recommend_date_unrecognized"
    assert fields[3].recommend_date_format == "blank"
    assert fields[3].recommend_date_iso is None
    assert fields[3].vi_status == "ok"
    assert fields[3].vi_status_reason is None
    assert fields[3].action_date_in_text == 1
    assert fields[4].vi_status == "partial"
    assert fields[4].vi_status_reason == "recommend_date_out_of_range"
    assert parsed.rows[5].parse_status == "empty"
    assert fields[5].vi_status == "empty"
    assert fields[5].vi_status_reason == "placeholder_row"


def test_spaced_text_keeps_legal_prefix_and_nfc() -> None:
    """상호 정규화는 공백만 정리하고, 표시용 상호 함수는 쓰지 않는다."""
    assert normalize_spaced_text("주식회사\u00a0한빛  회계법인") == "주식회사 한빛 회계법인"
    assert normalize_spaced_text("업무의\u3000수행") == "업무의 수행"
    nfd = unicodedata.normalize("NFD", "업무의 수행")
    assert normalize_spaced_text(nfd) == "업무의 수행"
    assert normalize_firm_display_name("주식회사 한빛회계법인") == "한빛회계법인"
    row = LogicalRow(
        table_idx=0,
        row_idx=0,
        component=nfd,
        action_date="2019년 06월 01일",
        finding="권고",
        action="이행",
        parse_status="ok",
        source_cells=4,
        source_line_raw="업무의 수행 | 2019년 06월 01일 | 권고 | 이행",
    )
    assert vi_row_fields(row, rcept_dt="2019-06-28").category_raw == "업무의 수행"


def test_corp_name_and_body_hash_come_from_jsonl(tmp_path: Path) -> None:
    """법인명은 JSONL 원문을 공백 정규화만 하고, 본문 해시는 다시 계산하지 않는다."""
    body = "\n".join(
        (
            "2. 품질관리 감리결과",
            "구분 | 조치일자 | 개선권고사항 | 개선권고 이행상황",
            "리더십 | 2019년 06월 01일 | 권고 | 이행",
        )
    )
    corp_name = "주식회사\u00a0한빛  회계법인"
    record = {
        "schema_version": 1,
        "rcept_no": "20190628000299",
        "corp_code": "00512657",
        "corp_name": corp_name,
        "report_nm": "회계법인사업보고서",
        "correction_type": "최초공시",
        "submitter": "한빛",
        "rcept_dt": "2019-06-28",
        "bsns_year": None,
        "section_code": "VI",
        "section_title": "Ⅵ. 최근 3개 사업연도의 감리결과",
        "body_text": body,
        "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "body_chars": len(body),
        "source_url": "https://example.invalid/local-fixture",
        "fetched_at": "2026-11-05T00:00:00Z",
    }
    payload = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    path = _manifest(tmp_path / "one", payload)
    loaded = load_section_records(path)
    assert loaded[0].body_hash == record["body_hash"]
    documents = prepare_documents(path, {})
    assert documents[0].corp_name == "주식회사 한빛 회계법인"
    assert documents[0].body_hash == record["body_hash"]
    assert documents[0].subsection == "quality_control"


def test_modules_do_not_enable_llm_or_open_network() -> None:
    """유료 API와 네트워크 클라이언트를 읽거나 가져오지 않는다."""
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "research" / "extracting" / "firm_remediation.py",
        root / "research" / "models" / "firm_remediation.py",
        root / "research" / "repositories" / "firm_remediation_repository.py",
        root / "research" / "services" / "firm_remediation_loader.py",
        root / "research" / "services" / "firm_remediation_service.py",
        root / "scripts" / "extract_firm_remediation.py",
    ]
    banned = (
        "DART_LLM_ENABLED",
        "import httpx",
        "import requests",
        "openai",
        "anthropic",
        "aiohttp",
        "urllib",
        "http.client",
        "dart.fss.or.kr",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in source
    assert "ensure_ascii=False" in (root / "scripts" / "extract_firm_remediation.py").read_text(
        encoding="utf-8"
    )


async def test_sample_dry_run_does_not_create_db_and_write_fills_view(tmp_path: Path) -> None:
    """dry-run은 파일을 만들지 않고, 쓰기는 발견행과 둘째 표만 뷰에 올린다."""
    payload = SAMPLES.read_bytes()
    source = _manifest(tmp_path / "in", payload)
    catalog = tmp_path / "catalog.db"
    target = tmp_path / "out" / "firm.db"
    _catalog(catalog, _SAMPLE_CATALOG)
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(source),
            "--catalog",
            str(catalog),
            "--target-db",
            str(target),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "DART_LLM_ENABLED": "false"},
    )
    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert list(summary) == list(SUMMARY_KEYS)
    assert summary["documents"] == 5
    assert summary["logical_rows"] == 110
    assert summary["finding_rows"] == 91
    assert summary["placeholder_rows"] == 19
    assert summary["view_rows"] == 91
    assert summary["vi_status_partial"] == 1
    assert summary["second_table_rows"] == 39
    assert summary["period_key_missing"] == 0
    assert summary["subsection_quality_control"] == 2
    assert summary["subsection_auditor"] == 3
    assert not target.exists()

    await run_firm_remediation(
        input_path=source, catalog_path=catalog, write=True, target_db=target
    )
    connection = sqlite3.connect(target)
    columns = [row[1] for row in connection.execute("PRAGMA table_info(v_f004_vi_findings)")]
    assert tuple(columns) == VIEW_COLUMNS
    assert connection.execute("SELECT COUNT(*) FROM v_f004_vi_findings").fetchone()[0] == 91
    leaked = connection.execute(
        "SELECT COUNT(*) FROM v_f004_vi_findings WHERE action_date IS NOT NULL "
        "OR inspection_year IS NOT NULL OR category_raw IS NULL OR category_raw = '' "
        "OR source_line_raw NOT LIKE '%|%'"
    ).fetchone()[0]
    assert leaked == 0
    partial = connection.execute(
        "SELECT rcept_no, table_idx, row_idx, recommend_date_raw, parse_status, parse_reason "
        "FROM v_f004_vi_findings WHERE parse_status = 'partial'"
    ).fetchone()
    assert partial == (
        "20190628000221",
        0,
        8,
        "2106년 11월 18일",
        "partial",
        "recommend_date_out_of_range",
    )
    sanction = connection.execute(
        "SELECT COUNT(*) FROM v_f004_vi_findings WHERE recommend_date_raw = '2025-10-21' "
        "OR finding_text LIKE '%동일이사%'"
    ).fetchone()[0]
    assert sanction == 0
    fiscal = {
        row[0]: row[1:]
        for row in connection.execute(
            "SELECT rcept_no, fiscal_year, fiscal_year_src, corp_name FROM "
            "extraction_firm_remediation_documents"
        ).fetchall()
    }
    assert fiscal["20190628000221"] == (2019, "catalog.year_end", "효림회계법인")
    versions = {
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT parser_version FROM extraction_firm_remediation"
        )
    }
    assert versions == {PARSER_VERSION}
    finding_marks = ", ".join("?" for _ in FINDING_VI_STATUSES)
    finding_view = connection.execute(
        f"SELECT COUNT(*) FROM v_f004_vi_findings WHERE parse_status IN ({finding_marks})",
        FINDING_VI_STATUSES,
    ).fetchone()[0]
    view_total = connection.execute("SELECT COUNT(*) FROM v_f004_vi_findings").fetchone()[0]
    assert summary["finding_rows"] == finding_view
    assert summary["view_rows"] == view_total
    sample_groups = connection.execute("""
        SELECT corp_code, period_key, SUM(flag) FROM (
            SELECT corp_code, period_key, rcept_no, MAX(is_latest) AS flag
            FROM v_f004_vi_findings
            GROUP BY corp_code, period_key, rcept_no
        )
        GROUP BY corp_code, period_key
        """).fetchall()
    assert len(sample_groups) == 5
    assert [row[2] for row in sample_groups] == [1, 1, 1, 1, 1]
    connection.close()


async def test_empty_document_is_one_view_row_and_subsection_one_is_absent(
    tmp_path: Path,
) -> None:
    """빈 문서는 뷰에 1행이고, 소제목 없음과 표 안 빈 행은 뷰에 넣지 않는다."""
    catalog = tmp_path / "catalog.db"
    target = tmp_path / "old.db"
    _catalog(catalog, _OLD_CATALOG)
    await run_firm_remediation(
        input_path=OLD_FIXTURE, catalog_path=catalog, write=True, target_db=target
    )
    connection = sqlite3.connect(target)
    empty = connection.execute(
        "SELECT table_idx, row_idx, parse_status, parse_reason, corp_name, fiscal_year "
        "FROM v_f004_vi_findings WHERE rcept_no = '20200929000485'"
    ).fetchall()
    assert empty == [(None, None, "empty", "no_findings", "삼일회계법인", 2020)]
    missing = connection.execute(
        "SELECT COUNT(*) FROM v_f004_vi_findings WHERE rcept_no = '20160630000531'"
    ).fetchone()[0]
    assert missing == 0
    kept = connection.execute(
        "SELECT COUNT(*) FROM v_f004_vi_findings WHERE rcept_no = '20220930000262'"
    ).fetchone()[0]
    assert kept == 3
    stored_empty = connection.execute(
        "SELECT COUNT(*) FROM extraction_firm_remediation "
        "WHERE rcept_no = '20220930000262' AND parse_status = 'empty'"
    ).fetchone()[0]
    assert stored_empty == 1
    connection.close()


_V01_DDL = """
CREATE TABLE extraction_firm_remediation (
    rcept_no TEXT NOT NULL,
    table_idx INTEGER NOT NULL,
    row_idx INTEGER NOT NULL,
    corp_code TEXT NOT NULL,
    period_key TEXT,
    component TEXT NOT NULL,
    action_date TEXT NOT NULL,
    finding TEXT NOT NULL,
    action TEXT NOT NULL,
    is_latest INTEGER NOT NULL,
    parse_status TEXT NOT NULL,
    source_cells INTEGER NOT NULL,
    parser_version TEXT NOT NULL,
    extracted_at DATETIME NOT NULL,
    PRIMARY KEY (rcept_no, table_idx, row_idx)
);
CREATE TABLE extraction_firm_remediation_documents (
    rcept_no TEXT PRIMARY KEY,
    corp_code TEXT NOT NULL,
    period_key TEXT,
    rcept_dt TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    n_tables INTEGER NOT NULL,
    n_logical_rows INTEGER NOT NULL,
    n_notes INTEGER NOT NULL,
    parser_version TEXT NOT NULL,
    extracted_at DATETIME NOT NULL
);
"""


def _create_v01(path: Path) -> None:
    """PR #9 0.1 테이블만 만든다. 새 Ⅵ 열은 없다."""
    connection = sqlite3.connect(path)
    connection.executescript(_V01_DDL)
    connection.commit()
    connection.close()


def _insert_v01(
    path: Path,
    *,
    rcept_no: str,
    corp_code: str,
    period_key: str,
    rcept_dt: str,
    status: str = "table",
) -> None:
    """0.1 문서와 발견행 한 줄을 넣는다."""
    connection = sqlite3.connect(path)
    connection.execute(
        """
        INSERT INTO extraction_firm_remediation_documents (
            rcept_no, corp_code, period_key, rcept_dt, status, n_tables,
            n_logical_rows, n_notes, parser_version, extracted_at
        ) VALUES (?, ?, ?, ?, ?, 1, 1, 0, 'f004-remediation-0.1', '2019-06-28 00:00:00')
        """,
        (rcept_no, corp_code, period_key, rcept_dt, status),
    )
    connection.execute(
        """
        INSERT INTO extraction_firm_remediation (
            rcept_no, table_idx, row_idx, corp_code, period_key, component,
            action_date, finding, action, is_latest, parse_status, source_cells,
            parser_version, extracted_at
        ) VALUES (?, 0, 0, ?, ?, '리더십', '2019년 06월 01일', '기존 권고', '기존 이행',
                  1, 'ok', 4, 'f004-remediation-0.1', '2019-06-28 00:00:00')
        """,
        (rcept_no, corp_code, period_key),
    )
    connection.commit()
    connection.close()


async def test_v01_schema_gains_nullable_columns_and_a_view(tmp_path: Path) -> None:
    """0.1 행은 새 열이 NULL인 채로 남고, 뷰에서는 stale로 구분한다."""
    target = tmp_path / "legacy.db"
    _create_v01(target)
    _insert_v01(
        target,
        rcept_no="20190628000999",
        corp_code="00000001",
        period_key="2019-06",
        rcept_dt="2019-06-28",
    )

    engine = create_db_engine("sqlite+aiosqlite:///" + target.resolve().as_posix())
    await create_firm_remediation_tables(engine)
    await engine.dispose()

    connection = sqlite3.connect(target)
    row_columns = [
        row[1] for row in connection.execute("PRAGMA table_info(extraction_firm_remediation)")
    ]
    doc_columns = [
        row[1]
        for row in connection.execute("PRAGMA table_info(extraction_firm_remediation_documents)")
    ]
    assert "category_raw" in row_columns
    assert "vi_status" in row_columns
    assert "subsection" in doc_columns
    assert "inspection_year_note" in doc_columns
    stored = connection.execute(
        "SELECT component, action_date, finding, category_raw, vi_status, parser_version "
        "FROM extraction_firm_remediation"
    ).fetchone()
    assert stored == ("리더십", "2019년 06월 01일", "기존 권고", None, None, "f004-remediation-0.1")
    document = connection.execute(
        "SELECT rcept_dt, status, subsection, corp_name, fiscal_year FROM "
        "extraction_firm_remediation_documents"
    ).fetchone()
    assert document == ("2019-06-28", "table", None, None, None)
    viewed = connection.execute(
        "SELECT rcept_no, category_raw, parse_status, action_date, inspection_year, "
        "parser_version FROM v_f004_vi_findings"
    ).fetchone()
    assert viewed == ("20190628000999", None, "stale", None, None, "f004-remediation-0.1")
    assert connection.execute("SELECT parse_reason FROM v_f004_vi_findings").fetchone() == (
        "rerun_required",
    )
    connection.close()


def _section_record(**overrides: object) -> dict[str, object]:
    """해시가 맞는 최소 JSONL 객체를 만든다."""
    body = "\n".join(
        (
            "2. 품질관리 감리결과",
            "구분 | 조치일자 | 개선권고사항 | 개선권고 이행상황",
            "리더십 | 2019년 06월 01일 | 권고 | 이행",
        )
    )
    record: dict[str, object] = {
        "schema_version": 1,
        "rcept_no": "20190628000299",
        "corp_code": "00512657",
        "corp_name": "효림회계법인",
        "report_nm": "회계법인사업보고서",
        "correction_type": "최초공시",
        "submitter": "효림회계법인",
        "rcept_dt": "2019-06-28",
        "bsns_year": None,
        "section_code": "VI",
        "section_title": "Ⅵ. 최근 3개 사업연도의 감리결과",
        "body_text": body,
        "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "body_chars": len(body),
        "source_url": "https://example.invalid/local-fixture",
        "fetched_at": "2026-11-05T00:00:00Z",
    }
    record.update(overrides)
    return record


def test_body_hash_rejects_missing_or_null_and_stores_lowercase(tmp_path: Path) -> None:
    """body_hash 키가 없거나 None이면 적재를 멈추고, 대문자 hex는 소문자로 저장한다."""
    missing = _section_record()
    del missing["body_hash"]
    missing_path = _manifest(
        tmp_path / "missing",
        (json.dumps(missing, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    with pytest.raises(FirmRemediationLoadError, match="body_hash"):
        load_section_records(missing_path)

    empty_hash = _section_record(body_hash=None)
    none_path = _manifest(
        tmp_path / "none",
        (json.dumps(empty_hash, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    with pytest.raises(FirmRemediationLoadError, match="해시가 일치하지 않습니다"):
        load_section_records(none_path)

    original = _section_record()
    upper = _section_record(body_hash=str(original["body_hash"]).upper())
    upper_path = _manifest(
        tmp_path / "upper",
        (json.dumps(upper, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    loaded = load_section_records(upper_path)
    assert loaded[0].body_hash == original["body_hash"]
    assert loaded[0].body_hash == str(loaded[0].body_hash).lower()
    assert len(str(loaded[0].body_hash)) == 64


def _multi_flag(finding: str) -> int:
    """다건 플래그만 본다. 정규식은 바꾸지 않는다."""
    row = LogicalRow(
        table_idx=0,
        row_idx=0,
        component="구분",
        action_date="-",
        finding=finding,
        action="-",
        parse_status="ok",
        source_cells=4,
    )
    return vi_row_fields(row, rcept_dt="2023-06-30").multi_finding_flag


def test_multi_finding_flag_matches_reviewed_examples() -> None:
    """전수 검토에서 참·거짓으로 갈린 문장을 그대로 확인한다."""
    assert _multi_flag("- 품질 개선 - 자원할당 부족") == 1
    assert _multi_flag("① 감사계획 ② 커뮤니케이션") == 1
    assert _multi_flag("미흡 외 13건") == 1
    assert _multi_flag("1. 감사계획 미흡 2. 커뮤니케이션 미흡") == 1
    assert _multi_flag("2023. 04.25 개선권고 이행") == 0
    assert _multi_flag("감사-보고 절차 미흡") == 0
    assert _multi_flag("1. 감사계획 수립절차 미흡") == 0
    assert _multi_flag("- 독립성 점검절차 미비") == 0
    assert _multi_flag("② 독립성 점검시스템 구축ㆍ운영 미흡") == 0
    assert _multi_flag("외부감사 절차 미흡") == 0
    assert _multi_flag("2019.03.12 - 2019.05.28 기간 감리") == 0


def test_blank_rcept_dt_skips_only_the_upper_year_bound() -> None:
    """접수연도가 없으면 2010 하한과 달력 검사만 남긴다."""
    raw, iso, date_format, reason = _recommend_date("2019년 03월 12일", "")
    assert (raw, iso, date_format, reason) == ("2019년 03월 12일", "2019-03-12", "ymd_kor", None)
    _raw, early_iso, _fmt, early_reason = _recommend_date("2002.04.27", "")
    assert early_iso is None
    assert early_reason == "recommend_date_out_of_range"


def _view_groups(connection: sqlite3.Connection) -> list[tuple]:
    """뷰 문서를 결산기 묶음으로 모아 묶음별 is_latest=1 문서 수를 센다."""
    return connection.execute("""
        SELECT corp_code, period_key, SUM(flag) FROM (
            SELECT corp_code, period_key, rcept_no, MAX(is_latest) AS flag
            FROM v_f004_vi_findings
            GROUP BY corp_code, period_key, rcept_no
        )
        GROUP BY corp_code, period_key
        ORDER BY corp_code, period_key
        """).fetchall()


async def test_empty_view_is_latest_follows_period_group(tmp_path: Path) -> None:
    """빈 문서 뷰 행의 is_latest는 결산기 최신 접수와 같고 NULL이 없다."""
    catalog = tmp_path / "catalog.db"
    target = tmp_path / "old.db"
    _catalog(catalog, _OLD_CATALOG)
    await run_firm_remediation(
        input_path=OLD_FIXTURE, catalog_path=catalog, write=True, target_db=target
    )
    documents = prepare_documents(
        OLD_FIXTURE, fetch_year_ends(catalog, [row[0] for row in _OLD_CATALOG])
    )
    python_flags = {
        document.rcept_no: document.rows[0].is_latest for document in documents if document.rows
    }
    summary = summarize(documents)
    connection = sqlite3.connect(target)
    view_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'view' AND name = 'v_f004_vi_findings'"
    ).fetchone()[0]
    assert (
        "is_latest = 결산기(corp_code, period_key)별 최신 정정 공시이며, 법인 전체나 지적 키 기준이 아님."
        in view_sql
    )
    assert (
        "empty 문서 행도 같은 정의이며, 그 문서 기본 행의 MAX(is_latest)에서 가져온다." in view_sql
    )
    assert "parse_status='stale'" in view_sql
    flags = dict(
        connection.execute(
            "SELECT rcept_no, MAX(is_latest) FROM v_f004_vi_findings GROUP BY rcept_no"
        ).fetchall()
    )
    assert flags["20200929000485"] == 1
    assert flags["20200630000215"] == 0
    assert flags["20201202000259"] == 1
    assert "20160630000531" not in flags
    assert flags == python_flags
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM v_f004_vi_findings WHERE is_latest IS NULL"
        ).fetchone()[0]
        == 0
    )
    empty_null = connection.execute(
        "SELECT COUNT(*) FROM v_f004_vi_findings "
        "WHERE parse_status = 'empty' AND is_latest IS NULL"
    ).fetchone()[0]
    assert empty_null == 0
    groups = _view_groups(connection)
    assert len(groups) == 6
    assert all(row[2] == 1 for row in groups)
    finding_marks = ", ".join("?" for _ in FINDING_VI_STATUSES)
    finding_view = connection.execute(
        f"SELECT COUNT(*) FROM v_f004_vi_findings WHERE parse_status IN ({finding_marks})",
        FINDING_VI_STATUSES,
    ).fetchone()[0]
    assert summary["finding_rows"] == finding_view
    assert (
        summary["view_rows"]
        == connection.execute("SELECT COUNT(*) FROM v_f004_vi_findings").fetchone()[0]
    )
    connection.close()


async def test_rewritten_v01_rows_match_a_fresh_view_except_the_leftover(
    tmp_path: Path,
) -> None:
    """입력에 있는 0.1 접수는 새 DB와 같고, 없는 접수만 stale로 남는다."""
    catalog = tmp_path / "catalog.db"
    source = _manifest(tmp_path / "in", SAMPLES.read_bytes())
    legacy = tmp_path / "legacy.db"
    fresh = tmp_path / "fresh.db"
    _catalog(catalog, _SAMPLE_CATALOG)
    _create_v01(legacy)
    _insert_v01(
        legacy,
        rcept_no="20190628000221",
        corp_code="00512657",
        period_key="2019-06",
        rcept_dt="2019-06-28",
    )
    _insert_v01(
        legacy,
        rcept_no="20190628000999",
        corp_code="00000099",
        period_key="1999-01",
        rcept_dt="2019-06-28",
    )
    await run_firm_remediation(
        input_path=source, catalog_path=catalog, write=True, target_db=legacy
    )
    await run_firm_remediation(input_path=source, catalog_path=catalog, write=True, target_db=fresh)
    connection = sqlite3.connect(legacy)
    connection.execute("ATTACH DATABASE ? AS fresh", (str(fresh.resolve()),))
    only_legacy = connection.execute("""
        SELECT * FROM v_f004_vi_findings WHERE rcept_no != '20190628000999'
        EXCEPT
        SELECT * FROM fresh.v_f004_vi_findings
        """).fetchall()
    only_fresh = connection.execute("""
        SELECT * FROM fresh.v_f004_vi_findings
        EXCEPT
        SELECT * FROM v_f004_vi_findings WHERE rcept_no != '20190628000999'
        """).fetchall()
    stale = connection.execute(
        "SELECT parse_status, parse_reason FROM v_f004_vi_findings "
        "WHERE rcept_no = '20190628000999'"
    ).fetchall()
    fresh_stale = connection.execute(
        "SELECT COUNT(*) FROM fresh.v_f004_vi_findings WHERE parse_status = 'stale'"
    ).fetchone()[0]
    connection.close()
    assert only_legacy == []
    assert only_fresh == []
    assert stale == [("stale", "rerun_required")]
    assert fresh_stale == 0


async def test_empty_document_without_rows_recomputes_is_latest(tmp_path: Path) -> None:
    """행이 없는 empty 문서는 결산기 비교로 is_latest를 채운다."""
    target = tmp_path / "empty-only.db"
    engine = create_db_engine("sqlite+aiosqlite:///" + target.resolve().as_posix())
    await create_firm_remediation_tables(engine)
    await engine.dispose()
    connection = sqlite3.connect(target)
    rows = (
        ("20200630000001", "00000077", "2020-03", "2020-06-30", "quality_control"),
        ("20201202000001", "00000077", "2020-03", "2020-12-02", "quality_control"),
        ("20210630000001", "00000088", None, "2021-06-30", "quality_control"),
    )
    for rcept_no, corp_code, period_key, rcept_dt, subsection in rows:
        connection.execute(
            """
            INSERT INTO extraction_firm_remediation_documents (
                rcept_no, corp_code, period_key, rcept_dt, status, n_tables,
                n_logical_rows, n_notes, subsection, parser_version, extracted_at
            ) VALUES (?, ?, ?, ?, 'empty', 0, 0, 0, ?, 'f004-remediation-0.2',
                      '2021-06-30 00:00:00')
            """,
            (rcept_no, corp_code, period_key, rcept_dt, subsection),
        )
    connection.commit()
    flags = dict(
        connection.execute(
            "SELECT rcept_no, is_latest FROM v_f004_vi_findings ORDER BY rcept_no"
        ).fetchall()
    )
    connection.close()
    assert flags == {
        "20200630000001": 0,
        "20201202000001": 1,
        "20210630000001": 0,
    }


async def test_view_ddl_drops_then_creates_for_sqlite_and_postgres() -> None:
    """Postgres도 CREATE OR REPLACE 대신 DROP 다음 CREATE를 같은 연결에서 실행한다."""

    class _Dialect:
        def __init__(self, name: str) -> None:
            self.name = name

    class _Connection:
        def __init__(self, name: str) -> None:
            self.dialect = _Dialect(name)
            self.statements: list[str] = []

        async def execute(self, statement: object) -> None:
            self.statements.append(str(statement))

    source = (
        Path(__file__).resolve().parents[1]
        / "research"
        / "repositories"
        / "firm_remediation_repository.py"
    ).read_text(encoding="utf-8")
    before_select = source.split("_VI_VIEW_SELECT", 1)[0]
    assert (
        "is_latest = 결산기(corp_code, period_key)별 최신 정정 공시이며, 법인 전체나 지적 키 기준이 아님."
        in before_select
    )
    assert (
        "empty 문서 행도 같은 정의이며, 그 문서 기본 행의 MAX(is_latest)에서 가져온다."
        in before_select
    )
    assert _ensure_vi_view.__doc__ is not None
    assert (
        "is_latest = 결산기(corp_code, period_key)별 최신 정정 공시이며, 법인 전체나 지적 키 기준이 아님."
        in _ensure_vi_view.__doc__
    )
    assert (
        "empty 문서 행도 같은 정의이며, 그 문서 기본 행의 MAX(is_latest)에서 가져온다."
        in _ensure_vi_view.__doc__
    )
    for name in ("sqlite", "postgresql"):
        connection = _Connection(name)
        await _ensure_vi_view(connection)  # type: ignore[arg-type]
        assert len(connection.statements) == 2
        assert connection.statements[0] == "DROP VIEW IF EXISTS v_f004_vi_findings"
        assert connection.statements[1].startswith("CREATE VIEW v_f004_vi_findings AS")
        assert "CREATE OR REPLACE" not in connection.statements[1]
        assert (
            "is_latest = 결산기(corp_code, period_key)별 최신 정정 공시이며, 법인 전체나 지적 키 기준이 아님."
            in connection.statements[1]
        )
        assert (
            "empty 문서 행도 같은 정의이며, 그 문서 기본 행의 MAX(is_latest)에서 가져온다."
            in connection.statements[1]
        )
        assert "parse_status='stale'" in connection.statements[1]
