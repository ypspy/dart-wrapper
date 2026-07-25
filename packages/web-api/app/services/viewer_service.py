"""Lazy Retrieval Viewer 서비스. 조회 시점에 원문을 가져와 정제한다."""

from __future__ import annotations

import asyncio
import logging

from app.adapters.dart_http import DartHttpClient
from app.errors import CatalogNotFound, DartWrapperError, SourceFetchError
from app.models.entry import Entry
from app.parsing.cleaner import extract_text
from app.parsing.tables import extract_tables
from app.repositories.entry_repository import EntryRepository
from app.schemas.viewer import DisclosureContent, DisclosureMeta, SectionContent, TableData

logger = logging.getLogger(__name__)


class ViewerService:
    """카탈로그 엔트리의 viewer_url로 원문을 수집·정제한다."""

    def __init__(
        self,
        entries: EntryRepository,
        http: DartHttpClient,
        concurrency: int = 4,
    ) -> None:
        self._entries = entries
        self._http = http
        self._concurrency = concurrency

    async def get_disclosure(self, rcept_no: str) -> DisclosureContent:
        """접수번호에 속한 모든 leaf 섹션을 정제해 반환한다.

        일부 섹션이 실패하면 해당 섹션에만 error를 담고 나머지는 정상 반환한다.

        :raises CatalogNotFound: 카탈로그에 해당 접수번호가 없는 경우
        :raises SourceFetchError: 모든 섹션의 원문 수집이 실패한 경우
        """
        entries = await self._entries.list_by_rcept_no(rcept_no)
        if not entries:
            raise CatalogNotFound(
                f"접수번호 {rcept_no}에 해당하는 카탈로그 항목이 없습니다. "
                "먼저 Admin 수집을 실행해 주세요."
            )

        semaphore = asyncio.Semaphore(self._concurrency)
        sections = await asyncio.gather(
            *(self._load_section(entry, semaphore) for entry in entries)
        )

        if all(section.error is not None for section in sections):
            raise SourceFetchError(
                f"접수번호 {rcept_no}의 모든 구성 문서 원문을 가져오지 못했습니다."
            )

        return DisclosureContent(
            rcp_no=rcept_no,
            meta=DisclosureMeta(
                corp_name=entries[0].corp_name,
                corp_code=entries[0].corp_code,
                report_nm=entries[0].report_nm,
                rcept_dt=entries[0].rcept_dt,
            ),
            sections=list(sections),
        )

    async def get_section(self, rcept_no: str, entry_id: str) -> SectionContent:
        """특정 leaf 섹션 하나만 정제해 반환한다.

        :raises CatalogNotFound: 엔트리가 없거나 해당 접수번호에 속하지 않는 경우
        :raises SourceFetchError: 원문 수집이 실패한 경우
        """
        entry = await self._entries.get_by_entry_id(entry_id)
        if entry is None or entry.rcept_no != rcept_no:
            raise CatalogNotFound(
                f"접수번호 {rcept_no}에서 섹션 {entry_id}을(를) 찾을 수 없습니다."
            )

        html = await self._fetch_html(entry)
        return self._to_section(entry, html=html)

    async def _load_section(self, entry: Entry, semaphore: asyncio.Semaphore) -> SectionContent:
        """동시 요청 수를 제한하며 섹션 하나를 정제한다. 실패는 error로 담는다."""
        async with semaphore:
            try:
                html = await self._fetch_html(entry)
            except DartWrapperError as exc:
                logger.warning("섹션 원문 수집 실패(%s): %s", entry.entry_id, exc)
                return self._to_section(entry, error=str(exc))

            try:
                return self._to_section(entry, html=html)
            except DartWrapperError as exc:
                logger.warning("섹션 정제 실패(%s): %s", entry.entry_id, exc)
                return self._to_section(entry, error=str(exc))

    async def _fetch_html(self, entry: Entry) -> str:
        """엔트리의 viewer_url로 원문 HTML을 가져온다."""
        if not entry.viewer_url:
            raise SourceFetchError(f"섹션 {entry.entry_id}에 원문 주소가 없습니다.")
        return await self._http.fetch_html(entry.viewer_url)

    def _to_section(
        self,
        entry: Entry,
        html: str | None = None,
        error: str | None = None,
    ) -> SectionContent:
        """엔트리 메타와 정제 결과를 합쳐 응답 모델을 만든다."""
        text = extract_text(html) if html is not None else None
        tables = [TableData(**table) for table in extract_tables(html)] if html is not None else []
        return SectionContent(
            entry_id=entry.entry_id,
            source=entry.source,
            dcm_no=entry.dcm_no,
            ele_id=entry.ele_id,
            path=list(entry.path or []),
            document_name=entry.document_name,
            section_name=entry.section_name,
            text=text,
            tables=tables,
            error=error,
        )
