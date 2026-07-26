"""Viewer 응답 스키마. 원문 정제 결과를 담는다."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class TableData(BaseModel):
    """표 하나를 헤더와 행으로 표현한다."""

    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class HeadingBlock(BaseModel):
    """제목 블록."""

    type: Literal["heading"] = "heading"
    level: int = Field(ge=1, le=3)
    text: str


class ParagraphBlock(BaseModel):
    """문단 블록."""

    type: Literal["paragraph"] = "paragraph"
    text: str


class TableBlock(BaseModel):
    """표 블록. TableData와 동일 구조에 type 구분자만 붙인다."""

    type: Literal["table"] = "table"
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


# 문서 순서 블록. type 값으로 구분한다.
ContentBlock = Annotated[
    HeadingBlock | ParagraphBlock | TableBlock,
    Field(discriminator="type"),
]


class SectionContent(BaseModel):
    """leaf 섹션 1건의 정제 결과."""

    entry_id: str
    source: str
    dcm_no: str | None = None
    ele_id: str | None = None
    path: list[str] = Field(default_factory=list)
    document_name: str | None = None
    section_name: str | None = None
    blocks: list[ContentBlock] = Field(default_factory=list)
    text: str | None = None
    tables: list[TableData] = Field(default_factory=list)
    error: str | None = None


class DisclosureMeta(BaseModel):
    """공시 단위 메타데이터."""

    corp_name: str | None = None
    corp_code: str | None = None
    report_nm: str | None = None
    rcept_dt: str | None = None


class DisclosureContent(BaseModel):
    """접수번호 하나에 속한 모든 leaf 섹션의 정제 결과."""

    rcp_no: str
    meta: DisclosureMeta
    sections: list[SectionContent] = Field(default_factory=list)
