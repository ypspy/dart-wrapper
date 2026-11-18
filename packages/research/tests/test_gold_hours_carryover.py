"""단일 기간 감사시간의 골드 이월·재채점. 합성 표와 임시 gold.db만 쓴다."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hours_period_samples import comparative_hours, single_period_hours
from research.gold.db import migrate, open_gold
from research.gold.scoring import score, table_carryover

_OLD = "audit_opinion.v19"
_NEW = "audit_opinion.v20"


def _prepare(
    tmp_path: Path,
    *,
    old_hours: list[dict[str, object]],
    new_hours: list[dict[str, object]],
    gold_value: dict[str, Any] | None,
) -> sqlite3.Connection:
    """임시 gold.db에 실행·표본·v19/v20 스냅샷·hours 라벨을 넣는다.

    gold_value가 None이면 gold UI의 맞음 저장과 같이 SQL NULL을 넣는다.
    """
    conn = open_gold(tmp_path / "gold.db", None)
    migrate(conn)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO gold_runs (
            run_id, seed, created_at, population_sql_sha, db_snapshot, params, stats
        ) VALUES ('gold-test', 'gold-test', ?, 'x', '{}', '{}', '{}')
        """,
        (now,),
    )
    conn.execute("""
        INSERT INTO gold_samples (
            run_id, rcept_no, dcm_no, period, stratum, stratum_weight, sample_hash,
            mode, role, queue_order, status, meta
        ) VALUES (
            'gold-test', 'R1', 'D1', 'P7', 's', 1, 'h', 'prefill', 'main', 1, 'todo', '{}'
        )
        """)
    for version, hours in ((_OLD, old_hours), (_NEW, new_hours)):
        payload = {
            "extractor_version": version,
            "rcept_no": "R1",
            "dcm_no": "D1",
            "hours": hours,
            "hours_status": "ok",
        }
        conn.execute(
            """
            INSERT INTO extractor_snapshots (
                extractor_version, rcept_no, dcm_no, payload, captured_at
            ) VALUES (?, 'R1', 'D1', ?, ?)
            """,
            (version, json.dumps(payload, ensure_ascii=False), now),
        )
    conn.execute(
        """
        INSERT INTO gold_labels (
            rcept_no, dcm_no, bundle, subject, pass, verdict, gold_value, shown_value,
            shown_extractor_version, note, labeled_at
        ) VALUES ('R1', 'D1', 'hours', 'table', 'prefill', 'correct', ?, ?, ?, '', ?)
        """,
        (
            None if gold_value is None else json.dumps(gold_value, ensure_ascii=False),
            json.dumps(old_hours, ensure_ascii=False),
            _OLD,
            now,
        ),
    )
    conn.commit()
    return conn


def _other_cell_changed() -> list[dict[str, object]]:
    """합계가 아닌 첫 칸만 바꾼 단일 기간 표를 돌려준다."""
    hours = single_period_hours()
    hours[0] = dict(hours[0], raw="2", value=2)
    return hours


def _two_totals(
    *,
    left_audit: int = 100,
    right_audit: int = 90,
    left_headcount: int = 15,
    right_headcount: int = 14,
) -> list[dict[str, object]]:
    """「합계」와 「합 계」 두 열. 감사·인원 합계를 각각 두 칸으로 둔다."""
    hours = single_period_hours(audit_total=left_audit, headcount_total=left_headcount)
    audit = next(cell for cell in hours if cell["role"] == "total" and cell["metric"] == "audit")
    head = next(cell for cell in hours if cell["role"] == "total" and cell["metric"] == "headcount")
    hours.append(dict(audit, role_raw="합 계", value=right_audit, raw=str(right_audit)))
    hours.append(dict(head, role_raw="합 계", value=right_headcount, raw=str(right_headcount)))
    return hours


def _carry(conn: sqlite3.Connection) -> tuple[str | None, int]:
    """table_carryover의 (gold_scores.outcome, 재검수 큐 건수)."""
    queued = table_carryover(conn, _OLD, _NEW)
    row = conn.execute("SELECT outcome FROM gold_scores WHERE bundle = 'hours'").fetchone()
    return (None if row is None else str(row[0]), len(queued))


def test_same_single_period_table_carries_verdict(tmp_path: Path) -> None:
    """표가 같으면 판정을 넘긴다. v19끼리라 _hours_keys를 부르지 않고 tp, 큐 0이다."""
    table = single_period_hours()
    conn = _prepare(
        tmp_path,
        old_hours=table,
        new_hours=table,
        gold_value={"verdict": "correct"},
    )
    assert _carry(conn) == ("tp", 0)


def test_changed_single_period_total_is_fp(tmp_path: Path) -> None:
    """단일 기간 합계가 100에서 90으로 바뀌면 FP이고 재검수 큐는 0이다.

    라벨에 audit_hours가 없으면 이전 스냅샷 합계가 정답이다.
    합계가 바뀌면 재검수가 아니라 FP로 본다.
    """
    conn = _prepare(
        tmp_path,
        old_hours=single_period_hours(audit_total=100),
        new_hours=single_period_hours(audit_total=90),
        gold_value={"verdict": "correct"},
    )
    assert _carry(conn) == ("fp", 0)


def test_non_total_cell_change_without_answer_keys_is_queued(tmp_path: Path) -> None:
    """합계가 아닌 칸만 바뀌고 라벨이 verdict뿐이면 핵심값이 같아 abstain, 큐 1이다."""
    conn = _prepare(
        tmp_path,
        old_hours=single_period_hours(),
        new_hours=_other_cell_changed(),
        gold_value={"verdict": "correct"},
    )
    assert _carry(conn) == ("abstain", 1)


