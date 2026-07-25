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
    rcept_dt: str | None = None
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
            rcept_dt=row.rcept_dt,
            entry_count=row.entry_count,
            disclosure_url=row.disclosure_url,
        )


class DisclosureListResponse(BaseModel):
    """공시 목록과 다음 페이지 cursor."""

    items: list[DisclosureSummary] = Field(default_factory=list)
    next_cursor: str | None = None


class EntrySummary(BaseModel):
    """leaf 목차 항목. Viewer 진입용 entry_id를 포함한다."""

    entry_id: str
    source: str
    dcm_no: str | None = None
    ele_id: str | None = None
    document_name: str | None = None
    section_name: str | None = None
    path: list[str] = Field(default_factory=list)
    depth: int | None = None

    @classmethod
    def from_model(cls, row: Entry) -> EntrySummary:
        """ORM 엔트리를 목차 항목으로 변환한다."""
        return cls(
            entry_id=row.entry_id,
            source=row.source,
            dcm_no=row.dcm_no,
            ele_id=row.ele_id,
            document_name=row.document_name,
            section_name=row.section_name,
            path=list(row.path or []),
            depth=row.depth,
        )


class DisclosureEntriesResponse(BaseModel):
    """공시 1건의 primary/전체 leaf 목차."""

    rcp_no: str
    report_type: str | None = None
    primary_entries: list[EntrySummary] = Field(default_factory=list)
    all_entries: list[EntrySummary] = Field(default_factory=list)
