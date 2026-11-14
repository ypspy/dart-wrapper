"""개선권고 이행 연구 테이블 생성과 교체 저장.

같은 접수번호의 현재 파싱을 지운 뒤 다시 넣으므로 재실행해도 행이 늘지 않는다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from sqlalchemy import Table, delete, or_, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.models.base import Base
from research.extracting.firm_remediation import PARSER_VERSION, PreparedDocument, vi_row_fields
from research.models.firm_remediation import (
    ExtractionFirmMatchReview,
    ExtractionFirmRemediation,
    ExtractionFirmRemediationDocument,
    ExtractionFirmRemediationNote,
)
from research.schema import _add_column_if_missing
from research.services.firm_remediation_loader import FirmRemediationError, FirmRemediationLoadError


@dataclass(frozen=True)
class MatchReviewSeed:
    """사람 확인 목록에 넣는 고정 시드."""

    reason: str
    corp_code: str
    other_corp_code: str
    corp_name: str
    other_corp_name: str | None


def firm_tables() -> list[Table]:
    """이 추출기가 만드는 연구 테이블만 돌려준다."""
    return [
        ExtractionFirmRemediation.__table__,
        ExtractionFirmRemediationNote.__table__,
        ExtractionFirmRemediationDocument.__table__,
        ExtractionFirmMatchReview.__table__,
    ]


def _iso_rcept_dt(rcept_no: str) -> str | None:
    """접수번호 앞 8자리 YYYYMMDD를 ISO 날짜로 바꾼다. 숫자가 아니면 None."""
    prefix = rcept_no[:8]
    if len(prefix) != 8 or not prefix.isdigit():
        return None
    return f"{prefix[:4]}-{prefix[4:6]}-{prefix[6:8]}"


_VI_ROW_COLUMNS = (
    ("category_raw", "TEXT"),
    ("category_inherited", "INTEGER"),
    ("finding_text", "TEXT"),
    ("action_text", "TEXT"),
    ("recommend_date_raw", "TEXT"),
    ("recommend_date_iso", "TEXT"),
    ("recommend_date_format", "TEXT"),
    ("action_date_in_text", "INTEGER"),
    ("multi_finding_flag", "INTEGER"),
    ("source_line_raw", "TEXT"),
    ("vi_status", "TEXT"),
    ("vi_status_reason", "TEXT"),
)
_VI_DOCUMENT_COLUMNS = (
    ("subsection", "TEXT"),
    ("corp_name", "TEXT"),
    ("body_hash", "TEXT"),
    ("fiscal_year", "INTEGER"),
    ("fiscal_year_src", "TEXT"),
    ("inspection_year_note", "TEXT"),
)
_VI_VIEW_NAME = "v_f004_vi_findings"
_VI_VIEW_SELECT = """
SELECT
    d.rcept_no AS rcept_no,
    d.rcept_dt AS rcept_dt,
    d.corp_code AS corp_code,
    d.corp_name AS corp_name,
    d.fiscal_year AS fiscal_year,
    d.fiscal_year_src AS fiscal_year_src,
    d.period_key AS period_key,
    d.subsection AS subsection,
    r.table_idx AS table_idx,
    r.row_idx AS row_idx,
    r.category_raw AS category_raw,
    r.category_inherited AS category_inherited,
    r.finding_text AS finding_text,
    r.action_text AS action_text,
    r.recommend_date_raw AS recommend_date_raw,
    r.recommend_date_iso AS recommend_date_iso,
    r.recommend_date_format AS recommend_date_format,
    CAST(NULL AS TEXT) AS action_date,
    r.action_date_in_text AS action_date_in_text,
    CAST(NULL AS TEXT) AS inspection_year,
    d.inspection_year_note AS inspection_year_note,
    r.multi_finding_flag AS multi_finding_flag,
    r.source_line_raw AS source_line_raw,
    r.vi_status AS parse_status,
    r.vi_status_reason AS parse_reason,
    r.is_latest AS is_latest,
    d.body_hash AS body_hash,
    r.parser_version AS parser_version