def test_explicit_null_answer_keys_make_non_total_change_fp(tmp_path: Path) -> None:
    """라벨에 audit_hours·headcount가 null이면 합계 외 변경도 FP다.

    동작 변화다. 정답을 (None, None)으로 보아 단일 기간 합계 (100, 15)와 다르다.
    현재 gold UI는 audit_hours를 쓰지 않고 gold.db 라벨이 0건이라 실제 영향은 없다.
    """
    conn = _prepare(
        tmp_path,
        old_hours=single_period_hours(),
        new_hours=_other_cell_changed(),
        gold_value={"verdict": "correct", "audit_hours": None, "headcount": None},
    )
    assert _carry(conn) == ("fp", 0)


def test_matching_explicit_answer_keys_queue_non_total_change(tmp_path: Path) -> None:
    """라벨 정답 100/15와 새 합계가 같으면 다른 칸의 변경은 재검수다.

    자동 FP였던 경우가 abstain, 큐 1로 바뀐다.
    """
    conn = _prepare(
        tmp_path,
        old_hours=single_period_hours(),
        new_hours=_other_cell_changed(),
        gold_value={"verdict": "correct", "audit_hours": 100, "headcount": 15},
    )
    assert _carry(conn) == ("abstain", 1)


def test_same_total_on_new_comparative_table_is_queued(tmp_path: Path) -> None:
    """단일 기간 100/15가 새 서식 당기 100/15로 바뀌면 합계가 같아 재검수다.

    라벨에 audit_hours가 없으면 이전 합계와 비교한다. abstain, 큐 1이다.
    합계가 같으면 재검수로 본다.
    """
    conn = _prepare(
        tmp_path,
        old_hours=single_period_hours(audit_total=100, headcount_total=15),
        new_hours=comparative_hours(audit_current=100, audit_prior=80, headcount_current=15),
        gold_value={"verdict": "correct"},
    )
    assert _carry(conn) == ("abstain", 1)


def test_score_table_bundle_uses_verdict_not_hours_keys(tmp_path: Path) -> None:
    """score()의 표 묶음 판정은 verdict만 보고 _hours_keys를 쓰지 않아 tp다."""
    table = single_period_hours()
    conn = _prepare(
        tmp_path,
        old_hours=table,
        new_hours=table,
        gold_value={"verdict": "correct"},
    )
    assert score(conn, _OLD) == 1
    row = conn.execute(
        """
        SELECT outcome FROM gold_scores
        WHERE extractor_version = ? AND bundle = 'hours' AND subject = 'table'
        """,
        (_OLD,),
    ).fetchone()
    assert row is not None
    assert row[0] == "tp"


def test_n10_single_to_two_totals_with_null_gold_is_fp(tmp_path: Path) -> None:
    """단일 100/15가 합계 100과 합 계 90이 되면 키가 사라져 FP이고 큐는 0이다.

    gold_value는 SQL NULL이다. current 표에서 합계가 사라질 때의 master 의미와 같다.
    """
    conn = _prepare(
        tmp_path,
        old_hours=single_period_hours(audit_total=100, headcount_total=15),
        new_hours=_two_totals(),
        gold_value=None,
    )
    stored = conn.execute("SELECT gold_value FROM gold_labels").fetchone()
    assert stored is not None
    assert stored[0] is None
    assert _carry(conn) == ("fp", 0)


def test_n11_left_total_change_with_null_gold_stays_queued(tmp_path: Path) -> None:
    """두 합계에서 왼쪽 감사만 80으로 바뀌면 키가 둘 다 없어 abstain, 큐 1이다."""
    conn = _prepare(
        tmp_path,
        old_hours=_two_totals(),
        new_hours=_two_totals(left_audit=80),
        gold_value=None,
    )
    assert _carry(conn) == ("abstain", 1)


def test_n12_right_total_change_with_null_gold_is_queued(tmp_path: Path) -> None:
    """두 합계에서 오른쪽 감사만 70으로 바뀌면 abstain, 큐 1이다."""
    conn = _prepare(
        tmp_path,
        old_hours=_two_totals(),
        new_hours=_two_totals(right_audit=70),
        gold_value=None,
    )
    assert _carry(conn) == ("abstain", 1)


def test_n13_nontotal_change_on_two_totals_with_null_gold_is_queued(tmp_path: Path) -> None:
    """두 합계는 유지하고 비합계 칸만 바꾸면 abstain, 큐 1이다."""
    changed = _two_totals()
    changed[0] = dict(changed[0], raw="2", value=2)
    conn = _prepare(
        tmp_path,
        old_hours=_two_totals(),
        new_hours=changed,
        gold_value=None,
    )
    assert _carry(conn) == ("abstain", 1)


def test_n15_label_matches_new_total_is_queued(tmp_path: Path) -> None:
    """라벨 정답이 이전 표와 다르고 새 표와 같으면 abstain, 큐 1이다."""
    conn = _prepare(
        tmp_path,
        old_hours=single_period_hours(audit_total=100, headcount_total=15),
        new_hours=single_period_hours(audit_total=90, headcount_total=15),
        gold_value={"verdict": "correct", "audit_hours": 90, "headcount": 15},
    )
    assert _carry(conn) == ("abstain", 1)
