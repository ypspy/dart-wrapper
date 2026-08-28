"""Admin 추출 작업과 진행 로그 테이블."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    """UTC 기준 현재 시각."""
    return datetime.now(timezone.utc)


class ExtractionJob(Base):
    """추출·날짜 해소 작업 단위. 상태와 파라미터를 보관한다."""

    __tablename__ = "extraction_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # audit_opinion: 표지·의견 추출, resolve_dates: ambiguous 날짜 LLM 해소
    extractor_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # extract: 신규, resume: 미추출·실패분 재개, reparse: not_found 필드 재fetch
    mode: Mapped[str] = mapped_column(String(16), default="extract", nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExtractionJobLog(Base):
    """추출 작업 진행 로그 한 줄."""

    __tablename__ = "extraction_job_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("extraction_jobs.job_id"), index=True, nullable=False
    )
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
