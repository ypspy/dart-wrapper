"""엔트리 수집 포트. 구현체(Node 브릿지 등)를 교체할 수 있게 한다."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from app.schemas.entry import EntryRecord


class CollectRequest(BaseModel):
    """수집 범위 요청. 날짜는 YYYYMMDD 형식이다."""

    report_type: str
    start_date: str = Field(pattern=r"^\d{8}$")
    end_date: str = Field(pattern=r"^\d{8}$")
    corp_code: str | None = None
    max_total: int | None = Field(default=None, ge=1)
    include_attachments: bool = True


class EntryCollector(Protocol):
    """공시 목록·상세를 훑어 flat leaf 엔트리를 만드는 수집기."""

    async def collect(self, request: CollectRequest) -> list[EntryRecord]:
        """요청 범위의 엔트리를 모두 수집해 반환한다."""
        ...
