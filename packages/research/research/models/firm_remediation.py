"""회계법인 사업보고서 Ⅵ-2 개선권고 이행 연구 테이블.

카탈로그 웹앱 스키마에는 등록하지 않는다. ``--write`` 대상 DB에서만 만든다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from research.extracting.firm_remediation import PARSER_VERSION


class ExtractionFirmRemediation(Base):
    """개선권고 논리 행. 정정 전 접수도 지우지 않고 남긴다."""

    __tablename__ = "extraction_firm_remediation"

    rcept_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    table_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    row_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    corp_code: Mapped[str] = mapped_column(String(16), nullable=False)
    period_key: Mapped[str | None] = mapped_column(String(16))
    component: Mapped[str] = mapped_column(Text, nullable=False, default="")
    action_date: Mapped[str] = mapped_column(Text, nullable=False, default="")
    finding: Mapped[str] = mapped_column(Text, nullable=False, default="")
    action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_latest: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_cells: Mapped[int] = mapped_column(Integer, nullable=False)
    category_raw: Mapped[str | None] = mapped_column(Text)
    category_inherited: Mapped[int | None] = mapped_column(Integer)
    finding_text: Mapped[str | None] = mapped_column(Text)
    action_text: Mapped[str | None] = mapped_column(Text)
    recommend_date_raw: Mapped[str | None] = mapped_column(Text)
    recommend_date_iso: Mapped[str | None] = mapped_column(Text)
    recommend_date_format: Mapped[str | None] = mapped_column(Text)
    action_date_in_text: Mapped[int | None] = mapped_column(Integer)
    multi_finding_flag: Mapped[int | None] = mapped_column(Integer)
    source_line_raw: Mapped[str | None] = mapped_column(Text)
    vi_status: Mapped[str | None] = mapped_column(Text)
    vi_status_reason: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False, default=PARSER_VERSION)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExtractionFirmRemediationNote(Base):
    """주석과 논리 행으로 만들지 않은 원문."""

    __tablename__ = "extraction_firm_remediation_notes"

    rcept_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    note_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_idx: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False, default=PARSER_VERSION)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExtractionFirmRemediationDocument(Base):
    """접수 단위 처리 상태. 빈 문서와 소제목 없음도 한 행으로 남긴다."""

    __tablename__ = "extraction_firm_remediation_documents"

    rcept_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    corp_code: Mapped[str] = mapped_column(String(16), nullable=False)
    period_key: Mapped[str | None] = mapped_column(String(16))
    rcept_dt: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    n_tables: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_logical_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_notes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subsection: Mapped[str | None] = mapped_column(Text)
    corp_name: Mapped[str | None] = mapped_column(Text)
    body_hash: Mapped[str | None] = mapped_column(Text)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_year_src: Mapped[str | None] = mapped_column(Text)
    inspection_year_note: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False, default=PARSER_VERSION)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExtractionFirmMatchReview(Base):
    """사람이 확인할 동명·미등재 법인. 자동으로 합치지 않는다."""

    __tablename__ = "extraction_firm_match_review"

    reason: Mapped[str] = mapped_column(String(64), primary_key=True)
    corp_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    other_corp_code: Mapped[str] = mapped_column(String(16), primary_key=True, default="")
    corp_name: Mapped[str | None] = mapped_column(String(255))
    other_corp_name: Mapped[str | None] = mapped_column(String(255))
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False, default=PARSER_VERSION)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
