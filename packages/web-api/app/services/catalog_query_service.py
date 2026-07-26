"""Public 카탈로그 조회 서비스. cursor 목록과 leaf 목차를 담당한다."""

from __future__ import annotations

import base64
import json

from app.errors import BadRequest, CatalogNotFound
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.entry_repository import EntryRepository
from app.schemas.catalog_query import (
    DisclosureEntriesResponse,
    DisclosureListResponse,
    DisclosureSummary,
    EntrySummary,
)


def encode_cursor(rcept_dt: str, rcept_no: str) -> str:
    """목록 페이지의 opaque cursor를 만든다."""
    payload = json.dumps(
        {"rcept_dt": rcept_dt, "rcept_no": rcept_no},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    """opaque cursor를 (rcept_dt, rcept_no)로 복원한다.

    :raises BadRequest: 손상되었거나 필드가 없는 경우
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        return data["rcept_dt"], data["rcept_no"]
    except Exception as exc:
        raise BadRequest(
            "커서 값이 올바르지 않습니다. 이전 응답의 next_cursor를 그대로 전달해 주세요."
        ) from exc


class CatalogQueryService:
    """공시 목록·단건·leaf 목차 조회."""

    def __init__(
        self,
        disclosures: DisclosureRepository,
        entries: EntryRepository,
    ) -> None:
        self._disclosures = disclosures
        self._entries = entries

    async def list_disclosures(
        self,
        *,
        corp_code: str | None = None,
        corp_name: str | None = None,
        report_nm: str | None = None,
        report_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> DisclosureListResponse:
        """필터와 keyset cursor로 공시 목록을 반환한다."""
        cursor_dt: str | None = None
        cursor_no: str | None = None
        if cursor:
            cursor_dt, cursor_no = decode_cursor(cursor)

        rows = await self._disclosures.list_page(
            corp_code=corp_code,
            corp_name=corp_name,
            report_nm=report_nm,
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit + 1,
            cursor_rcept_dt=cursor_dt,
            cursor_rcept_no=cursor_no,
        )
        next_cursor: str | None = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = encode_cursor(last.rcept_dt, last.rcept_no)
            rows = rows[:limit]

        return DisclosureListResponse(
            items=[DisclosureSummary.from_model(row) for row in rows],
            next_cursor=next_cursor,
        )

    async def get_disclosure(self, rcp_no: str) -> DisclosureSummary:
        """공시 1건 요약을 반환한다.

        :raises CatalogNotFound: 카탈로그에 없을 때
        """
        row = await self._disclosures.get(rcp_no)
        if row is None:
            raise CatalogNotFound(f"공시를 찾을 수 없습니다: {rcp_no}")
        return DisclosureSummary.from_model(row)

    async def list_entries(self, rcp_no: str) -> DisclosureEntriesResponse:
        """공시의 leaf 목차를 ordinal 순으로 반환한다.

        :raises CatalogNotFound: 공시가 없을 때
        """
        disclosure = await self._disclosures.get(rcp_no)
        if disclosure is None:
            raise CatalogNotFound(f"공시를 찾을 수 없습니다: {rcp_no}")

        entries = await self._entries.list_toc_by_rcept_no(rcp_no)
        all_entries = [EntrySummary.from_model(entry) for entry in entries]
        return DisclosureEntriesResponse(
            disclosure=DisclosureSummary.from_model(disclosure),
            all_entries=all_entries,
        )
