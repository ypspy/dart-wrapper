"""Admin 카탈로그 수집 요청·응답 스키마."""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
