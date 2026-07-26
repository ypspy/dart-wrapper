"""Public 카탈로그 목록·목차 응답 스키마."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.disclosure import Disclosure
from app.models.entry import Entry


class DisclosureSummary(BaseModel):
    """공시(접수) 1건 요약. 응답 필드는 rcp_no, DB는 rcept_no."""

    rcp_no: str
    corp_code: str | None = None
    corp_name: str | None = None
    report_nm: str | None = None
    report_type: str | None = None
    correction_type: str | None = None
    submitter: str | None = None
    rcept_dt: str | None = None
    year_end: str | None = None
    bsns_year: str | None = None
    entry_count: int = 0
    disclosure_url: str | None = None

    @classmethod
    def from_model(cls, row: Disclosure) -> DisclosureSummary:
        """ORM 행을 API 요약으로 변환한다."""
        return cls(
            rcp_no=row.rcept_no,
            corp_code=row.corp_code,
            corp_name=row.corp_name,
            report_nm=row.report_nm,
            report_type=row.report_type,
            correction_type=row.correction_type,
            submitter=row.submitter,
            rcept_dt=row.rcept_dt,
            year_end=row.year_end,
            bsns_year=row.bsns_year,
            entry_count=row.entry_count,
            disclosure_url=row.disclosure_url,
        )


class DisclosureListResponse(BaseModel):
    """공시 목록과 다음 페이지 cursor."""

    items: list[DisclosureSummary] = Field(default_factory=list)
    next_cursor: str | None = None


class EntrySummary(BaseModel):
    """leaf 엔트리 전 필드. entry-extractor 산출과 동일한 feature 집합이다."""

    entry_id: str
    rcept_no: str
    report_type: str | None = None
    correction_type: str | None = None
    report_nm: str | None = None
    year_end: str | None = None
    corp_code: str | None = None
    corp_name: str | None = None
    submitter: str | None = None
    rcept_dt: str | None = None
    bsns_year: str | None = None
    disclosure_url: str | None = None
    source: str
    dcm_no: str | None = None
    document_name: str | None = None
    section_name: str | None = None
    section_original_name: str | None = None
    depth: int | None = None
    ordinal: int | None = None
    is_leaf: bool = True
    parent_ele_id: str | None = None
    ele_id: str | None = None
    offset: str | None = None
    length: str | None = None
    dtd: str | None = None
    path: list[str] = Field(default_factory=list)
    viewer_url: str | None = None

    @classmethod
    def from_model(cls, row: Entry) -> EntrySummary:
        """ORM 엔트리를 Catalog leaf 응답으로 변환한다."""
        return cls(
            entry_id=row.entry_id,
            rcept_no=row.rcept_no,
            report_type=row.report_type,
            correction_type=row.correction_type,
            report_nm=row.report_nm,
            year_end=row.year_end,
            corp_code=row.corp_code,
            corp_name=row.corp_name,
            submitter=row.submitter,
            rcept_dt=row.rcept_dt,
            bsns_year=row.bsns_year,
            disclosure_url=row.disclosure_url,
            source=row.source,
            dcm_no=row.dcm_no,
            document_name=row.document_name,
            section_name=row.section_name,
            section_original_name=row.section_original_name,
            depth=row.depth,
            ordinal=row.ordinal,
            is_leaf=bool(row.is_leaf),
            parent_ele_id=row.parent_ele_id,
            ele_id=row.ele_id,
            offset=row.offset,
            length=row.length,
            dtd=row.dtd,
            path=list(row.path or []),
            viewer_url=row.viewer_url,
        )


class DisclosureEntriesResponse(BaseModel):
    """공시 1건의 메타 + leaf 목록 (전 feature)."""

    disclosure: DisclosureSummary
    all_entries: list[EntrySummary] = Field(default_factory=list)
