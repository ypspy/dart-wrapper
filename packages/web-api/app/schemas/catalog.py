"""Admin 카탈로그 수집 요청·응답 스키마."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ports.entry_collector import CollectRequest


class ExtractRequest(CollectRequest):
    """수집 트리거 요청. 수집 포트 요청과 동일한 범위를 받는다."""


class ResumeRequest(BaseModel):
    """미완료·실패분 재개 요청. 범위를 좁히려면 슬라이스나 유형을 지정한다."""

    slice_id: str | None = None
    report_type: str | None = None
    include_attachments: bool = True


class ExtractResponse(BaseModel):
    """수집 트리거 응답. 즉시 반환된다."""

    job_id: str
    status: str
    mode: str = "collect"


class JobLogItem(BaseModel):
    """수집 진행 로그 한 줄."""

    model_config = ConfigDict(from_attributes=True)

    level: str
    message: str
    created_at: datetime


class SliceSummary(BaseModel):
    """날짜 슬라이스 하나의 진행·완전성 요약."""

    model_config = ConfigDict(from_attributes=True)

    slice_id: str
    report_type: str
    slice_date: str
    status: str
    listed_count: int | None = None
    attempted: int = 0
    succeeded: int = 0
    failed_count: int = 0
    attempt: int = 0
    last_job_id: str | None = None
    updated_at: datetime | None = None

    @property
    def is_complete(self) -> bool:
        """완전성 조건을 만족한 슬라이스인지 여부."""
        return self.status == "complete"


class SliceListResponse(BaseModel):
    """슬라이스 목록 응답."""

    items: list[SliceSummary] = Field(default_factory=list)


class DisclosureAttemptItem(BaseModel):
    """공시 1건의 마지막 처리 결과."""

    model_config = ConfigDict(from_attributes=True)

    rcept_no: str
    status: str
    entry_count: int = 0
    attempt: int = 0
    last_error: str | None = None
    updated_at: datetime | None = None


class HeatmapCell(BaseModel):
    """보고서 유형·날짜 한 칸의 완전성."""

    slice_date: str
    level: Literal["complete", "incomplete", "missing", "future"]
    slice_id: str | None = None
    status: str | None = None
    succeeded: int = 0
    listed_count: int | None = None


class HeatmapMonthLabel(BaseModel):
    """월 이름을 표시할 주 인덱스."""

    week_index: int
    label: str


class HeatmapRow(BaseModel):
    """보고서 유형 하나의 53주 격자."""

    report_type: str
    weeks: list[list[HeatmapCell]]


class HeatmapResponse(BaseModel):
    """연간 완전성 히트맵 응답."""

    start_date: str
    end_date: str
    month_labels: list[HeatmapMonthLabel] = Field(default_factory=list)
    rows: list[HeatmapRow] = Field(default_factory=list)


class YearSummaryItem(BaseModel):
    """연도 하나의 완전성 요약."""

    year: int
    level: Literal["complete", "incomplete", "missing"]


class YearSummaryResponse(BaseModel):
    """연도 요약 바와 기본 선택 연도."""

    items: list[YearSummaryItem] = Field(default_factory=list)
    selected_year: int


class SliceDetailResponse(BaseModel):
    """슬라이스 상세: 요약과 공시별 처리 결과."""

    slice: SliceSummary
    attempts: list[DisclosureAttemptItem] = Field(default_factory=list)


class JobStatusResponse(BaseModel):
    """수집 작업 현황과 최근 로그."""

    job_id: str
    status: str
    mode: str = "collect"
    params: dict[str, Any] = Field(default_factory=dict)
    total_entries: int = 0
    saved_entries: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    logs: list[JobLogItem] = Field(default_factory=list)
