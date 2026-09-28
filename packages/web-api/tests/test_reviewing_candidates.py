"""진단 후보 순수 계산."""

from __future__ import annotations

import math

from app.reviewing.candidates import (
    FactView,
    numeric_candidates,
    quartile_bounds,
    select_panel_ids,
)


def view(index: int, **overrides: object) -> FactView:
    """번호만 다른 최소 행."""
    values: dict[str, object] = {
        "rcept_no": f"202003{index:08d}",
        "dcm_no": "1",
        "source_report_type": "F001",
        "fs_scope": "separate",
    }
    values.update(overrides)
    return FactView(**values)  # type: ignore[arg-type]


def test_quartile_bounds_none_when_short_or_flat() -> None:
    assert quartile_bounds([1.0] * 29) is None
    assert quartile_bounds([math.log1p(10.0)] * 30) is None


def test_numeric_flags_hours_forbidden_and_asset_tail() -> None:
    mass = [
        view(
            index,
            hours=[{"role": "total", "metric": "audit", "period": "current", "value": 100}],
            hours_status="ok",
            accounts=[
                {"account": "total_asset", "period": "current", "status": "ok", "value_won": 1_000},
                {"account": "net_income", "period": "current", "status": "ok", "value_won": -5},
                {"account": "total_equity", "period": "current", "status": "ok", "value_won": -5},
            ],
            accounts_status="ok",
        )
        for index in range(30)
    ]
    huge = view(
        30,
        hours=[{"role": "total", "metric": "audit", "period": "current", "value": 0}],
        hours_status="ok",
        accounts=[
            {"account": "total_asset", "period": "current", "status": "ok", "value_won": -1},
            {"account": "current_liability", "period": "current", "status": "ok", "value_won": 0},
        ],
        accounts_status="ok",
    )
    missing = view(31, hours=[], hours_status="ok")
    duplicate = view(
        32,
        hours=[
            {"role": "total", "metric": "audit", "period": "current", "value": 1},
            {"role": "total", "metric": "audit", "period": "current", "value": 2},
        ],
        hours_status="ok",
    )
    panel = {("20200300000030", "1")}
    candidates, summary = numeric_candidates([*mass, huge, missing, duplicate], panel)
    signals = {(item.rcept_no, item.signal, item.subject) for item in candidates}
    assert ("20200300000030", "hours_nonpositive", "audit_current_total") in signals
    assert ("20200300000030", "account_negative", "total_asset") in signals
    assert not any(
        item.subject == "net_income" and item.signal == "account_negative" for item in candidates
    )
    assert not any(
        item.subject == "total_equity" and item.signal == "account_negative" for item in candidates
    )
    assert not any(
        item.subject == "current_liability" and item.signal == "account_negative"
        for item in candidates
    )
    assert ("20200300000031", "hours_total_missing", "audit_current_total") in signals
    assert not any(item.rcept_no == "20200300000032" for item in candidates)
    assert any(
        row.section == "skip" and row.key == "hours_total_duplicate" and row.n == 1
        for row in summary
    )
    assert not any(
        item.signal == "iqr_high"
        and item.subject == "total_asset"
        and item.rcept_no == "20200300000030"
        for item in candidates
    )


def test_unit_missing_and_subsidiary_and_date() -> None:
    rows = [
        view(
            index,
            source_report_type="F002",
            fs_scope="consolidated",
            subsidiary_status="ok",
            subsidiary_count=3,
            audit_report_date_status="ok",
            audit_report_date="2020-03-15",
            year_end="2020.02",
            accounts=[
                {
                    "account": "total_asset",
                    "period": "current",
                    "status": "ok",
                    "value_won": None,
                }
            ],
            accounts_status="ok",
        )
        for index in range(1, 31)
    ]
    zero_sub = view(
        40,
        source_report_type="F002",
        fs_scope="consolidated",
        subsidiary_status="ok",
        subsidiary_count=0,
    )
    negative_sub = view(
        41,
        source_report_type="F002",
        fs_scope="consolidated",
        subsidiary_status="ok",
        subsidiary_count=-1,
    )
    early = view(
        42,
        audit_report_date_status="ok",
        audit_report_date="2020-01-31",
        year_end="2020.01",
        fs_scope="separate",
    )
    candidates, _summary = numeric_candidates([*rows, zero_sub, negative_sub, early], set())
    signals = {(item.signal, item.subject, item.rcept_no) for item in candidates}
    assert ("unit_missing", "total_asset", "20200300000001") in signals
    assert ("subsidiary_negative", "subsidiary_count", "20200300000041") in signals
    assert not any(
        item.signal == "subsidiary_negative" and item.rcept_no.endswith("40") for item in candidates
    )
    assert ("date_nonpositive", "lag_days", "20200300000042") in signals


