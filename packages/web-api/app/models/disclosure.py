"""공시(접수) 단위 집계 테이블. 목록 조회용 메타만 저장한다."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Disclosure(Base):
    """접수번호 1건의 공시 메타와 leaf 개수."""

    __tablename__ = "disclosures"
    __table_args__ = (
        Index("ix_disclosures_rcept_dt_rcept_no", "rcept_dt", "rcept_no"),
        Index("ix_disclosures_corp_code", "corp_code"),
        Index("ix_disclosures_report_type", "report_type"),
    )

    rcept_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    corp_code: Mapped[str | None] = mapped_column(String(16))
    corp_name: Mapped[str | None] = mapped_column(String(255))
    report_nm: Mapped[str | None] = mapped_column(String(255))
    report_type: Mapped[str | None] = mapped_column(String(16))
    correction_type: Mapped[str | None] = mapped_column(String(32))
    submitter: Mapped[str | None] = mapped_column(String(255))
    rcept_dt: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    bsns_year: Mapped[str | None] = mapped_column(String(8))
    year_end: Mapped[str | None] = mapped_column(String(32))
    disclosure_url: Mapped[str | None] = mapped_column(String(1024))
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
