"""개선권고 이행 연구 테이블 생성과 교체 저장.

같은 접수번호의 현재 파싱을 지운 뒤 다시 넣으므로 재실행해도 행이 늘지 않는다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from sqlalchemy import Table, delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models.base import Base
from research.extracting.firm_remediation import PARSER_VERSION, PreparedDocument
from research.models.firm_remediation import (
    ExtractionFirmMatchReview,
    ExtractionFirmRemediation,
    ExtractionFirmRemediationDocument,
    ExtractionFirmRemediationNote,
)


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


async def create_firm_remediation_tables(engine: AsyncEngine) -> None:
    """대상 DB에 개선권고 테이블이 없으면 만든다. 카탈로그 테이블은 만들지 않는다."""
    tables = firm_tables()

    def _create(sync_conn: object) -> None:
        Base.metadata.create_all(sync_conn, tables=tables)

    async with engine.begin() as connection:
        await connection.run_sync(_create)


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
                    parser_version=parser_version,
                    extracted_at=extracted_at,
                )
            )
            for row in document.rows:
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
        await self._recompute_is_latest(documents)

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
