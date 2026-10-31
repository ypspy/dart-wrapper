"""라벨 이력, 완료 조건, 블라인드 지연, 예비 승격."""

from __future__ import annotations

import inspect

import pytest

from research.gold import labels as labels_module
from research.gold.labels import (
    complete_doc,
    exclude_doc,
    next_doc,
    required_subjects,
    save_label,
)
from gold_fixtures import first_main, run_sample

_VERSION = "audit_opinion.v19"


def _fill(conn, run_id: str, rcept_no: str, dcm_no: str, pass_: str) -> None:
    """문서의 필수 항목을 모두 맞음으로 저장한다."""
    for bundle, subject in required_subjects(conn, run_id, rcept_no, dcm_no):
        save_label(
            conn,
            rcept_no=rcept_no,
            dcm_no=dcm_no,
            bundle=bundle,
            subject=subject,
            pass_=pass_,
            verdict="correct",
            gold_value="ok",
            shown_value="ok",
            shown_version=_VERSION,
        )


def test_label_history(tmp_path) -> None:
    conn, run_id = run_sample(tmp_path, "x")
    doc = first_main(conn)
    common = {
        "rcept_no": doc["rcept_no"],
        "dcm_no": doc["dcm_no"],
        "bundle": "opinion",
        "subject": "value",
        "pass_": "prefill",
        "shown_value": "unqualified",
        "shown_version": _VERSION,
    }
    save_label(conn, **common, verdict="correct", gold_value="unqualified")
    save_label(conn, **common, verdict="wrong", gold_value="qualified")
    assert conn.execute("SELECT count(*) FROM gold_label_history").fetchone()[0] == 1
    del run_id


def test_blind_prefill_ordering(tmp_path) -> None:
    """블라인드를 끝낸 문서는 prefill 큐에서 최소 20건 뒤에 나온다."""
    conn, run_id = run_sample(tmp_path, "x")
    period = "P7"
    blind = conn.execute(
        """
        SELECT rcept_no, dcm_no FROM gold_samples
        WHERE run_id = ? AND period = ? AND mode = 'blind' AND role = 'main'
        ORDER BY queue_order LIMIT 1
        """,
        (run_id, period),
    ).fetchone()
    assert blind is not None
    blind_key = (blind[0], blind[1])
    _fill(conn, run_id, blind[0], blind[1], "blind")
    complete_doc(conn, run_id, blind[0], blind[1], "blind")
    for _ in range(19):
        nxt = next_doc(conn, run_id, period, "prefill")
        assert nxt is not None
        assert nxt != blind_key
        _fill(conn, run_id, nxt[0], nxt[1], "prefill")
        complete_doc(conn, run_id, nxt[0], nxt[1], "prefill")
    found = False
    for _ in range(8):
        nxt = next_doc(conn, run_id, period, "prefill")
        if nxt == blind_key:
            found = True
            break
        assert nxt is not None
        _fill(conn, run_id, nxt[0], nxt[1], "prefill")
        complete_doc(conn, run_id, nxt[0], nxt[1], "prefill")
    assert found


def test_complete_requires_all(tmp_path) -> None:
    conn, run_id = run_sample(tmp_path, "x")
    doc = first_main(conn)
    with pytest.raises(ValueError):
        complete_doc(conn, run_id, doc["rcept_no"], doc["dcm_no"], "prefill")


def test_exclude_promotes_reserve(tmp_path) -> None:
    conn, run_id = run_sample(tmp_path, "x")
    doc = first_main(conn)
    promoted = exclude_doc(
        conn, run_id, doc["rcept_no"], doc["dcm_no"], "감사의감사보고서"
    )
    assert promoted is not None
    assert promoted != (doc["rcept_no"], doc["dcm_no"])


def test_never_writes_extraction_reviews() -> None:
    source = inspect.getsource(labels_module).lower()
    assert "insert into cat.extraction_reviews" not in source
    assert "insert into extraction_reviews" not in source
