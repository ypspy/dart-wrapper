"""골드 감사시간 핵심값. 단일 기간만 unknown 합계를 읽고 마지막 칸을 쓴다."""

from __future__ import annotations

from hours_period_samples import comparative_hours, single_period_hours
from research.gold.scoring import _hours_keys
from research.reviewing.candidates import FactView, numeric_candidates


def test_hours_keys_single_period_returns_unknown_totals() -> None:
    """단일 기간 24칸이면 unknown 합계의 감사시간과 투입 인원을 돌려준다."""
    table = single_period_hours(audit_total=100, headcount_total=15)
    assert _hours_keys(table) == (100, 15)


def test_hours_keys_current_prior_returns_last_current_total() -> None:
    """새 서식은 당기 합계만 쓰고, 같은 합계가 여러 칸이면 마지막 값이다."""
    table = comparative_hours(
        audit_current=100, audit_prior=80, headcount_current=7, headcount_prior=5
    )
    table.insert(
        1,
        {
            "role": "total",
            "role_raw": "합계",
            "metric": "audit",
            "metric_raw": "audit",
            "period": "current",
            "period_raw": "당기",
            "raw": "140",
            "value": 140,
            "unmapped": False,
        },
    )
    table.append(
        {
            "role": "total",
            "role_raw": "합계",
            "metric": "headcount",
            "metric_raw": "headcount",
            "period": "current",
            "period_raw": "당기",
            "raw": "9",
            "value": 9,
            "unmapped": False,
        }
    )
    assert _hours_keys(table) == (140, 9)


def test_hours_keys_mixed_periods_returns_none() -> None:
    """current·prior가 섞인 표의 unknown 합계는 핵심값이 아니다."""
    table = single_period_hours(audit_total=100, headcount_total=15)
    partner = next(
        cell for cell in table if cell["role"] == "engagement_partner" and cell["metric"] == "audit"
    )
    partner["period"] = "current"
    partner["period_raw"] = "당기"
    other = next(cell for cell in table if cell["role"] == "cpa" and cell["metric"] == "audit")
    other["period"] = "prior"
    other["period_raw"] = "전기"
    assert _hours_keys(table) == (None, None)


def test_hours_keys_duplicate_role_columns_returns_none() -> None:
    """역할당 2열로 같은 키가 두 번이면 unknown이어도 (None, None)이다."""
    table = single_period_hours(audit_total=100, headcount_total=15)
    table = [*table, *[dict(cell) for cell in table]]
    assert _hours_keys(table) == (None, None)


def test_hours_keys_distinct_total_columns_return_none_and_missing() -> None:
    """단일 기간에서 role_raw가 다른 합계 2열이면 골드는 (None, None)이고 큐는 missing이다.

    r3에서 기대값 변경(검토 중간 1·2).
    """
    table = single_period_hours(audit_total=100, headcount_total=15)
    total = next(cell for cell in table if cell["role"] == "total" and cell["metric"] == "audit")
    table.append(dict(total, role_raw="합 계", value=120, raw="120"))
    assert _hours_keys(table) == (None, None)
    fact = FactView(
        rcept_no="R-HOURS-2",
        dcm_no="D1",
        source_report_type="F001",
        fs_scope="separate",
        hours=table,
        hours_status="ok",
    )
    candidates, summary = numeric_candidates([fact], set())
    assert [item.signal for item in candidates if item.bundle == "hours"] == ["hours_total_missing"]
    assert not any(row.key == "hours_total_duplicate" for row in summary)