def test_panel_queue_order_is_extreme_five() -> None:
    facts = []
    panel: set[tuple[str, str]] = set()
    for index in range(30):
        if index == 0:
            amount = 1
        elif index == 29:
            amount = 10**9
        else:
            amount = 1000 + index
        fact = view(
            index,
            accounts=[
                {
                    "account": "total_asset",
                    "period": "current",
                    "status": "ok",
                    "value_won": amount,
                }
            ],
            accounts_status="ok",
            corp_code="C",
        )
        facts.append(fact)
        panel.add((fact.rcept_no, fact.dcm_no))
    facts.append(
        view(
            80,
            accounts=[
                {
                    "account": "total_asset",
                    "period": "current",
                    "status": "ok",
                    "value_won": 10**12,
                }
            ],
            accounts_status="ok",
        )
    )
    candidates, _summary = numeric_candidates(facts, panel)
    highs = [
        item
        for item in candidates
        if item.signal == "iqr_high" and item.subject == "total_asset" and item.queue_order == 1
    ]
    assert len(highs) == 1
    assert highs[0].rcept_no == "20200300000029"
    assert highs[0].raw_value == "1000000000"
    assert highs[0].in_research_panel is True
    assert highs[0].tail == "high"
    lows = [
        item
        for item in candidates
        if item.signal == "iqr_low" and item.subject == "total_asset" and item.queue_order == 1
    ]
    assert len(lows) == 1
    assert lows[0].rcept_no == "20200300000000"
    assert lows[0].raw_value == "1"
    assert lows[0].in_research_panel is True
    outsider = [
        item
        for item in candidates
        if item.rcept_no == "20200300000080" and item.signal == "iqr_high"
    ]
    assert outsider[0].queue_order is None
    assert outsider[0].in_research_panel is False


def test_panel_prefers_consolidated_then_f_then_latest() -> None:
    rows = [
        view(
            1,
            corp_code="C",
            year_end="2019.12",
            rcept_dt="20200301",
            fs_scope="separate",
            source_report_type="F001",
        ),
        view(
            2,
            corp_code="C",
            year_end="2019.12",
            rcept_dt="20200302",
            fs_scope="consolidated",
            source_report_type="A001",
        ),
        view(
            3,
            corp_code="C",
            year_end="2019.12",
            rcept_dt="20200303",
            fs_scope="consolidated",
            source_report_type="F002",
        ),
        view(
            4,
            corp_code="C",
            year_end="2019.12",
            rcept_dt="20200304",
            fs_scope="consolidated",
            source_report_type="F002",
        ),
        view(
            5,
            corp_code=None,
            year_end="2019.12",
            rcept_dt="20200304",
            fs_scope="separate",
            source_report_type="F001",
        ),
        view(
            6,
            corp_code="D",
            year_end="2015.12",
            rcept_dt="20160115",
            fs_scope="separate",
            source_report_type="F001",
        ),
        view(
            7,
            corp_code="E",
            year_end="2020.12",
            rcept_dt="20261001",
            fs_scope="separate",
            source_report_type="F001",
        ),
        view(
            8,
            corp_code="F",
            year_end="2020.06",
            rcept_dt="20200701",
            fs_scope="unknown",
            source_report_type="F001",
        ),
    ]
    assert select_panel_ids(rows) == {("20200300000004", "1")}
