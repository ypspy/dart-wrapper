"""Admin 감사 추출 요청·응답 스키마."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.catalog import JobLogItem


class ExtractAuditRequest(BaseModel):
    """감사 추출 트리거 요청."""

    start_date: str = Field(pattern=r"^\d{8}$")
    end_date: str = Field(pattern=r"^\d{8}$")
    report_types: list[str] = Field(min_length=1)
    mode: Literal["extract", "resume", "reparse"] = "extract"


class ExtractAuditResponse(BaseModel):
    """추출 트리거 응답. 즉시 반환된다."""

    job_id: str
    status: str = "pending"
    mode: str = "extract"


class ExtractJobStatusResponse(BaseModel):
    """추출 작업 현황과 최근 로그."""

    job_id: str
    status: str
    mode: str = "extract"
    params: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    logs: list[JobLogItem] = Field(default_factory=list)


class CompletenessItem(BaseModel):
    """완전성 목록의 문서 식별자."""

    rcept_no: str
    dcm_no: str


class CompletenessResponse(BaseModel):
    """기간·유형별 감사 추출 완전성 집계."""

    target: int
    ok: int
    fetch_failed: int
    blocked: int
    section_missing: int
    unextracted: int
    ambiguous_dates: int
    field_partial: int
    items: list[CompletenessItem] = Field(default_factory=list)
    next_cursor: str | None = None


class DateOverrideRequest(BaseModel):
    """감사보고서일 수동 보정 요청."""

    iso: str


class DateOverrideResponse(BaseModel):
    """수동 보정 후 날짜 필드."""

    rcept_no: str
    dcm_no: str
    audit_report_date: str | None
    audit_report_date_override: str | None
    audit_report_date_status: str | None
    audit_report_date_source: str | None
