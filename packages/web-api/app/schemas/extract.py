"""Admin 감사 추출 요청·응답 스키마."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

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
    stale_version: int = 0
    ambiguous_dates: int
    field_partial: int
    items: list[CompletenessItem] = Field(default_factory=list)
    next_cursor: str | None = None


class ResolveDatesResponse(BaseModel):
    """날짜 LLM 해소 트리거 응답. 즉시 반환된다."""

    job_id: str
    status: str = "pending"


class DateOverrideRequest(BaseModel):
    """감사보고서일 수동 보정 요청."""

    iso: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("iso")
    @classmethod
    def iso_must_be_calendar_date(cls, value: str) -> str:
        """패턴을 통과한 뒤에도 실제 달력 날짜인지 확인한다."""
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("iso는 YYYY-MM-DD 달력 날짜여야 합니다.") from exc
        return value


class DateOverrideResponse(BaseModel):
    """수동 보정 후 날짜 필드."""

    rcept_no: str
    dcm_no: str
    audit_report_date: str | None
    audit_report_date_override: str | None
    audit_report_date_status: str | None
    audit_report_date_source: str | None


class FieldBundleRow(BaseModel):
    """창 표 한 줄."""

    bundle: str
    label: str
    ok: int
    not_applicable: int
    expected_missing: int
    fail: int


class FieldBundleCountsResponse(BaseModel):
    """기간 안 현재 추출기 facts의 12묶음 집계."""

    start_date: str
    end_date: str
    extractor_version: str
    eligible: int
    bundles: list[FieldBundleRow]


class FieldBundleFailItem(BaseModel):
    """실패 목록·TSV 한 행."""

    report_type: str
    rcept_no: str
    dcm_no: str
    fs_scope: str
    bundle: str
    status: str | None
    extractor_version: str | None
    viewer_url: str | None


class FieldBundleFailListResponse(BaseModel):
    """실패 목록 한 페이지."""

    items: list[FieldBundleFailItem]
    next_cursor: str | None = None
