"""필드 묶음 12개 성공·해당없음·제도상없음·실패 분류."""

from app.extracting.field_bundles import (
    BUNDLE_KEYS,
    add_fact_outcomes,
    classify_outcome,
    empty_field_bundle_counts,
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
