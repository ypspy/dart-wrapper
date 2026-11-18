"""단일 기간 감사시간 가드. unknown을 무조건 당기로 보지 않는다."""

from __future__ import annotations

from hours_period_samples import single_period_hours
from research.extracting.hours_period import is_single_period_hours, total_cells
from research.gold.scoring import _hours_keys
from research.reviewing.candidates import numeric_candidates
from test_reviewing_candidates import view


def test_single_period_24_cells_accepts_unknown_total() -> None:
    """24칸이 모두 unknown이고 역할 키가 한 번씩이면 가드가 참이고 unknown 합계를 고른다."""
    hours = single_period_hours(audit_total=100, headcount_total=15)
    assert len(hours) == 24
    assert is_single_period_hours(hours) is True
    audit = total_cells(hours, "audit")
    headcount = total_cells(hours, "headcount")
    assert audit is not None and len(audit) == 1
    assert audit[0]["period"] == "unknown"
    assert audit[0]["value"] == 100
    assert headcount is not None and len(headcount) == 1
    assert headcount[0]["value"] == 15
    interim = total_cells(hours, "interim_review")
    assert interim is not None and len(interim) == 1
    assert interim[0]["period"] == "unknown"
    assert interim[0]["value"] == 1


def test_period_raw_blocks_single_period() -> None:
    """period가 unknown이어도 period_raw가 있으면 당기 표시가 있는 것으로 본다."""
    hours = single_period_hours()
    hours[0]["period_raw"] = "당기"
    assert is_single_period_hours(hours) is False
    assert total_cells(hours, "audit") == []


def test_mixed_current_prior_blocks_single_period() -> None:
    """current·prior가 섞이면 가드가 거짓이고 unknown 합계를 당기로 읽지 않는다."""
    hours = single_period_hours()
    hours[1]["period"] = "current"
    hours[1]["period_raw"] = "당기"
    hours[2]["period"] = "prior"
    hours[2]["period_raw"] = "전기"
    assert is_single_period_hours(hours) is False
    assert total_cells(hours, "audit") == []


def test_duplicate_role_key_blocks_single_period() -> None:
    """같은 (role, role_raw, metric)이 두 번이면 역할당 2열이라 가드가 거짓이다."""
    hours = single_period_hours()
    hours.append(dict(hours[-1]))
    assert is_single_period_hours(hours) is False
    assert total_cells(hours, "audit") == []


def test_empty_list_is_not_single_period() -> None:
    """빈 리스트는 단일 기간이 아니고, 합계 칸은 빈 리스트다."""
    assert is_single_period_hours([]) is False
    assert total_cells([], "audit") == []


def test_non_list_is_not_single_period() -> None:
    """리스트가 아니면 가드는 거짓이고 합계 칸은 None이다."""
    assert is_single_period_hours(None) is False
    assert is_single_period_hours({"role": "total"}) is False
    assert total_cells(None, "audit") is None
    assert total_cells({"role": "total"}, "audit") is None


def test_non_dict_element_blocks_single_period() -> None:
    """dict가 아닌 원소가 있으면 가드가 거짓이다."""
    hours = single_period_hours()
    hours.append("칸아님")
    assert is_single_period_hours(hours) is False
    assert is_single_period_hours(["칸아님"]) is False


def test_n8_role_list_is_missing_without_type_error() -> None:
    """한 칸의 role이 리스트면 가드가 거짓이고 후보 계산이 예외 없이 끝난다.

    정상 fact는 신호가 없고, 그 fact는 missing 1건이다. _hours_keys는 (None, None)이다.
    """
    normal = single_period_hours(audit_total=100, headcount_total=15)
    broken = single_period_hours(audit_total=100, headcount_total=15)
    broken[0]["role"] = ["qcr"]
    assert is_single_period_hours(broken) is False
    assert _hours_keys(broken) == (None, None)
    normal_fact = view(81, hours=normal, hours_status="ok")
    broken_fact = view(82, hours=broken, hours_status="ok")
    candidates, _summary = numeric_candidates([normal_fact, broken_fact], set())
    assert [item for item in candidates if item.rcept_no == normal_fact.rcept_no] == []
    broken_rows = [item for item in candidates if item.rcept_no == broken_fact.rcept_no]
    assert [item.signal for item in broken_rows] == ["hours_total_missing"]


def _unknown_metric_row(
    source: list[dict[str, object]], metric_raw: str
) -> list[dict[str, object]]:
    """감사 행의 역할마다 모르는 지표 칸을 만든다. unmapped는 True다."""
    return [
        dict(cell, metric="other", metric_raw=metric_raw, raw="9", value=9, unmapped=True)
        for cell in source
        if cell["metric"] == "audit"
    ]


def test_n16_one_unknown_metric_row_stays_single_period() -> None:
    """모르는 지표 행이 하나면 가드가 참이고 합계는 (100, 15)다."""
    hours = single_period_hours(audit_total=100, headcount_total=15)
    hours.extend(_unknown_metric_row(hours, "기타시간"))
    assert len([cell for cell in hours if cell["metric"] == "other"]) == 6
    assert is_single_period_hours(hours) is True
    assert _hours_keys(hours) == (100, 15)


def test_n17_two_unknown_metric_rows_are_rejected() -> None:
    """모르는 지표 행이 둘이면 키가 겹쳐 가드가 거짓이고 합계 키는 (None, None)이다."""
    hours = single_period_hours(audit_total=100, headcount_total=15)
    hours.extend(_unknown_metric_row(hours, "기타시간"))
    hours.extend(_unknown_metric_row(hours, "다른시간"))
    assert is_single_period_hours(hours) is False
    assert _hours_keys(hours) == (None, None)


def test_n24_non_string_period_raw_is_rejected() -> None:
    """period_raw가 0·False·[]이면 빈 값으로 보지 않고 가드가 거짓이다."""
    for raw in (0, False, []):
        hours = single_period_hours(audit_total=100, headcount_total=15)
        hours[0]["period_raw"] = raw
        assert is_single_period_hours(hours) is False


def test_n9_role_raw_dict_is_missing_without_type_error() -> None:
    """같은 24칸에서 role_raw가 dict면 가드가 거짓이고 예외가 나지 않는다."""
    normal = single_period_hours(audit_total=100, headcount_total=15)
    broken = single_period_hours(audit_total=100, headcount_total=15)
    broken[0]["role_raw"] = {"raw": "제47기"}
    assert is_single_period_hours(broken) is False
    assert _hours_keys(broken) == (None, None)
    normal_fact = view(83, hours=normal, hours_status="ok")
    broken_fact = view(84, hours=broken, hours_status="ok")
    candidates, _summary = numeric_candidates([normal_fact, broken_fact], set())
    assert [item for item in candidates if item.rcept_no == normal_fact.rcept_no] == []
    broken_rows = [item for item in candidates if item.rcept_no == broken_fact.rcept_no]
    assert [item.signal for item in broken_rows] == ["hours_total_missing"]
