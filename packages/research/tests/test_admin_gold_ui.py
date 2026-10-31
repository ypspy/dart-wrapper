"""골드 검수 화면. 예측값은 블라인드에서 내려가지 않는다."""

from __future__ import annotations

import inspect
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from research.api.admin.gold import get_gold_conn
from research.extracting.constants import EXTRACTOR_VERSION
from research.extracting.field_bundles import BUNDLE_KEYS
from research.gold.db import migrate, open_gold
from research.gold.subjects import subjects_for
from conftest import create_app

_STRINGS = ("회계법인서정", "unqualified", "15,277,377,649")


@dataclass
class _Doc:
    rcept_no: str
    dcm_no: str
    extracted_strings: tuple[str, ...]


def _expected_rows() -> int:
    return sum(len(subjects_for(bundle)) for bundle in BUNDLE_KEYS)


def _seed(tmp_path):
    catalog = tmp_path / "catalog.db"
    raw = sqlite3.connect(catalog)
    raw.executescript("""
        CREATE TABLE disclosures (
            rcept_no TEXT PRIMARY KEY, corp_code TEXT, rcept_dt TEXT,
            year_end TEXT, correction_type TEXT, report_nm TEXT, report_type TEXT
        );
        CREATE TABLE corps (corp_code TEXT PRIMARY KEY, corp_cls TEXT, corp_name TEXT);
        CREATE TABLE entries (
            entry_id TEXT PRIMARY KEY, rcept_no TEXT, dcm_no TEXT,
            section_name TEXT, ele_id TEXT, dtd TEXT, viewer_url TEXT
        );
        CREATE TABLE audit_report_facts (
            rcept_no TEXT, dcm_no TEXT, extractor_version TEXT, fetch_status TEXT,
            PRIMARY KEY (rcept_no, dcm_no)
        );
        CREATE TABLE extraction_reviews (
            rcept_no TEXT, dcm_no TEXT, bundle TEXT, signal TEXT, subject TEXT
        );
        """)
    gold_path = tmp_path / "gold.db"
    conn = open_gold(gold_path, catalog)
    migrate(conn)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO gold_runs (
            run_id, seed, created_at, population_sql_sha, db_snapshot, params, stats
        ) VALUES ('gold-2026-10', 'gold-2026-10', ?, 'x', '{}', '{}', '{}')
        """,
        (now,),
    )
    docs = {
        "prefill": _Doc("20240315000111", "11", _STRINGS),
        "blind": _Doc("20240315000222", "22", _STRINGS),
    }
    for mode, doc in docs.items():
        raw.execute(
            "INSERT INTO disclosures (rcept_no, rcept_dt, year_end) "
            "VALUES (?, '20240315', '2023.12')",
            (doc.rcept_no,),
        )
        viewer = (
            "https://dart.fss.or.kr/dsaf001/main.do"
            f"?rcpNo={doc.rcept_no}&dcmNo={doc.dcm_no}"
        )
        entry_id = f"{doc.rcept_no}:bs"
        raw.execute(
            """
            INSERT INTO entries (entry_id, rcept_no, dcm_no, section_name, ele_id, viewer_url)
            VALUES (?, ?, ?, '재무상태표', '4', ?)
            """,
            (entry_id, doc.rcept_no, doc.dcm_no, viewer),
        )
        meta = {
            "in_extraction_reviews": 1 if mode == "prefill" else 0,
            "catalog_as_of": now,
        }
        conn.execute(
            """
            INSERT INTO gold_samples (
                run_id, rcept_no, dcm_no, period, stratum, stratum_weight, sample_hash,
                mode, role, queue_order, status, meta
            ) VALUES ('gold-2026-10', ?, ?, 'P7', 'P7', 1, 'h', ?, 'main', ?, 'todo', ?)
            """,
            (
                doc.rcept_no,
                doc.dcm_no,
                mode,
                1 if mode == "prefill" else 2,
                json.dumps(meta),
            ),
        )
        payload = {
            "rcept_no": doc.rcept_no,
            "dcm_no": doc.dcm_no,
            "extractor_version": EXTRACTOR_VERSION,
            "auditor_resolved": _STRINGS[0],
            "auditor_status": "ok",
            "opinion_resolved": _STRINGS[1],
            "opinion_status": "ok",
            "accounts_status": "ok",
            "accounts": [
                {
                    "account": "total_asset",
                    "period": "current",
                    "raw": _STRINGS[2],
                    "unit_raw": "원",
                    "value": 15277377649,
                }
            ],
            "bs_entry_id": entry_id,
        }
        conn.execute(
            """
            INSERT INTO extractor_snapshots (
                extractor_version, rcept_no, dcm_no, payload, captured_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                EXTRACTOR_VERSION,
                doc.rcept_no,
                doc.dcm_no,
                json.dumps(payload, ensure_ascii=False),
                now,
            ),
        )
    raw.commit()
    raw.close()
    conn.commit()
    conn.close()
    return gold_path, catalog, docs


