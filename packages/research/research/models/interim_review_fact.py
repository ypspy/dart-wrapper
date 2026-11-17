"""반기·분기 검토보고서 문서 단위 추출 결과.

기동 스키마(`ensure_schema`)와 연구 열 보강 목록에는 넣지 않는다.
테이블은 `scripts/create_interim_review_table.py`로만 만든다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from research.extracting.interim_review import INTERIM_EXTRACTOR_VERSION


def _now() -> datetime:
    """UTC 기준 현재 시각."""
    return datetime.now(timezone.utc)


class InterimReviewFact(Base):
    """검토보고서 문서 하나(`rcept_no` + `dcm_no`)의 추출 결과."""

    __tablename__ = "interim_review_facts"
    __table_args__ = (
        Index("ix_interim_review_facts_source_report_type", "source_report_type"),
        Index("ix_interim_review_facts_extracted_at", "extracted_at"),
    )

    rcept_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    dcm_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_report_type: Mapped[str] = mapped_column(String(16), nullable=False)
    review_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    fs_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    doc_kind: Mapped[str] = mapped_column(String(32), nullable=False)

    cover_entry_id: Mapped[str | None] = mapped_column(String(128))
    report_entry_id: Mapped[str | None] = mapped_column(String(128))
    fs_parent_entry_id: Mapped[str | None] = mapped_column(String(128))
    notes_entry_id: Mapped[str | None] = mapped_column(String(128))

    reviewer_raw: Mapped[str | None] = mapped_column(Text)
    reviewer_resolved: Mapped[str | None] = mapped_column(String(255))
    reviewer_status: Mapped[str | None] = mapped_column(String(32))

    conclusion_raw: Mapped[str | None] = mapped_column(Text)
    conclusion_code: Mapped[str | None] = mapped_column(String(32))
    conclusion_status: Mapped[str | None] = mapped_column(String(32))

    review_report_date_raw: Mapped[str | None] = mapped_column(Text)
    review_report_date: Mapped[str | None] = mapped_column(String(16))
    review_report_date_status: Mapped[str | None] = mapped_column(String(32))
    review_report_date_candidates: Mapped[list[Any]] = mapped_column(
        JSON, default=list, nullable=False
    )

    review_period_raw: Mapped[str | None] = mapped_column(Text)
    review_period_resolved: Mapped[str | None] = mapped_column(String(64))
    review_period_status: Mapped[str | None] = mapped_column(String(32))

    gaap_code: Mapped[str | None] = mapped_column(String(32))
    gaap_status: Mapped[str | None] = mapped_column(String(32))

    emphasis_of_matter: Mapped[bool] = mapped_column(default=False, nullable=False)
    going_concern: Mapped[bool] = mapped_column(default=False, nullable=False)
    emphasis_raw: Mapped[str | None] = mapped_column(Text)
    emphasis_status: Mapped[str | None] = mapped_column(String(32))

    fetch_status: Mapped[str] = mapped_column(String(32), nullable=False)
    conflicts: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    extractor_version: Mapped[str] = mapped_column(
        String(32), default=INTERIM_EXTRACTOR_VERSION, nullable=False
    )