FROM extraction_firm_remediation AS r
JOIN extraction_firm_remediation_documents AS d ON d.rcept_no = r.rcept_no
WHERE r.vi_status IN ('ok', 'merged', 'partial')
   OR (r.vi_status IS NULL AND r.parse_status <> 'empty')
UNION ALL
SELECT
    d.rcept_no,
    d.rcept_dt,
    d.corp_code,
    d.corp_name,
    d.fiscal_year,
    d.fiscal_year_src,
    d.period_key,
    d.subsection,
    CAST(NULL AS INTEGER),
    CAST(NULL AS INTEGER),
    CAST(NULL AS TEXT),
    CAST(NULL AS INTEGER),
    CAST(NULL AS TEXT),
    CAST(NULL AS TEXT),
    CAST(NULL AS TEXT),
    CAST(NULL AS TEXT),
    CAST(NULL AS TEXT),
    CAST(NULL AS TEXT),
    CAST(NULL AS INTEGER),
    CAST(NULL AS TEXT),
    d.inspection_year_note,
    CAST(NULL AS INTEGER),
    CAST(NULL AS TEXT),
    'empty',
    'no_findings',
    CAST(NULL AS INTEGER),
    d.body_hash,
    d.parser_version
FROM extraction_firm_remediation_documents AS d
WHERE d.status = 'empty'
"""


async def create_firm_remediation_tables(engine: AsyncEngine) -> None:
    """대상 DB에 개선권고 테이블이 없으면 만들고, 빠진 열과 소비 뷰를 붙인다."""
    tables = firm_tables()

    def _create(sync_conn: object) -> None:
        Base.metadata.create_all(sync_conn, tables=tables)

    async with engine.begin() as connection:
        await connection.run_sync(_create)
        await _add_document_rcept_dt(connection)
        await _add_vi_columns(connection)
        await _ensure_vi_view(connection)


async def _add_document_rcept_dt(connection: AsyncConnection) -> None:
    """문서 테이블에 rcept_dt가 없으면 SQLite와 Postgres 모두 ALTER로 추가한다."""
    dialect = connection.dialect.name
    try:
        await _add_column_if_missing(
            connection,
            ExtractionFirmRemediationDocument.__tablename__,
            "rcept_dt",
            "VARCHAR(16) NOT NULL DEFAULT ''",
            dialect,
        )
    except SQLAlchemyError as exc:
        raise FirmRemediationError(
            "기존 문서 테이블에 rcept_dt 컬럼을 추가하지 못해 저장하지 않습니다."
        ) from exc


def fiscal_from_period_key(period_key: str | None) -> tuple[int | None, str | None]:
    """``YYYY-MM`` 기간 키의 연도와 출처. 키가 없으면 둘 다 비운다."""
    if not period_key or len(period_key) < 5 or period_key[4] != "-":
        return None, None
    year_text = period_key[:4]
    if not year_text.isdigit():
        return None, None
    return int(year_text), "catalog.year_end"


async def _add_vi_columns(connection: AsyncConnection) -> None:
    """0.1 테이블에 Ⅵ 열을 NULL 허용으로 붙인다. 이미 있으면 건너뛴다."""
    dialect = connection.dialect.name
    patches = (
        (ExtractionFirmRemediation.__tablename__, _VI_ROW_COLUMNS),
        (ExtractionFirmRemediationDocument.__tablename__, _VI_DOCUMENT_COLUMNS),
    )
    try:
        for table, columns in patches:
            for name, column_ddl in columns:
                await _add_column_if_missing(connection, table, name, column_ddl, dialect)
    except SQLAlchemyError as exc:
        raise FirmRemediationLoadError(
            "기존 개선권고 테이블에 Ⅵ 열을 추가하지 못해 저장하지 않습니다."
        ) from exc


async def _ensure_vi_view(connection: AsyncConnection) -> None:
    """쓰기 대상 DB에만 소비용 뷰를 만든다. 0.1 행의 NULL은 그대로 둔다."""
    try:
        if connection.dialect.name == "sqlite":
            await connection.execute(text(f"DROP VIEW IF EXISTS {_VI_VIEW_NAME}"))
            await connection.execute(text(f"CREATE VIEW {_VI_VIEW_NAME} AS {_VI_VIEW_SELECT}"))
            return
        await connection.execute(
            text(f"CREATE OR REPLACE VIEW {_VI_VIEW_NAME} AS {_VI_VIEW_SELECT}")
        )
    except SQLAlchemyError as exc:
        raise FirmRemediationLoadError("개선권고 소비 뷰를 만들지 못해 저장하지 않습니다.") from exc


class FirmRemediationRepository:
    """대상 DB에 문서·행·주석·확인 목록을 교체 저장한다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_snapshot(
        self,
        documents: Sequence[PreparedDocument],
        reviews: Sequence[MatchReviewSeed],
        *,
        extracted_at: datetime,
        parser_version: str = PARSER_VERSION,
    ) -> None:
        """입력에 들어 있는 접수번호의 기존 파싱을 현재 결과로 바꾼다."""
        rcept_nos = [document.rcept_no for document in documents]
        await self._delete_rcepts(ExtractionFirmRemediation, rcept_nos)
        await self._delete_rcepts(ExtractionFirmRemediationNote, rcept_nos)
        await self._delete_rcepts(ExtractionFirmRemediationDocument, rcept_nos)
        await self._session.flush()

        for document in documents:
            fiscal_year, fiscal_year_src = fiscal_from_period_key(document.period_key)
            self._session.add(
                ExtractionFirmRemediationDocument(
                    rcept_no=document.rcept_no,
                    corp_code=document.corp_code,
                    period_key=document.period_key,
                    rcept_dt=document.rcept_dt,
                    status=document.status,
                    n_tables=document.n_tables,
                    n_logical_rows=len(document.rows),
                    n_notes=len(document.notes),
                    subsection=document.subsection,
                    corp_name=document.corp_name,
                    body_hash=document.body_hash,
                    fiscal_year=fiscal_year,
                    fiscal_year_src=fiscal_year_src,
                    inspection_year_note=document.inspection_year_note,
                    parser_version=parser_version,
                    extracted_at=extracted_at,
                )
            )
            for row in document.rows:
                fields = vi_row_fields(row, rcept_dt=document.rcept_dt)
                self._session.add(
                    ExtractionFirmRemediation(
                        rcept_no=document.rcept_no,
                        table_idx=row.table_idx,
                        row_idx=row.row_idx,
                        corp_code=document.corp_code,
                        period_key=document.period_key,
                        component=row.component,
                        action_date=row.action_date,
                        finding=row.finding,
                        action=row.action,
                        is_latest=row.is_latest,
                        parse_status=row.parse_status,
                        source_cells=row.source_cells,
                        category_raw=fields.category_raw,
                        category_inherited=fields.category_inherited,
                        finding_text=fields.finding_text,
                        action_text=fields.action_text,
                        recommend_date_raw=fields.recommend_date_raw,
                        recommend_date_iso=fields.recommend_date_iso,
                        recommend_date_format=fields.recommend_date_format,
                        action_date_in_text=fields.action_date_in_text,
                        multi_finding_flag=fields.multi_finding_flag,
                        source_line_raw=fields.source_line_raw,
                        vi_status=fields.vi_status,
                        vi_status_reason=fields.vi_status_reason,
                        parser_version=parser_version,
                        extracted_at=extracted_at,
                    )
                )
            for note in document.notes:
                self._session.add(
                    ExtractionFirmRemediationNote(
                        rcept_no=document.rcept_no,
                        note_idx=note.note_idx,
                        table_idx=note.table_idx,
                        kind=note.kind,
                        raw_text=note.raw_text,
                        reason=note.reason,
                        parser_version=parser_version,
                        extracted_at=extracted_at,
                    )
                )

        await self._session.execute(delete(ExtractionFirmMatchReview))
        await self._session.flush()
        for review in reviews:
            self._session.add(
                ExtractionFirmMatchReview(
                    reason=review.reason,
                    corp_code=review.corp_code,
                    other_corp_code=review.other_corp_code,
                    corp_name=review.corp_name,
                    other_corp_name=review.other_corp_name,
                    parser_version=parser_version,
                    extracted_at=extracted_at,
                )
            )
        await self._session.flush()
        await self._backfill_empty_rcept_dt()
        await self._recompute_is_latest(documents)

    async def _backfill_empty_rcept_dt(self) -> None:
        """rcept_dt가 비어 있는 문서를 접수번호 앞 8자리의 ISO 날짜로 채운다.

        이번 입력에서 다시 넣은 문서는 이미 값이 있다. 구스키마에 남아 있던 같은 그룹만
        비어 있으면 (rcept_dt, rcept_no) 승자가 뒤집히므로, 비교 전에 채운다.
        """
        try:
            result = await self._session.execute(
                select(ExtractionFirmRemediationDocument.rcept_no).where(
                    or_(
                        ExtractionFirmRemediationDocument.rcept_dt.is_(None),
                        ExtractionFirmRemediationDocument.rcept_dt == "",
                    )
                )
            )
            for (rcept_no,) in result.all():
                iso = _iso_rcept_dt(str(rcept_no))
                if iso is None:
                    continue
                await self._session.execute(
                    update(ExtractionFirmRemediationDocument)
                    .where(ExtractionFirmRemediationDocument.rcept_no == rcept_no)
                    .values(rcept_dt=iso)
                )
            await self._session.flush()
            self._session.expire_all()
        except SQLAlchemyError as exc:
            raise FirmRemediationError(
                "기존 문서의 rcept_dt를 접수번호로 채우지 못해 저장하지 않습니다."
            ) from exc

    async def _recompute_is_latest(self, documents: Sequence[PreparedDocument]) -> None:
        """이번 입력의 (법인, 사업연도 말) 그룹만, DB에 있는 문서까지 포함해 다시 고른다."""
        groups = {
            (document.corp_code, document.period_key)
            for document in documents
            if document.period_key
        }
        if not groups:
            return
        corp_codes = list({corp_code for corp_code, _period in groups})
        result = await self._session.execute(
            select(ExtractionFirmRemediationDocument).where(
                ExtractionFirmRemediationDocument.corp_code.in_(corp_codes)
            )
        )
        stored = [
            row
            for row in result.scalars().all()
            if row.period_key and (row.corp_code, row.period_key) in groups
        ]
        by_group: dict[tuple[str, str], list[ExtractionFirmRemediationDocument]] = defaultdict(list)
        for row in stored:
            by_group[(row.corp_code, row.period_key or "")].append(row)
        for members in by_group.values():
            winner = max(members, key=lambda item: (item.rcept_dt, item.rcept_no))
            for item in members:
                flag = 1 if item.rcept_no == winner.rcept_no else 0
                await self._session.execute(
                    update(ExtractionFirmRemediation)
                    .where(ExtractionFirmRemediation.rcept_no == item.rcept_no)
                    .values(is_latest=flag)
                )
        await self._session.flush()

    async def _delete_rcepts(self, model: type, rcept_nos: Sequence[str]) -> None:
        """접수번호 묶음마다 기존 행을 지운다."""
        if not rcept_nos:
            return
        for start in range(0, len(rcept_nos), 400):
            chunk = list(rcept_nos[start : start + 400])
            await self._session.execute(delete(model).where(model.rcept_no.in_(chunk)))
