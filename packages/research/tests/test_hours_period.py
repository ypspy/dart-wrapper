"""단일 기간 감사시간 가드. unknown을 무조건 당기로 보지 않는다."""

from __future__ import annotations

from hours_period_samples import single_period_hours
from research.extracting.hours_period import is_single_period_hours, total_cells


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
