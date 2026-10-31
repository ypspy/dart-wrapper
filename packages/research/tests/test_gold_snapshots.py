"""추출기 버전별 facts 스냅샷."""

from __future__ import annotations

import pytest

from research.gold.snapshots import capture, load_snapshot
from gold_fixtures import run_sample


def test_capture_and_load(tmp_path) -> None:
    conn, run_id = run_sample(tmp_path, "x")
    captured = capture(conn, run_id, "audit_opinion.v19")
    sample_count = conn.execute("SELECT count(*) FROM gold_samples").fetchone()[0]
    assert captured == sample_count
    row = conn.execute("SELECT rcept_no, dcm_no FROM gold_samples LIMIT 1").fetchone()
    snapshot = load_snapshot(conn, "audit_opinion.v19", row[0], row[1])
    assert snapshot is not None
    assert snapshot["extractor_version"] == "audit_opinion.v19"
    assert capture(conn, run_id, "audit_opinion.v19") == 0


def test_version_mismatch_refused(tmp_path) -> None:
    conn, run_id = run_sample(tmp_path, "x")
    with pytest.raises(ValueError):
        capture(conn, run_id, "audit_opinion.v20")
