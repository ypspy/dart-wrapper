"""Public 감사 추출 결과 목록 조회."""

from __future__ import annotations

import base64
import json

from app.errors import BadRequest
from app.repositories.fact_repository import FactRepository
from app.schemas.facts import FactListResponse, fact_list_item_from


def encode_fact_cursor(rcept_dt: str, rcept_no: str, dcm_no: str) -> str:
    """목록 페이지의 opaque cursor를 만든다."""
    payload = json.dumps(
        {"rcept_dt": rcept_dt, "rcept_no": rcept_no, "dcm_no": dcm_no},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_fact_cursor(cursor: str) -> tuple[str, str, str]:
    """opaque cursor를 (rcept_dt, rcept_no, dcm_no)로 복원한다.

    :raises BadRequest: 손상되었거나 필드가 없는 경우
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        return data["rcept_dt"], data["rcept_no"], data["dcm_no"]
    except Exception as exc:
        raise BadRequest(
            "커서 값이 올바르지 않습니다. 이전 응답의 next_cursor를 그대로 전달해 주세요."
        ) from exc


class FactQueryService:
    """추출 결과 목록 조회."""

    def __init__(self, facts: FactRepository) -> None:
        self._facts = facts

    async def list_page(
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
    ) -> FactListResponse:
        """필터와 keyset cursor로 추출 목록을 반환한다."""
        cursor_dt = cursor_no = cursor_dcm = None
        if cursor:
            cursor_dt, cursor_no, cursor_dcm = decode_fact_cursor(cursor)
        rows = await self._facts.list_page(
            corp_code=corp_code,
            corp_name=corp_name,
            report_nm=report_nm,
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit + 1,
            cursor_rcept_dt=cursor_dt,
            cursor_rcept_no=cursor_no,
            cursor_dcm_no=cursor_dcm,
        )
        next_cursor: str | None = None
        if len(rows) > limit:
            last_fact, last_disc = rows[limit - 1]
            next_cursor = encode_fact_cursor(
                last_disc.rcept_dt, last_fact.rcept_no, last_fact.dcm_no
            )
            rows = rows[:limit]
        return FactListResponse(
            items=[fact_list_item_from(fact, disc) for fact, disc in rows],
            next_cursor=next_cursor,
        )
