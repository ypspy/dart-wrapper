"""수집 재개용 체크포인트 테이블.

상위 체크포인트는 `report_type × 날짜` 슬라이스이고, 하위 체크포인트는 공시(접수번호)다.
DART 목록은 시간이 지나면 페이지 구성이 바뀌므로 페이지 번호는 재개 기준으로 쓰지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    """UTC 기준 현재 시각."""
    return datetime.now(timezone.utc)


class SliceProgress(Base):
    """하루치 수집 진행 상황. 완전성 판정의 기준이 된다."""

    __tablename__ = "slice_progress"
    __table_args__ = (
        UniqueConstraint("report_type", "slice_date", name="uq_slice_progress_type_date"),
        Index("ix_slice_progress_slice_date", "slice_date"),
        Index("ix_slice_progress_status", "status"),
    )

    slice_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_type: Mapped[str] = mapped_column(String(16), nullable=False)
    slice_date: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # 원천 목록의 총건수. 목록 수집에 실패하면 확정할 수 없어 NULL로 남는다.
    listed_count: Mapped[int | None] = mapped_column(Integer)
    attempted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_job_id: Mapped[str | None] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class DisclosureAttempt(Base):
    """공시 1건의 처리 결과. 이미 성공한 공시는 다시 파싱하지 않는다."""

    __tablename__ = "disclosure_attempts"
    __table_args__ = (Index("ix_disclosure_attempts_slice_status", "slice_id", "status"),)

    rcept_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    slice_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("slice_progress.slice_id"), nullable=False
    )
    report_type: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    entry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
