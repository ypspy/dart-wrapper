"""근거 섹션과 셀 하이라이트."""

from __future__ import annotations

import sqlite3

from research.gold.db import open_gold
from research.gold.evidence import annotate_cells, evidence_for, find_cells


def test_annotate_and_find() -> None:
    html = "<table><tr><td>재고자산</td><td>1,234</td><td>999</td></tr></table>"
    out = annotate_cells(html)
    assert 'data-t="0" data-r="0" data-c="1"' in out
    assert find_cells(out, "1,234", "재고자산") == [(0, 0, 1)]


def test_evidence_uses_entries(tmp_path) -> None:
    catalog = tmp_path / "catalog.db"
    conn = sqlite3.connect(catalog)
    conn.execute("""
        CREATE TABLE entries (
            entry_id TEXT PRIMARY KEY,
            section_name TEXT,
            viewer_url TEXT,
            ele_id TEXT
        )
        """)
    conn.execute("""
        INSERT INTO entries (entry_id, section_name, viewer_url, ele_id)
        VALUES ('bs1', '재무상태표', 'https://dart.fss.or.kr/report/viewer.do?rcpNo=1', '4')
        """)
    conn.commit()
    conn.close()
    gold = open_gold(tmp_path / "gold.db", catalog)
    found = evidence_for(
        gold,
        {"bs_entry_id": "bs1", "rcept_no": "20240315000001", "dcm_no": "9"},
        "accounts",
    )
    assert found
    assert found[0].viewer_url.startswith("https://dart.fss.or.kr")
    assert "rcpNo=20240315000001" in found[0].dart_url
    assert "dcmNo=9" in found[0].dart_url
