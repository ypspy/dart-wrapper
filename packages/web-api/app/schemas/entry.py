"""entry-extractor 출력과 DB 사이를 잇는 엔트리 스키마."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EntryRecord(BaseModel):
    """Node entry-extractor가 만든 flat leaf 엔트리 1건.

    Node 쪽 camelCase 필드(reportType, dcmNo)는 alias로 받는다.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    entry_id: str
    rcept_no: str
    report_type: str | None = Field(default=None, alias="reportType")
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
    dcm_no: str | None = Field(default=None, alias="dcmNo")
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
