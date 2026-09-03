"""Public 감사 추출 결과 응답 스키마."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _empty_communications() -> dict[str, Any]:
    """커뮤니케이션 JSON 기본값. 공유 가변 dict를 쓰지 않는다."""
    return {"has_audit_committee": False, "items": []}


class AuditReportFactItem(BaseModel):
    """감사보고서 문서 한 행. LLM 내부 메타(date_resolver_*)는 공개하지 않는다."""

    model_config = ConfigDict(from_attributes=True)

    rcept_no: str
    dcm_no: str
    source_report_type: str
    fs_scope: str

    cover_entry_id: str | None = None
    opinion_entry_id: str | None = None
    activity_entry_id: str | None = None
    a001_opinion_entry_id: str | None = None
    a001_cover_entry_id: str | None = None

    auditor: str | None = None
    auditor_body: str | None = None
    auditor_a001: str | None = None
    auditor_listing: str | None = None
    auditor_status: str | None = None
    auditor_resolved: str | None = None
    auditor_source: str | None = None

    opinion_raw: str | None = None
    opinion_code: str | None = None
    opinion_status: str | None = None
    opinion_resolved: str | None = None
    opinion_source: str | None = None

    audit_report_date_raw: str | None = None
    audit_report_date_candidates: list[Any] = Field(default_factory=list)
    audit_report_date: str | None = None
    audit_report_date_status: str | None = None
    audit_report_date_source: str | None = None
    audit_report_date_override: str | None = None

    gaap_raw: str | None = None
    gaap_code: str | None = None
    gaap_status: str | None = None
    gaap_resolved: str | None = None
    gaap_source: str | None = None

    current_period_raw: str | None = None
    current_period_status: str | None = None
    current_period_resolved: str | None = None
    current_period_source: str | None = None

    hours: list[Any] = Field(default_factory=list)
    activities: list[Any] = Field(default_factory=list)
    communications: dict[str, Any] = Field(default_factory=_empty_communications)
    hours_status: str | None = None
    activities_status: str | None = None
    communications_status: str | None = None

    bs_entry_id: str | None = None
    is_entry_id: str | None = None
    fs_parent_entry_id: str | None = None
    accounts: list[Any] = Field(default_factory=list)
    accounts_status: str | None = None

    icfr_entry_id: str | None = None
    icfr_engagement: str | None = None
    icfr_opinion_raw: str | None = None
    icfr_opinion_code: str | None = None
    icfr_status: str | None = None

    fetch_status: str
    conflicts: list[Any] = Field(default_factory=list)
    extracted_at: datetime
    extractor_version: str
