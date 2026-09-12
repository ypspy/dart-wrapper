"""감사 facts 필드 묶음 12개의 성공·실패 분류."""

from __future__ import annotations

from typing import Literal

from app.models.audit_report_fact import AuditReportFact

FieldBundleOutcome = Literal["ok", "not_applicable", "expected_missing", "fail"]

_BUNDLE_ROWS: tuple[tuple[str, str, str], ...] = (
    ("auditor", "auditor_status", "감사인"),
    ("opinion", "opinion_status", "감사의견"),
    ("gaap", "gaap_status", "GAAP"),
    ("audit_report_date", "audit_report_date_status", "감사보고서일"),
    ("current_period", "current_period_status", "당기"),
    ("hours", "hours_status", "감사시간"),
    ("activities", "activities_status", "실시항목"),
    ("communications", "communications_status", "커뮤니케이션"),
    ("accounts", "accounts_status", "계정"),
    ("icfr", "icfr_status", "내부회계"),
    ("going_concern", "going_concern_status", "계속기업"),
    ("subsidiary", "subsidiary_status", "종속기업"),
)

BUNDLE_KEYS: tuple[str, ...] = tuple(row[0] for row in _BUNDLE_ROWS)
BUNDLE_LABELS: dict[str, str] = {row[0]: row[2] for row in _BUNDLE_ROWS}
FIELD_BUNDLE_REPORT_TYPES: tuple[str, ...] = ("F001", "F002", "A001")
EXPORT_PAGE_SIZE = 5000
DART_DISCLOSURE_VIEW = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def status_attr(bundle: str) -> str:
    """bundle 키에 대응하는 facts 컬럼 이름."""
    for key, attr, _label in _BUNDLE_ROWS:
        if key == bundle:
            return attr
    raise KeyError(bundle)


def classify_outcome(
    bundle: str,
    *,
    fs_scope: str,
    status: str | None,
    hours_status: str | None = None,
    activities_status: str | None = None,
) -> FieldBundleOutcome:
    """한 문서·한 묶음의 네 칸 중 하나를 고른다."""
    if (
        bundle == "subsidiary"
        and fs_scope != "consolidated"
        and status == "not_applicable"
    ):
        return "not_applicable"
    if (
        bundle == "communications"
        and status == "not_found"
        and hours_status == "ok"
        and activities_status == "ok"
    ):
        return "expected_missing"
    if status == "ok":
        return "ok"
    return "fail"


def empty_field_bundle_counts() -> dict[str, dict[str, int]]:
    """잡 params·집계 초기값."""
    return {
        key: {
            "ok": 0,
            "not_applicable": 0,
            "expected_missing": 0,
            "fail": 0,
        }
        for key in BUNDLE_KEYS
    }


def add_fact_outcomes(
    counts: dict[str, dict[str, int]],
    fact: AuditReportFact,
) -> None:
    """fetch_status=ok 행만 12묶음에 더한다."""
    if fact.fetch_status != "ok":
        return
    for bundle in BUNDLE_KEYS:
        outcome = classify_outcome(
            bundle,
            fs_scope=fact.fs_scope,
            status=getattr(fact, status_attr(bundle)),
            hours_status=fact.hours_status,
            activities_status=fact.activities_status,
        )
        counts[bundle][outcome] += 1
