"""추출 진단 검토 행. 측정 facts와 분리한다."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExtractionReview(Base):
    """문서×묶음×신호×대상 하나의 판정."""

    __tablename__ = "extraction_reviews"

    rcept_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    dcm_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    bundle: Mapped[str] = mapped_column(String(32), primary_key=True)
    signal: Mapped[str] = mapped_column(String(32), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True, default="")
    extractor_version: Mapped[str] = mapped_column(String(32), nullable=False)
    in_research_panel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stratum: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    tail: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    queue_order: Mapped[int | None] = mapped_column(Integer)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False, default="hold")
    tag: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
