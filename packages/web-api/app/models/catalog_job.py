"""Admin 카탈로그 수집 작업과 진행 로그 테이블."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    """UTC 기준 현재 시각."""
    return datetime.now(timezone.utc)


class CatalogJob(Base):
    """수집 작업 단위. 상태와 진행 수치를 보관한다."""

    __tablename__ = "catalog_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # collect: 신규 수집, resume: 미완료·실패분 재개, rescan: 최근 기간 겹침 수집
    mode: Mapped[str] = mapped_column(String(16), default="collect", nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    params_key: Mapped[str] = mapped_column(String(512), index=True, nullable=False)
    total_entries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    saved_entries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CatalogJobLog(Base):
    """수집 작업 진행 로그 한 줄."""

    __tablename__ = "catalog_job_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("catalog_jobs.job_id"), index=True, nullable=False
    )
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
