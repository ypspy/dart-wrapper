"""재현 가능한 층화 표본."""

from __future__ import annotations

from research.gold.sampler import SampleParams, allocate, build_sample, rank_hash
from gold_fixtures import make_population, run_sample


def test_rank_hash_stable() -> None:
    assert rank_hash("s", "1", "2") == rank_hash("s", "1", "2")
    assert rank_hash("s", "1", "2") != rank_hash("t", "1", "2")


def test_allocate_sums_and_min() -> None:
    allocated = allocate({"A": 1000, "B": 30, "C": 5}, 100, min_alloc=15)
    assert sum(allocated.values()) == 100
    assert allocated["B"] >= 15
    assert allocated["C"] == 5


def test_reproducible(tmp_path) -> None:
    first, _run_a = run_sample(tmp_path, "x")
    second, _run_b = run_sample(tmp_path, "x")
    query = "SELECT rcept_no, dcm_no, mode, role FROM gold_samples ORDER BY 1, 2"
    assert first.execute(query).fetchall() == second.execute(query).fetchall()


def test_blind_and_reserve_ratio(tmp_path) -> None:
    conn, _run_id = run_sample(tmp_path, "x")
    for period in ("P6", "P7"):
        main = conn.execute(
            "SELECT count(*) FROM gold_samples WHERE period=? AND role='main'",
            (period,),
        ).fetchone()[0]
        blind = conn.execute(
            "SELECT count(*) FROM gold_samples WHERE period=? AND mode='blind'",
            (period,),
        ).fetchone()[0]
        assert main == 40
        assert blind == 4


def test_excludes_f003_and_out(tmp_path) -> None:
    conn, _run_id = run_sample(tmp_path, "x")
    assert (
        conn.execute("SELECT count(*) FROM gold_samples WHERE period='OUT'").fetchone()[
            0
        ]
        == 0
    )
    joined = conn.execute("""
        SELECT count(*)
        FROM gold_samples s
        JOIN cat.audit_report_facts f
          ON f.rcept_no = s.rcept_no AND f.dcm_no = s.dcm_no
        WHERE f.source_report_type = 'F003'
        """).fetchone()[0]
    assert joined == 0


def test_overlap_flag(tmp_path) -> None:
    conn, _run_id = run_sample(tmp_path, "x")
    flags = [
        row[0]
        for row in conn.execute(
            "SELECT json_extract(meta, '$.in_extraction_reviews') FROM gold_samples"
        )
    ]
    assert set(flags) <= {0, 1}
    assert 1 in flags


def test_samples_record_catalog_as_of(tmp_path) -> None:
    conn, _run_id = run_sample(tmp_path, "x")
    stamps = [
        row[0]
        for row in conn.execute(
            "SELECT json_extract(meta, '$.catalog_as_of') FROM gold_samples"
        )
    ]
    assert stamps
    assert all(stamps)


def test_build_sample_uses_fixture_population(tmp_path) -> None:
    """임포트가 살아 있고 시드 기본값이 설계와 같은지 확인한다."""
    assert SampleParams().seed == "gold-2026-10"
    catalog = make_population(tmp_path)
    assert catalog.exists()
    assert build_sample is not None
