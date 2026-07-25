"""ViewerService 전체/단일 조회와 부분 실패 처리 테스트."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import pytest

from app.adapters.dart_http import DartHttpClient
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import CatalogNotFound, SourceFetchError
from app.repositories.entry_repository import EntryRepository
from app.schemas.entry import EntryRecord
from app.services.viewer_service import ViewerService

BODY_HTML = (
    "<html><body><p>재무상태표</p>"
    "<table><tr><th>과목</th><th>당기</th></tr>"
    "<tr><td>자산총계</td><td>1,000</td></tr></table></body></html>"
)


def _record(entry_id: str, path: str) -> EntryRecord:
    return EntryRecord(
        entry_id=entry_id,
        rcept_no="20260724000650",
        corp_code="00224628",
        corp_name="제이에스어소시에이츠",
        report_nm="감사보고서",
        rcept_dt="2026.07.24",
        source="body",
        dcm_no="11495035",
        ele_id=entry_id.rsplit("_", 1)[-1],
        document_name="감사보고서",
        section_name="재무상태표",
        path=["감사보고서", "재무상태표"],
        viewer_url=f"https://dart.fss.or.kr/report/viewer.do?{path}",
    )


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        await EntryRepository(session).upsert_many(
            [_record("e_1", "ok=1"), _record("e_2", "fail=1")]
        )
        await session.commit()
    yield sessionmaker
    await engine.dispose()


def _transport(fail_query: str | None = "fail=1") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if fail_query and fail_query in str(request.url):
            return httpx.Response(500, content=b"error")
        return httpx.Response(
            200, content=BODY_HTML.encode("euc-kr"), headers={"Content-Type": "text/html"}
        )

    return httpx.MockTransport(handler)


@asynccontextmanager
async def _service(sessionmaker, transport: httpx.MockTransport):
    """세션과 httpx 클라이언트를 정리하는 ViewerService 컨텍스트."""
    async with sessionmaker() as session, httpx.AsyncClient(transport=transport) as client:
        fetcher = DartHttpClient(client, max_retries=0, retry_backoff_seconds=0.0)
        yield ViewerService(EntryRepository(session), fetcher, concurrency=2)


async def test_get_disclosure_returns_all_leaf_sections(sessionmaker_fixture) -> None:
    async with _service(sessionmaker_fixture, _transport(fail_query=None)) as service:
        content = await service.get_disclosure("20260724000650")

    assert content.rcp_no == "20260724000650"
    assert content.meta.corp_name == "제이에스어소시에이츠"
    assert [section.entry_id for section in content.sections] == ["e_1", "e_2"]
    assert "재무상태표" in (content.sections[0].text or "")
    assert content.sections[0].tables[0].headers == ["과목", "당기"]
    assert all(section.error is None for section in content.sections)


async def test_get_disclosure_reports_partial_failure(sessionmaker_fixture) -> None:
    async with _service(sessionmaker_fixture, _transport()) as service:
        content = await service.get_disclosure("20260724000650")

    assert content.sections[0].error is None
    assert content.sections[1].error is not None
    assert content.sections[1].text is None


async def test_get_disclosure_raises_when_all_sections_fail(sessionmaker_fixture) -> None:
    async with _service(sessionmaker_fixture, _transport(fail_query="viewer.do")) as service:
        with pytest.raises(SourceFetchError):
            await service.get_disclosure("20260724000650")


async def test_get_disclosure_raises_for_unknown_rcept_no(sessionmaker_fixture) -> None:
    async with _service(sessionmaker_fixture, _transport(fail_query=None)) as service:
        with pytest.raises(CatalogNotFound):
            await service.get_disclosure("99999999999999")


async def test_get_section_returns_single_leaf(sessionmaker_fixture) -> None:
    async with _service(sessionmaker_fixture, _transport(fail_query=None)) as service:
        section = await service.get_section("20260724000650", "e_1")

    assert section.entry_id == "e_1"
    assert "재무상태표" in (section.text or "")


async def test_get_section_rejects_entry_from_other_disclosure(sessionmaker_fixture) -> None:
    async with _service(sessionmaker_fixture, _transport(fail_query=None)) as service:
        with pytest.raises(CatalogNotFound):
            await service.get_section("11111111111111", "e_1")
