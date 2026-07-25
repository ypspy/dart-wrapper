"""엔트리 수집 포트. 구현체(Node 브릿지 등)를 교체할 수 있게 한다."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.entry import EntryRecord


class CollectRequest(BaseModel):
    """수집 범위 요청. 날짜는 YYYYMMDD 형식이다."""

    report_type: str
    start_date: str = Field(pattern=r"^\d{8}$")
    end_date: str = Field(pattern=r"^\d{8}$")
    corp_code: str | None = None
    max_total: int | None = Field(default=None, ge=1)
    include_attachments: bool = True


class DisclosureListItem(BaseModel):
    """상세검색 목록 1건. Node가 만든 원본 필드를 그대로 보존한다."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    rcept_no: str
    report_type: str | None = Field(default=None, alias="reportType")
    corp_code: str | None = None
    corp_name: str | None = None
    report_nm: str | None = None
    rcept_dt: str | None = None
    url: str

    def to_node_payload(self) -> dict[str, Any]:
        """Node extract 모드에 넘길 공시 원본 딕셔너리를 만든다."""
        return self.model_dump(by_alias=True, exclude_none=True)


class DisclosureListResult(BaseModel):
    """하루치 목록 조회 결과. `listed_count`는 원천이 알려준 총건수다."""

    listed_count: int
    items: list[DisclosureListItem] = Field(default_factory=list)


class EntryCollector(Protocol):
    """공시 목록·상세를 훑어 flat leaf 엔트리를 만드는 수집기."""

    async def collect(self, request: CollectRequest) -> list[EntryRecord]:
        """요청 범위의 엔트리를 한 번에 수집한다(예제·수동 실행용)."""
        ...

    async def list_disclosures(self, request: CollectRequest) -> DisclosureListResult:
        """기간(보통 하루)의 공시 목록과 원천 총건수를 반환한다."""
        ...

    async def extract_disclosure(
        self,
        disclosure: DisclosureListItem,
        *,
        include_attachments: bool = True,
    ) -> list[EntryRecord]:
        """공시 1건의 leaf 엔트리를 반환한다."""
        ...
