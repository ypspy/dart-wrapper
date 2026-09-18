"""감사 추출 완전성 집계와 감사보고서일 수동 보정."""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Integer, and_, case, cast, exists, func, literal, or_, select

from app.errors import BadRequest, CatalogNotFound
from app.extracting.constants import EXTRACTOR_VERSION
from app.extracting.field_bundles import (
    BUNDLE_KEYS,
    BUNDLE_LABELS,
    DART_DOCUMENT_VIEW,
    EXPORT_PAGE_SIZE,
    FIELD_BUNDLE_REPORT_TYPES,
    ICFR_CONSOLIDATED_MANDATE_YEAR,
    ICFR_LISTED_CORP_CLS,
    empty_field_bundle_counts,
    status_attr,
)
from app.extracting.selector import (
    AUDIT_ATTACHMENT_DOC_NAMES,
    AUDIT_DOC_EXCLUDE_MARKERS,
    collect_audit_document_keys,
)
from app.models.audit_report_fact import AuditReportFact
from app.models.corp import Corp
from app.models.disclosure import Disclosure
from app.models.entry import Entry
from app.rcept_dt import to_dotted_rcept_dt
from app.repositories.entry_repository import EntryRepository
from app.repositories.fact_repository import FactRepository
from app.schemas.extract import (
    CompletenessItem,
    CompletenessResponse,
    DateOverrideResponse,
    FieldBundleCountsResponse,
    FieldBundleFailItem,
    FieldBundleFailListResponse,
    FieldBundleRow,
)

