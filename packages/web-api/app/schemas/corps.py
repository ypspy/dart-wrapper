"""회사 업종 Admin 요청·응답 스키마."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.catalog import JobLogItem


class CorpEnrichResponse(BaseModel):
    """회사 업종 채움 트리거 응답."""

    job_id: str
    status: str = "pending"
    mode: str = "fill_missing"


class CorpSummaryResponse(BaseModel):
    """회사 업종 채움 현황 집계."""

    disclosure_corps: int
    ok_count: int
    remaining_count: int


class CorpJobStatusResponse(BaseModel):
    """회사 업종 작업 현황과 최근 로그."""

    job_id: str
    status: str
    mode: str = "fill_missing"
    params: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stop_requested: bool = False
    logs: list[JobLogItem] = Field(default_factory=list)
