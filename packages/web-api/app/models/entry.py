"""flat leaf 엔트리 카탈로그 테이블. 메타데이터만 저장한다."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    """UTC 기준 현재 시각."""
    return datetime.now(timezone.utc)


class Entry(Base):
    """공시 컨테이너 내 leaf 문서·섹션 단위 엔트리."""

    __tablename__ = "entries"
    __table_args__ = (Index("ix_entries_rcept_no_entry_id", "rcept_no", "entry_id"),)

    entry_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    rcept_no: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    report_type: Mapped[str | None] = mapped_column(String(16))
    correction_type: Mapped[str | None] = mapped_column(String(32))
    report_nm: Mapped[str | None] = mapped_column(String(255))
    year_end: Mapped[str | None] = mapped_column(String(32))
    corp_code: Mapped[str | None] = mapped_column(String(16), index=True)
    corp_name: Mapped[str | None] = mapped_column(String(255))
    submitter: Mapped[str | None] = mapped_column(String(255))
    rcept_dt: Mapped[str | None] = mapped_column(String(16))
    bsns_year: Mapped[str | None] = mapped_column(String(8))
    disclosure_url: Mapped[str | None] = mapped_column(String(1024))
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    dcm_no: Mapped[str | None] = mapped_column(String(32))
    document_name: Mapped[str | None] = mapped_column(String(255))
    section_name: Mapped[str | None] = mapped_column(String(255))
    section_original_name: Mapped[str | None] = mapped_column(String(255))
    depth: Mapped[int | None] = mapped_column(Integer)
    ordinal: Mapped[int | None] = mapped_column(Integer)
    is_leaf: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    parent_ele_id: Mapped[str | None] = mapped_column(String(32))
    ele_id: Mapped[str | None] = mapped_column(String(32))
    offset: Mapped[str | None] = mapped_column(String(32))
    length: Mapped[str | None] = mapped_column(String(32))
    dtd: Mapped[str | None] = mapped_column(String(64))
    path: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    viewer_url: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