_ALLOWED_REPORT_TYPES = frozenset({"A001", "F001", "F002"})
LIST_STATUSES = (
    "unextracted",
    "stale_version",
    "fetch_failed",
    "blocked",
    "section_missing",
    "ambiguous_dates",
    "field_partial",
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


def _sum_if(condition: object) -> object:
    """조건이 참인 행만 센다. 빈 그룹은 0이다."""
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def _join_facts_window(statement: object) -> object:
    """facts–disclosures 필수, corps는 내부회계 판정용 LEFT JOIN."""
    return statement.join(
        Disclosure, AuditReportFact.rcept_no == Disclosure.rcept_no
    ).outerjoin(Corp, Corp.corp_code == Disclosure.corp_code)


def _icfr_period_year_sql() -> object:
    """icfr_period_year와 같이 결산월 연, 없으면 접수일 연. 이상값은 NULL."""
    year_from_end = cast(
        func.substr(
            Disclosure.year_end,
            func.instr(func.coalesce(Disclosure.year_end, ""), ".") - 4,
            4,
        ),
        Integer,
    )
    compact_rcept = func.replace(
        func.replace(func.coalesce(Disclosure.rcept_dt, ""), ".", ""),
        "-",
        "",
    )
    year_from_rcept = cast(func.substr(compact_rcept, 1, 4), Integer)
    year_end_usable = and_(
        Disclosure.year_end.is_not(None),
        Disclosure.year_end != "",
        func.instr(Disclosure.year_end, ".") > 4,
    )
    raw = case((year_end_usable, year_from_end), else_=year_from_rcept)
    return case((and_(raw >= 1900, raw <= 2100), raw), else_=None)


def _field_partial_sql():
    """현재 파서 ok 행에서 12묶음 실패가 하나라도 있는 조건."""
    return any_bundle_fail_clause()


def any_bundle_fail_clause() -> object:
    """한 행에 묶음 실패가 하나라도 있으면 참."""
    return or_(*(_fail_predicate(key) for key in BUNDLE_KEYS))


def _bundle_predicates(bundle: str) -> tuple[object, object, object, object]:
    """한 묶음의 NA·제도상없음·ok·실패 SQL 조건. classify_outcome과 같아야 한다."""
    col = getattr(AuditReportFact, status_attr(bundle))
    if bundle == "subsidiary":
        is_na = and_(
            AuditReportFact.fs_scope != "consolidated",
            col == "not_applicable",
        )
    else:
        is_na = literal(False)
    if bundle == "communications":
        is_expected = and_(
            col == "not_found",
            AuditReportFact.hours_status == "ok",
            AuditReportFact.activities_status == "ok",
        )
    elif bundle == "icfr":
        period_year = _icfr_period_year_sql()
        unlisted = or_(
            Corp.corp_cls.is_(None),
            Corp.corp_cls == "",
            ~Corp.corp_cls.in_(tuple(ICFR_LISTED_CORP_CLS)),
        )
        is_expected = and_(
            col == "skipped",
            or_(
                and_(
                    AuditReportFact.source_report_type == "F001",
                    unlisted,
                ),
                and_(
                    AuditReportFact.source_report_type == "F002",
                    period_year.is_not(None),
                    period_year < ICFR_CONSOLIDATED_MANDATE_YEAR,
                ),
            ),
        )
    else:
        is_expected = literal(False)
    is_ok = and_(~is_na, ~is_expected, col == "ok")
    is_fail = and_(~is_na, ~is_expected, or_(col.is_(None), col != "ok"))
    return is_na, is_expected, is_ok, is_fail


def _fail_predicate(bundle: str) -> object:
    """eligible 행에서 해당 묶음이 실패인 조건. 집계와 목록이 공유한다."""
    _is_na, _is_expected, _is_ok, is_fail = _bundle_predicates(bundle)
    return is_fail


def _compact_sql(column: object) -> object:
    """SQL에서 compact()와 같이 공백을 뺀다."""
    return func.replace(
        func.replace(func.replace(func.coalesce(column, ""), " ", ""), "\t", ""),
        "\n",
        "",
    )


def _audit_document_exists() -> object:
    """is_audit_document와 같은 대상 문서만 facts에 남긴다."""
    compacted = _compact_sql(Entry.document_name)
    excluded = or_(
        *[compacted.contains(marker) for marker in AUDIT_DOC_EXCLUDE_MARKERS]
    )
    named_attachment = and_(
        Entry.source == "attachment",
        compacted.in_(tuple(AUDIT_ATTACHMENT_DOC_NAMES)),
    )
    return exists(
        select(literal(1)).where(
            Entry.rcept_no == AuditReportFact.rcept_no,
            Entry.dcm_no == AuditReportFact.dcm_no,
            ~excluded,
            or_(
                and_(
                    Entry.report_type.in_(("F001", "F002")),
                    Entry.source != "attachment",
                ),
                and_(
                    Entry.report_type.in_(("F001", "F002", "A001")),
                    named_attachment,
                ),
            ),
        )
    )


class CompletenessService:
    """기간·유형별 추출 완전성을 집계하고 날짜 override를 저장한다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _window(self, start_date: str, end_date: str) -> tuple[str, str]:
        return to_dotted_rcept_dt(start_date), to_dotted_rcept_dt(end_date)

    def _disclosure_window(self, start_dt: str, end_dt: str, report_type: str):
        return and_(
            Disclosure.report_type == report_type,
            Disclosure.rcept_dt >= start_dt,
            Disclosure.rcept_dt <= end_dt,
        )

    def _fact_window(self, start_dt: str, end_dt: str, report_type: str):
        return and_(
            AuditReportFact.source_report_type == report_type,
            Disclosure.rcept_dt >= start_dt,
            Disclosure.rcept_dt <= end_dt,
        )

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
        """공시·facts 조인으로 건수를 세고, status가 있으면 문서 목록을 붙인다."""
        if status is not None and status not in LIST_STATUSES:
            raise BadRequest(
                "status는 unextracted, stale_version, fetch_failed, blocked, "
                "section_missing, ambiguous_dates, field_partial 중 하나여야 합니다."
            )
        summaries = await self.summarize_many(
            start_date=start_date,
            end_date=end_date,
            report_types=[report_type],
        )
        response = summaries[report_type]
        if status is None:
            return response

        start_dt, end_dt = self._window(start_date, end_date)
        keys, next_cursor = await self._list_status_keys(
            start_dt=start_dt,
            end_dt=end_dt,
            report_type=report_type,
            status=status,
            cursor=cursor,
            limit=limit,
        )
        return response.model_copy(
            update={
                "items": [
                    CompletenessItem(rcept_no=rcept, dcm_no=dcm) for rcept, dcm in keys
                ],
                "next_cursor": next_cursor,
            }
        )

    async def summarize_many(
        self,
        *,
        start_date: str,
        end_date: str,
        report_types: Sequence[str],
    ) -> dict[str, CompletenessResponse]:
        """기간 안 여러 유형 건수를 disclosures·facts 두 쿼리로 집계한다.

        대상·미추출은 접수(`rcept_no`) 단위이며, 한 접수에 감사 DCM이 둘이면
        한쪽만 fact여도 미추출이 0일 수 있다.
        """
        for report_type in report_types:
            if report_type not in _ALLOWED_REPORT_TYPES:
                raise BadRequest("report_type은 A001, F001, F002 중 하나여야 합니다.")
        start_dt, end_dt = self._window(start_date, end_date)
        filings = await self._filing_counts(start_dt, end_dt, report_types)
        facts = await self._fact_group_counts(start_dt, end_dt, report_types)
        summaries: dict[str, CompletenessResponse] = {}
        for report_type in report_types:
            group = facts.get(report_type, {})
            fact_rows = int(group.get("fact_rows", 0))
            fact_rcepts = int(group.get("fact_rcepts", 0))
            unextracted = max(int(filings.get(report_type, 0)) - fact_rcepts, 0)
            summaries[report_type] = CompletenessResponse(
                target=unextracted + fact_rows,
                ok=int(group.get("ok", 0)),
                fetch_failed=int(group.get("fetch_failed", 0)),
                blocked=int(group.get("blocked", 0)),
                section_missing=int(group.get("section_missing", 0)),
                unextracted=unextracted,
                stale_version=int(group.get("stale_version", 0)),
                ambiguous_dates=int(group.get("ambiguous_dates", 0)),
                field_partial=int(group.get("field_partial", 0)),
                all_success=int(group.get("all_success", 0)),
                items=[],
                next_cursor=None,
            )
        return summaries

    async def _filing_counts(
        self,
        start_dt: str,
        end_dt: str,
        report_types: Sequence[str],
    ) -> dict[str, int]:
        """유형별 공시 건수."""
        if not report_types:
            return {}
        statement = (
            select(Disclosure.report_type, func.count())
            .where(
                Disclosure.report_type.in_(list(report_types)),
                Disclosure.rcept_dt >= start_dt,
                Disclosure.rcept_dt <= end_dt,
            )
            .group_by(Disclosure.report_type)
        )
        rows = (await self._session.execute(statement)).all()
        return {str(report_type): int(count) for report_type, count in rows}

    async def _fact_group_counts(
        self,
        start_dt: str,
        end_dt: str,
        report_types: Sequence[str],
    ) -> dict[str, dict[str, int]]:
        """유형별 facts 건수를 한 번의 GROUP BY로 센다."""
        if not report_types:
            return {}
        ok_current = and_(
            AuditReportFact.fetch_status == "ok",
            AuditReportFact.extractor_version == EXTRACTOR_VERSION,
        )
        stale = and_(
            AuditReportFact.fetch_status == "ok",
            or_(
                AuditReportFact.extractor_version.is_(None),
                AuditReportFact.extractor_version != EXTRACTOR_VERSION,
            ),
        )
        statement = (
            _join_facts_window(
                select(
                    AuditReportFact.source_report_type,
                    func.count().label("fact_rows"),
                    func.count(func.distinct(AuditReportFact.rcept_no)).label(
                        "fact_rcepts"
                    ),
                    _sum_if(ok_current).label("ok"),
                    _sum_if(stale).label("stale_version"),
                    _sum_if(AuditReportFact.fetch_status == "fetch_failed").label(
                        "fetch_failed"
                    ),
                    _sum_if(AuditReportFact.fetch_status == "blocked").label("blocked"),
                    _sum_if(AuditReportFact.fetch_status == "section_missing").label(
                        "section_missing"
                    ),
                    _sum_if(
                        AuditReportFact.audit_report_date_status == "ambiguous"
                    ).label("ambiguous_dates"),
                    _sum_if(and_(ok_current, _field_partial_sql())).label(
                        "field_partial"
                    ),
                    _sum_if(and_(ok_current, ~any_bundle_fail_clause())).label(
                        "all_success"
                    ),
                )
            )
            .where(
                AuditReportFact.source_report_type.in_(list(report_types)),
                Disclosure.rcept_dt >= start_dt,
                Disclosure.rcept_dt <= end_dt,
                _audit_document_exists(),
            )
            .group_by(AuditReportFact.source_report_type)
        )
        rows = (await self._session.execute(statement)).all()
        grouped: dict[str, dict[str, int]] = {}
        for row in rows:
            grouped[str(row.source_report_type)] = {
                "fact_rows": int(row.fact_rows or 0),
                "fact_rcepts": int(row.fact_rcepts or 0),
                "ok": int(row.ok or 0),
                "stale_version": int(row.stale_version or 0),
                "fetch_failed": int(row.fetch_failed or 0),
                "blocked": int(row.blocked or 0),
                "section_missing": int(row.section_missing or 0),
                "ambiguous_dates": int(row.ambiguous_dates or 0),
                "field_partial": int(row.field_partial or 0),
                "all_success": int(row.all_success or 0),
            }
        return grouped

    async def _list_status_keys(
        self,
        *,
        start_dt: str,
        end_dt: str,
        report_type: str,
        status: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[DocKey], str | None]:
        """상태별 문서 식별자 한 페이지를 반환한다."""
        cursor_key = decode_cursor(cursor) if cursor else None
        if status == "unextracted":
            statement = (
                select(Disclosure.rcept_no)
                .outerjoin(
                    AuditReportFact,
                    and_(
                        AuditReportFact.rcept_no == Disclosure.rcept_no,
                        AuditReportFact.source_report_type == report_type,
                    ),
                )
                .where(
                    self._disclosure_window(start_dt, end_dt, report_type),
                    AuditReportFact.rcept_no.is_(None),
                )
                .order_by(Disclosure.rcept_no)
            )
            if cursor_key is not None:
                statement = statement.where(Disclosure.rcept_no > cursor_key[0])
            rcept_nos = list(
                (await self._session.execute(statement.limit(limit + 1))).scalars().all()
            )
            has_more = len(rcept_nos) > limit
            rcept_nos = rcept_nos[:limit]
            keys: list[DocKey] = []
            repo = EntryRepository(self._session)
            for rcept_no in rcept_nos:
                filing = await repo.list_by_rcept_no(rcept_no)
                doc_keys = collect_audit_document_keys(
                    [
                        (
                            entry.rcept_no,
                            entry.dcm_no,
                            entry.report_type,
                            entry.source,
                            entry.document_name,
                        )
                        for entry in filing
                    ]
                )
                if doc_keys:
                    keys.extend(doc_keys)
                else:
                    keys.append((rcept_no, ""))
            next_cursor = None
            if has_more and keys:
                last_rcept, last_dcm = keys[-1]
                next_cursor = encode_cursor(last_rcept, last_dcm)
            return keys, next_cursor

        extra = {
            "stale_version": and_(
                AuditReportFact.fetch_status == "ok",
                AuditReportFact.extractor_version != EXTRACTOR_VERSION,
            ),
            "fetch_failed": AuditReportFact.fetch_status == "fetch_failed",
            "blocked": AuditReportFact.fetch_status == "blocked",
            "section_missing": AuditReportFact.fetch_status == "section_missing",
            "ambiguous_dates": AuditReportFact.audit_report_date_status == "ambiguous",
            "field_partial": and_(
                AuditReportFact.fetch_status == "ok",
                AuditReportFact.extractor_version == EXTRACTOR_VERSION,
                _field_partial_sql(),
            ),
        }[status]
        statement = (
            _join_facts_window(
                select(AuditReportFact.rcept_no, AuditReportFact.dcm_no)
            )
            .where(
                self._fact_window(start_dt, end_dt, report_type),
                extra,
                _audit_document_exists(),
            )
            .order_by(AuditReportFact.rcept_no, AuditReportFact.dcm_no)
        )
        if cursor_key is not None:
            statement = statement.where(
                or_(
                    AuditReportFact.rcept_no > cursor_key[0],
                    and_(
                        AuditReportFact.rcept_no == cursor_key[0],
                        AuditReportFact.dcm_no > cursor_key[1],
                    ),
                )
            )
        rows = list((await self._session.execute(statement.limit(limit + 1))).all())
        has_more = len(rows) > limit
        page = [(row[0], row[1]) for row in rows[:limit]]
        next_cursor = None
        if has_more and page:
            last_rcept, last_dcm = page[-1]
            next_cursor = encode_cursor(last_rcept, last_dcm)
        return page, next_cursor

    def _eligible_fact_window(self, start_dt: str, end_dt: str):
        """현재 추출기·fetch ok·연구 유형만 기간 안으로 남긴다."""
        return and_(
            AuditReportFact.fetch_status == "ok",
            AuditReportFact.extractor_version == EXTRACTOR_VERSION,
            AuditReportFact.source_report_type.in_(list(FIELD_BUNDLE_REPORT_TYPES)),
            Disclosure.rcept_dt >= start_dt,
            Disclosure.rcept_dt <= end_dt,
            _audit_document_exists(),
        )

    async def list_patch_document_keys(
        self,
        *,
        start_date: str,
        end_date: str,
        report_types: Sequence[str],
    ) -> list[tuple[str, str]]:
        """칸 실패가 있는 현재 추출기 ok 문서의 (rcept_no, dcm_no)."""
        if not report_types:
            return []
        start_dt, end_dt = self._window(start_date, end_date)
        statement = (
            _join_facts_window(
                select(AuditReportFact.rcept_no, AuditReportFact.dcm_no)
            )
            .where(
                self._eligible_fact_window(start_dt, end_dt),
                AuditReportFact.source_report_type.in_(list(report_types)),
                any_bundle_fail_clause(),
            )
            .order_by(AuditReportFact.rcept_no, AuditReportFact.dcm_no)
        )
        rows = (await self._session.execute(statement)).all()
        return [(str(rcept_no), str(dcm_no)) for rcept_no, dcm_no in rows]

    async def summarize_field_bundles(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> FieldBundleCountsResponse:
        """기간 안 현재 추출기 facts를 12묶음 네 칸으로 센다."""
        start_dt, end_dt = self._window(start_date, end_date)
        eligible_where = self._eligible_fact_window(start_dt, end_dt)
        eligible_stmt = _join_facts_window(
            select(func.count()).select_from(AuditReportFact)
        ).where(eligible_where)
        eligible = int((await self._session.execute(eligible_stmt)).scalar_one())
        counts = empty_field_bundle_counts()
        columns = []
        for key in BUNDLE_KEYS:
            is_na, is_expected, is_ok, is_fail = _bundle_predicates(key)
            columns.extend(
                (
                    _sum_if(is_ok).label(f"{key}_ok"),
                    _sum_if(is_na).label(f"{key}_not_applicable"),
                    _sum_if(is_expected).label(f"{key}_expected_missing"),
                    _sum_if(is_fail).label(f"{key}_fail"),
                )
            )
        statement = _join_facts_window(
            select(*columns).select_from(AuditReportFact)
        ).where(eligible_where)
        row = (await self._session.execute(statement)).one()
        bundles: list[FieldBundleRow] = []
        for key in BUNDLE_KEYS:
            bucket = counts[key]
            bucket["ok"] = int(getattr(row, f"{key}_ok") or 0)
            bucket["not_applicable"] = int(getattr(row, f"{key}_not_applicable") or 0)
            bucket["expected_missing"] = int(getattr(row, f"{key}_expected_missing") or 0)
            bucket["fail"] = int(getattr(row, f"{key}_fail") or 0)
            bundles.append(
                FieldBundleRow(
                    bundle=key,
                    label=BUNDLE_LABELS[key],
                    ok=bucket["ok"],
                    not_applicable=bucket["not_applicable"],
                    expected_missing=bucket["expected_missing"],
                    fail=bucket["fail"],
                )
            )
        return FieldBundleCountsResponse(
            start_date=start_date,
            end_date=end_date,
            extractor_version=EXTRACTOR_VERSION,
            eligible=eligible,
            bundles=bundles,
        )

    async def list_field_bundle_fail_items(
        self,
        *,
        start_date: str,
        end_date: str,
        bundle: str,
        cursor: str | None = None,
        limit: int = 50,
    ) -> FieldBundleFailListResponse:
        """한 묶음의 실패 행을 keyset으로 한 페이지 반환한다."""
        if bundle not in BUNDLE_KEYS:
            raise BadRequest("bundle은 12개 필드 키 중 하나여야 합니다.")
        if limit > EXPORT_PAGE_SIZE:
            limit = EXPORT_PAGE_SIZE
        start_dt, end_dt = self._window(start_date, end_date)
        cursor_key = decode_cursor(cursor) if cursor else None
        status_col = getattr(AuditReportFact, status_attr(bundle))
        statement = (
            _join_facts_window(
                select(
                    AuditReportFact.source_report_type,
                    AuditReportFact.rcept_no,
                    AuditReportFact.dcm_no,
                    AuditReportFact.fs_scope,
                    status_col,
                    AuditReportFact.extractor_version,
                )
            )
            .where(
                self._eligible_fact_window(start_dt, end_dt),
                _fail_predicate(bundle),
            )
            .order_by(AuditReportFact.rcept_no, AuditReportFact.dcm_no)
        )
        if cursor_key is not None:
            statement = statement.where(
                or_(
                    AuditReportFact.rcept_no > cursor_key[0],
                    and_(
                        AuditReportFact.rcept_no == cursor_key[0],
                        AuditReportFact.dcm_no > cursor_key[1],
                    ),
                )
            )
        rows = list((await self._session.execute(statement.limit(limit + 1))).all())
        has_more = len(rows) > limit
        page = rows[:limit]
        items: list[FieldBundleFailItem] = []
        for (
            report_type,
            rcept_no,
            dcm_no,
            fs_scope,
            status,
            extractor_version,
        ) in page:
            items.append(
                FieldBundleFailItem(
                    report_type=report_type,
                    rcept_no=rcept_no,
                    dcm_no=dcm_no,
                    fs_scope=fs_scope,
                    bundle=bundle,
                    status=status,
                    extractor_version=extractor_version,
                    viewer_url=await self._viewer_url_for(rcept_no, dcm_no),
                )
            )
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_cursor(last.rcept_no, last.dcm_no)
        return FieldBundleFailListResponse(items=items, next_cursor=next_cursor)

    async def _viewer_url_for(self, rcept_no: str, dcm_no: str) -> str:
        """실패 검토용 원문. leaf viewer.do가 아니라 문서 전체 목차(main.do)다."""
        return DART_DOCUMENT_VIEW.format(rcept_no=rcept_no, dcm_no=dcm_no)

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
