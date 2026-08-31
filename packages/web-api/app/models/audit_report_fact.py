"""감사보고서 문서 단위 추출 결과 테이블."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extracting.constants import EXTRACTOR_VERSION
from app.models.base import Base


def _now() -> datetime:
    """UTC 기준 현재 시각."""
    return datetime.now(timezone.utc)


def _empty_communications() -> dict[str, Any]:
    """커뮤니케이션 JSON 기본값. 공유 가변 dict를 쓰지 않는다."""
    return {"has_audit_committee": False, "items": []}


class AuditReportFact(Base):
    """감사보고서 문서 하나(`rcept_no` + `dcm_no`)의 추출·해소 결과."""

    __tablename__ = "audit_report_facts"

    rcept_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    dcm_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_report_type: Mapped[str] = mapped_column(String(16), nullable=False)
    fs_scope: Mapped[str] = mapped_column(String(16), nullable=False)

    cover_entry_id: Mapped[str | None] = mapped_column(String(128))
    opinion_entry_id: Mapped[str | None] = mapped_column(String(128))
    activity_entry_id: Mapped[str | None] = mapped_column(String(128))
    a001_opinion_entry_id: Mapped[str | None] = mapped_column(String(128))
    a001_cover_entry_id: Mapped[str | None] = mapped_column(String(128))

    auditor: Mapped[str | None] = mapped_column(String(255))
    auditor_body: Mapped[str | None] = mapped_column(String(255))
    auditor_a001: Mapped[str | None] = mapped_column(String(255))
    auditor_listing: Mapped[str | None] = mapped_column(String(255))
    auditor_status: Mapped[str | None] = mapped_column(String(32))
    auditor_resolved: Mapped[str | None] = mapped_column(String(255))
    auditor_source: Mapped[str | None] = mapped_column(String(32))

    opinion_raw: Mapped[str | None] = mapped_column(Text)
    opinion_code: Mapped[str | None] = mapped_column(String(32))
    opinion_status: Mapped[str | None] = mapped_column(String(32))
    opinion_resolved: Mapped[str | None] = mapped_column(String(32))
    opinion_source: Mapped[str | None] = mapped_column(String(32))

    audit_report_date_raw: Mapped[str | None] = mapped_column(Text)
    audit_report_date_candidates: Mapped[list[Any]] = mapped_column(
        JSON, default=list, nullable=False
    )
    audit_report_date: Mapped[str | None] = mapped_column(String(16))
    audit_report_date_status: Mapped[str | None] = mapped_column(String(32))
    audit_report_date_source: Mapped[str | None] = mapped_column(String(32))
    audit_report_date_override: Mapped[str | None] = mapped_column(String(16))

    gaap_raw: Mapped[str | None] = mapped_column(Text)
    gaap_code: Mapped[str | None] = mapped_column(String(32))
    gaap_status: Mapped[str | None] = mapped_column(String(32))
    gaap_resolved: Mapped[str | None] = mapped_column(String(32))
    gaap_source: Mapped[str | None] = mapped_column(String(32))

    current_period_raw: Mapped[str | None] = mapped_column(Text)
    current_period_status: Mapped[str | None] = mapped_column(String(32))
    current_period_resolved: Mapped[str | None] = mapped_column(String(255))
    current_period_source: Mapped[str | None] = mapped_column(String(32))

    hours: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    activities: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    communications: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=_empty_communications, nullable=False
    )
    hours_status: Mapped[str | None] = mapped_column(String(32))
    activities_status: Mapped[str | None] = mapped_column(String(32))
    communications_status: Mapped[str | None] = mapped_column(String(32))

    fetch_status: Mapped[str] = mapped_column(String(32), nullable=False)
    conflicts: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    extractor_version: Mapped[str] = mapped_column(
        String(32), default=EXTRACTOR_VERSION, nullable=False
    )

    date_resolver_model: Mapped[str | None] = mapped_column(String(128))
    date_resolver_prompt_version: Mapped[str | None] = mapped_column(String(64))
    date_resolver_raw_response: Mapped[str | None] = mapped_column(Text)
