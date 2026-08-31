"""감사 추출 완전성 집계와 감사보고서일 수동 보정."""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import BadRequest, CatalogNotFound
from app.extracting.selector import is_audit_document
from app.models.audit_report_fact import AuditReportFact
from app.models.entry import Entry
from app.repositories.entry_repository import EntryRepository
from app.repositories.fact_repository import FactRepository
from app.schemas.extract import CompletenessItem, CompletenessResponse, DateOverrideResponse

_ALLOWED_REPORT_TYPES = frozenset({"A001", "F001", "F002"})
LIST_STATUSES = (
    "unextracted",
    "fetch_failed",
    "blocked",
    "section_missing",
    "ambiguous_dates",
    "field_partial",
)
_FIELD_STATUS_ATTRS = (
    "auditor_status",
    "opinion_status",
    "gaap_status",
    "audit_report_date_status",
    "current_period_status",
    "hours_status",
    "activities_status",
    "communications_status",
)
DocKey = tuple[str, str]


def encode_cursor(rcept_no: str, dcm_no: str) -> str:
    """문서 식별자 목록의 opaque cursor를 만든다."""
    payload = json.dumps(
        {"rcept_no": rcept_no, "dcm_no": dcm_no},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> DocKey:
    """opaque cursor를 (rcept_no, dcm_no)로 복원한다.

    :raises BadRequest: 손상되었거나 필드가 없는 경우
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        return data["rcept_no"], data["dcm_no"]
    except Exception as exc:
        raise BadRequest(
            "커서 값이 올바르지 않습니다. 이전 응답의 next_cursor를 그대로 전달해 주세요."
        ) from exc


def _is_field_partial(fact: AuditReportFact) -> bool:
    """fetch는 성공했지만 핵심 필드 중 하나라도 ok가 아닌지 본다.

    skipped·not_found·ambiguous·None은 모두 부분실패로 센다.
    """
    if fact.fetch_status != "ok":
        return False
    return any(getattr(fact, name) != "ok" for name in _FIELD_STATUS_ATTRS)


def _document_keys(entries: Sequence[Entry]) -> list[DocKey]:
    """selector 대상 문서를 (rcept_no, dcm_no) 중복 없이 모은다."""
    seen: dict[DocKey, None] = {}
    for entry in entries:
        if not entry.dcm_no:
            continue
        if not is_audit_document(entry.report_type, entry.source, entry.document_name):
            continue
        seen.setdefault((entry.rcept_no, entry.dcm_no), None)
    return list(seen.keys())


def _page(
    keys: Sequence[DocKey],
    cursor: str | None,
    limit: int,
) -> tuple[list[DocKey], str | None]:
    """keyset cursor로 한 페이지를 잘라 next_cursor를 붙인다."""
    start = 0
    if cursor:
        cursor_key = decode_cursor(cursor)
        start = next(
            (index for index, key in enumerate(keys) if key > cursor_key),
            len(keys),
        )
    page = list(keys[start : start + limit])
    next_cursor = None
    if start + limit < len(keys) and page:
        last_rcept, last_dcm = page[-1]
        next_cursor = encode_cursor(last_rcept, last_dcm)
    return page, next_cursor


class CompletenessService:
    """기간·유형별 추출 완전성을 집계하고 날짜 override를 저장한다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summarize(
        self,
        *,
        start_date: str,
        end_date: str,
        report_type: str,
        status: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> CompletenessResponse:
        """selector 대상 문서 기준으로 상태 건수와 선택적 목록을 반환한다."""
        if report_type not in _ALLOWED_REPORT_TYPES:
            raise BadRequest("report_type은 A001, F001, F002 중 하나여야 합니다.")
        if status is not None and status not in LIST_STATUSES:
            raise BadRequest(
                "status는 unextracted, fetch_failed, blocked, section_missing, "
                "ambiguous_dates, field_partial 중 하나여야 합니다."
            )

        repo = EntryRepository(self._session)
        rcept_nos = await repo.list_rcept_nos_for_extraction(start_date, end_date, [report_type])
        keys: list[DocKey] = []
        for rcept_no in rcept_nos:
            filing = await repo.list_by_rcept_no(rcept_no)
            keys.extend(_document_keys(filing))
        key_set = set(keys)
        facts_by_key: dict[DocKey, AuditReportFact] = {}
        for fact in await FactRepository(self._session).list_by_rcept_nos(
            [rcept for rcept, _ in keys]
        ):
            pair = (fact.rcept_no, fact.dcm_no)
            if pair in key_set:
                facts_by_key[pair] = fact

        buckets: dict[str, list[DocKey]] = {name: [] for name in LIST_STATUSES}
        ok = fetch_failed = blocked = section_missing = 0
        for key in keys:
            fact = facts_by_key.get(key)
            if fact is None:
                buckets["unextracted"].append(key)
                continue
            if fact.fetch_status == "ok":
                ok += 1
                if _is_field_partial(fact):
                    buckets["field_partial"].append(key)
            elif fact.fetch_status == "fetch_failed":
                fetch_failed += 1
                buckets["fetch_failed"].append(key)
            elif fact.fetch_status == "blocked":
                blocked += 1
                buckets["blocked"].append(key)
            elif fact.fetch_status == "section_missing":
                section_missing += 1
                buckets["section_missing"].append(key)
            if fact.audit_report_date_status == "ambiguous":
                buckets["ambiguous_dates"].append(key)

        items: list[CompletenessItem] = []
        next_cursor: str | None = None
        if status is not None:
            page, next_cursor = _page(buckets[status], cursor, limit)
            items = [CompletenessItem(rcept_no=rcept, dcm_no=dcm) for rcept, dcm in page]

        return CompletenessResponse(
            target=len(keys),
            ok=ok,
            fetch_failed=fetch_failed,
            blocked=blocked,
            section_missing=section_missing,
            unextracted=len(buckets["unextracted"]),
            ambiguous_dates=len(buckets["ambiguous_dates"]),
            field_partial=len(buckets["field_partial"]),
            items=items,
            next_cursor=next_cursor,
        )

    async def override_audit_report_date(
        self,
        rcept_no: str,
        dcm_no: str,
        iso: str,
    ) -> DateOverrideResponse:
        """기존 필드는 유지한 채 감사보고서일만 override로 채운다."""
        facts = FactRepository(self._session)
        fact = await facts.get(rcept_no, dcm_no)
        if fact is None:
            raise CatalogNotFound(f"추출 결과를 찾을 수 없습니다: {rcept_no}/{dcm_no}")
        fact.audit_report_date_override = iso
        fact.audit_report_date = iso
        fact.audit_report_date_status = "ok"
        fact.audit_report_date_source = "override"
        await facts.upsert(fact)
        await self._session.commit()
        return DateOverrideResponse(
            rcept_no=fact.rcept_no,
            dcm_no=fact.dcm_no,
            audit_report_date=fact.audit_report_date,
            audit_report_date_override=fact.audit_report_date_override,
            audit_report_date_status=fact.audit_report_date_status,
            audit_report_date_source=fact.audit_report_date_source,
        )
