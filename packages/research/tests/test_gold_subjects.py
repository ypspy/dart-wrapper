"""채점 단위와 리뷰 subject 매핑."""

from __future__ import annotations

from research.extracting.field_bundles import BUNDLE_KEYS
from research.gold.subjects import ACCOUNTS, extract_predicted, subjects_for


def test_every_bundle_has_subjects() -> None:
    for bundle in BUNDLE_KEYS:
        assert subjects_for(bundle)


def test_accounts_22_cells() -> None:
    assert len(ACCOUNTS) == 11
    subjects = subjects_for("accounts")
    assert len(subjects) == 22
    assert "total_asset@prior" in subjects


def test_icfr_two_subjects() -> None:
    assert subjects_for("icfr") == ["engagement", "opinion"]


def test_extract_account_display_value() -> None:
    row = {
        "accounts": (
            '[{"account":"inventory","period":"current","raw":"1,234",'
            '"unit_raw":"천원","unit_scale":1000,"value":1234}]'
        )
    }
    assert extract_predicted(row, "accounts", "inventory@current") == {
        "raw": "1,234",
        "unit_raw": "천원",
        "value": 1234,
    }
    assert extract_predicted(row, "accounts", "inventory@prior") is None