@pytest.fixture
def gold_env(tmp_path):
    """임시 gold.db를 붙인 앱. 실제 카탈로그는 열지 않는다."""
    gold_path, catalog, docs = _seed(tmp_path)
    app = create_app()

    def _override():
        conn = open_gold(gold_path, catalog)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_gold_conn] = _override
    prefill = docs["prefill"]
    blind = docs["blind"]
    return type(
        "GoldEnv",
        (),
        {
            "app": app,
            "gold_path": gold_path,
            "prefill_doc": prefill,
            "blind_doc": blind,
            "prefill_url": f"/admin/gold/doc/{prefill.rcept_no}/{prefill.dcm_no}?pass=prefill",
            "blind_url": f"/admin/gold/doc/{blind.rcept_no}/{blind.dcm_no}?pass=blind",
            "expected_rows": _expected_rows(),
        },
    )()


@pytest.fixture
async def authed_client(client_factory, gold_env):
    """관리자 쿠키가 있는 클라이언트."""
    async with client_factory(gold_env.app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        yield client


async def test_requires_token(client_factory, gold_env) -> None:
    async with client_factory(gold_env.app) as client:
        response = await client.get("/admin/gold", follow_redirects=False)
    assert response.status_code in (302, 303)


async def test_blind_hides_extracted_values(authed_client, gold_env) -> None:
    doc = gold_env.blind_doc
    response = await authed_client.get(
        f"/admin/gold/doc/{doc.rcept_no}/{doc.dcm_no}?pass=blind"
    )
    assert response.status_code == 200
    for value in doc.extracted_strings:
        assert value not in response.text
    assert 'data-evidence-autonav="1"' in response.text
    assert 'data-highlight="0"' in response.text


async def test_prefill_shows_values_and_overlap_badge(authed_client, gold_env) -> None:
    response = await authed_client.get(gold_env.prefill_url)
    assert response.status_code == 200
    assert gold_env.prefill_doc.extracted_strings[0] in response.text
    assert "리뷰 중복" in response.text


async def test_label_post_roundtrip(authed_client, gold_env) -> None:
    doc = gold_env.prefill_doc
    response = await authed_client.post(
        "/admin/gold/label",
        json={
            "rcept_no": doc.rcept_no,
            "dcm_no": doc.dcm_no,
            "bundle": "opinion",
            "subject": "value",
            "pass": "prefill",
            "verdict": "correct",
            "gold_value": "unqualified",
            "shown_value": "unqualified",
            "shown_version": EXTRACTOR_VERSION,
        },
    )
    assert response.status_code == 200
    conn = open_gold(gold_env.gold_path, None)
    try:
        assert conn.execute("SELECT count(*) FROM gold_labels").fetchone()[0] == 1
    finally:
        conn.close()


async def test_evidence_offline_fallback_link(authed_client, gold_env) -> None:
    doc = gold_env.prefill_doc
    response = await authed_client.get(
        f"/admin/gold/evidence/{doc.rcept_no}/{doc.dcm_no}/accounts?pass=prefill"
    )
    assert response.status_code == 200
    assert "dart.fss.or.kr" in response.text
    assert "<iframe" not in response.text.lower()


def test_no_llm_import() -> None:
    import research.api.admin.gold as gold

    source = inspect.getsource(gold)
    assert "llm_date_resolver" not in source
    assert "DateResolverService" not in source


async def test_rows_have_contract(authed_client, gold_env) -> None:
    response = await authed_client.get(gold_env.prefill_url)
    assert response.text.count('class="gold-row"') == gold_env.expected_rows
    assert 'data-subject="total_asset@prior"' in response.text


async def test_blind_disables_bulk_accept(authed_client, gold_env) -> None:
    response = await authed_client.get(gold_env.blind_url)
    assert 'data-bulk-accept="0"' in response.text
