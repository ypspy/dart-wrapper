"""필드 묶음 12개 성공·해당없음·제도상없음·실패 분류."""

from app.extracting.field_bundles import (
    BUNDLE_KEYS,
    add_fact_outcomes,
    classify_outcome,
    empty_field_bundle_counts,
    icfr_period_year,
    is_icfr_expected_missing,
    is_listed_for_icfr,
)
from app.models.audit_report_fact import AuditReportFact
from app.extracting.constants import EXTRACTOR_VERSION


def test_twelve_bundle_keys_in_spec_order() -> None:
    assert BUNDLE_KEYS == (
        "auditor",
        "opinion",
        "gaap",
        "audit_report_date",
        "current_period",
        "hours",
        "activities",
        "communications",
        "accounts",
        "icfr",
        "going_concern",
        "subsidiary",
    )


def test_separate_subsidiary_not_applicable_is_not_ok() -> None:
    assert (
        classify_outcome(
            "subsidiary",
            fs_scope="separate",
            status="not_applicable",
        )
        == "not_applicable"
    )


def test_unknown_scope_subsidiary_not_applicable() -> None:
    assert (
        classify_outcome(
            "subsidiary",
            fs_scope="unknown",
            status="not_applicable",
        )
        == "not_applicable"
    )


def test_communications_expected_missing_when_hours_and_activities_ok() -> None:
    assert (
        classify_outcome(
            "communications",
            fs_scope="separate",
            status="not_found",
            hours_status="ok",
            activities_status="ok",
        )
        == "expected_missing"
    )


def test_communications_not_found_is_fail_if_hours_skipped() -> None:
    assert (
        classify_outcome(
            "communications",
            fs_scope="separate",
            status="not_found",
            hours_status="skipped",
            activities_status="ok",
        )
        == "fail"
    )


def test_consolidated_subsidiary_not_found_is_fail() -> None:
    assert (
        classify_outcome(
            "subsidiary",
            fs_scope="consolidated",
            status="not_found",
        )
        == "fail"
    )


def test_ok_status_is_ok() -> None:
    assert classify_outcome("opinion", fs_scope="separate", status="ok") == "ok"


def test_f001_skipped_unlisted_is_expected_missing() -> None:
    for corp_cls in ("E", None, ""):
        assert (
            classify_outcome(
                "icfr",
                fs_scope="separate",
                status="skipped",
                report_type="F001",
                corp_cls=corp_cls,
            )
            == "expected_missing"
        )


def test_f001_skipped_listed_is_fail() -> None:
    for corp_cls in ("Y", "K", "N"):
        assert (
            classify_outcome(
                "icfr",
                fs_scope="separate",
                status="skipped",
                report_type="F001",
                corp_cls=corp_cls,
            )
            == "fail"
        )


def test_f002_skipped_before_2023_is_expected_missing() -> None:
    assert (
        classify_outcome(
            "icfr",
            fs_scope="consolidated",
            status="skipped",
            report_type="F002",
            period_year=2022,
        )
        == "expected_missing"
    )


def test_f002_skipped_from_2023_is_fail() -> None:
    assert (
        classify_outcome(
            "icfr",
            fs_scope="consolidated",
            status="skipped",
            report_type="F002",
            period_year=2023,
        )
        == "fail"
    )


def test_f002_skipped_unknown_year_is_fail() -> None:
    assert (
        classify_outcome(
            "icfr",
            fs_scope="consolidated",
            status="skipped",
            report_type="F002",
            period_year=None,
        )
        == "fail"
    )


def test_a001_skipped_is_fail_regardless_of_listing() -> None:
    assert (
        classify_outcome(
            "icfr",
            fs_scope="separate",
            status="skipped",
            report_type="A001",
            corp_cls="E",
            period_year=2016,
        )
        == "fail"
    )


def test_icfr_not_found_is_fail() -> None:
    assert (
        classify_outcome(
            "icfr",
            fs_scope="separate",
            status="not_found",
            report_type="F001",
            corp_cls="E",
        )
        == "fail"
    )


def test_icfr_ok_is_ok() -> None:
    assert classify_outcome("icfr", fs_scope="separate", status="ok") == "ok"


def test_icfr_period_year_prefers_year_end() -> None:
    assert icfr_period_year("(2019.12)", "2020.03.31") == 2019
    assert icfr_period_year(None, "2020.03.31") == 2020
    assert icfr_period_year(None, None) is None


def test_is_listed_for_icfr_includes_konex() -> None:
    assert is_listed_for_icfr("N") is True
    assert is_listed_for_icfr("E") is False


def test_add_fact_outcomes_skips_non_ok_fetch() -> None:
    counts = empty_field_bundle_counts()
    fact = AuditReportFact(
        rcept_no="1",
        dcm_no="1",
        source_report_type="F001",
        fs_scope="separate",
        fetch_status="fetch_failed",
        extractor_version=EXTRACTOR_VERSION,
        subsidiary_status="not_applicable",
        opinion_status="skipped",
    )
    add_fact_outcomes(counts, fact)
    assert counts["opinion"]["fail"] == 0
    assert counts["subsidiary"]["not_applicable"] == 0


def test_add_fact_outcomes_counts_ok_fetch() -> None:
    counts = empty_field_bundle_counts()
    fact = AuditReportFact(
        rcept_no="1",
        dcm_no="1",
        source_report_type="F001",
        fs_scope="separate",
        fetch_status="ok",
        extractor_version=EXTRACTOR_VERSION,
        opinion_status="ok",
        subsidiary_status="not_applicable",
        hours_status="ok",
        activities_status="ok",
        communications_status="not_found",
    )
    add_fact_outcomes(counts, fact)
    assert counts["opinion"]["ok"] == 1
    assert counts["subsidiary"]["not_applicable"] == 1
    assert counts["communications"]["expected_missing"] == 1
