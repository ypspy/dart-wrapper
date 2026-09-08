"""회사 업종 잡 오케스트레이션 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.opendart_company import (
    CompanyOverview,
    OpenDartCompanyClient,
    OpenDartHttpError,
)
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import BadRequest, CatalogConflict
from app.ksic import KsicEntry
from app.models.corp import Corp
from app.models.disclosure import Disclosure
from app.models.extraction_job import ExtractionJob
from app.repositories.extraction_job_repository import ExtractionJobRepository
from app.repositories.job_repository import JobRepository
from app.services.corp_industry_service import (
    CORP_INDUSTRY_EXTRACTOR_ID,
    CorpIndustryService,
)


@pytest.fixture
async def sessionmaker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


KSIC = {
    "C": KsicEntry(name="제조업", parent=None, level="div"),
    "26": KsicEntry(name="전자부품", parent="C", level="group"),
    "264": KsicEntry(name="통신장비", parent="26", level="class"),
}


@dataclass
class FakeClient:
    by_code: dict[str, CompanyOverview | Exception]

    async def fetch(self, corp_code: str, api_key: str) -> CompanyOverview:
        item = self.by_code[corp_code]
        if isinstance(item, Exception):
            raise item
        return item


def _disc(rcept_no: str, corp_code: str) -> Disclosure:
    return Disclosure(
        rcept_no=rcept_no,
        corp_code=corp_code,
        corp_name="회사",
        report_nm="감사보고서",
        report_type="F001",
        rcept_dt="20200331",
        entry_count=1,
    )


def _svc(
    sessionmaker: async_sessionmaker[AsyncSession],
    client: FakeClient,
    api_key: str = "key",
) -> CorpIndustryService:
    return CorpIndustryService(
        sessionmaker,
        cast(OpenDartCompanyClient, client),
        KSIC,
        api_key=api_key,
        concurrency=1,
    )


async def test_start_rejects_missing_api_key(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    service = _svc(sessionmaker_fixture, FakeClient({}), api_key="")
    with pytest.raises(BadRequest, match="인증키"):
        await service.start()
    async with sessionmaker_fixture() as session:
        assert (
            await ExtractionJobRepository(session).find_latest(CORP_INDUSTRY_EXTRACTOR_ID) is None
        )


async def test_start_rejects_duplicate_active_job(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    service = _svc(sessionmaker_fixture, FakeClient({}))
    first = await service.start()
    async with sessionmaker_fixture() as session:
        await ExtractionJobRepository(session).set_status(first, "running")
        await session.commit()
    with pytest.raises(CatalogConflict, match="회사 업종"):
        await service.start()


async def test_start_ignores_catalog_and_audit_locks(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """수집·감사 추출이 돌아도 회사 업종은 시작한다."""
    async with sessionmaker_fixture() as session:
        await JobRepository(session).create("cat-1", {"report_type": "F001"}, "k", mode="collect")
        await ExtractionJobRepository(session).create("ext-1", "audit_opinion", {}, mode="extract")
        await ExtractionJobRepository(session).set_status("ext-1", "running")
        await session.commit()
    service = _svc(sessionmaker_fixture, FakeClient({}))
    job_id = await service.start()
    assert job_id


async def test_run_skips_ok_and_fills_missing(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all([_disc("a", "00126380"), _disc("b", "00401731")])
        session.add(Corp(corp_code="00126380", fetch_status="ok", induty_code="264"))
        await session.commit()
    client = FakeClient(
        {
            "00401731": CompanyOverview(
                status="000",
                message="정상",
                corp_name="SK하이닉스",
                stock_code="000660",
                corp_cls="Y",
                induty_code="264",
            )
        }
    )
    service = _svc(sessionmaker_fixture, client)
    job_id = await service.start()
    await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        sk = await session.get(Corp, "00401731")
        samsung = await session.get(Corp, "00126380")
        job = await session.get(ExtractionJob, job_id)
    assert sk is not None
    assert sk.fetch_status == "ok"
    assert sk.induty_name_class == "통신장비"
    assert sk.induty_name_div == "제조업"
    assert samsung is not None
    assert samsung.induty_code == "264"
    assert job is not None
    assert job.status == "succeeded"
    assert job.params["target_count"] == 1
    assert job.params["processed_count"] == 1
    # 00126380은 FakeClient에 없다. 스킵되지 않으면 KeyError로 실패한다.


async def test_run_succeeds_when_target_empty(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_disc("a", "00126380"))
        session.add(Corp(corp_code="00126380", fetch_status="ok"))
        await session.commit()
    service = _svc(sessionmaker_fixture, FakeClient({}))
    job_id = await service.start()
    await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        job = await session.get(ExtractionJob, job_id)
    assert job is not None
    assert job.status == "succeeded"


async def test_run_stops_on_quota(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all([_disc("a", "001"), _disc("b", "002")])
        await session.commit()
    client = FakeClient(
        {
            "001": CompanyOverview(status="000", message="정상", induty_code="264"),
            "002": CompanyOverview(status="020", message="요청 제한"),
        }
    )
    service = _svc(sessionmaker_fixture, client)
    job_id = await service.start()
    await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        job = await session.get(ExtractionJob, job_id)
        one = await session.get(Corp, "001")
        two = await session.get(Corp, "002")
    assert job is not None
    assert job.status == "failed"
    assert "한도" in (job.error_message or "")
    assert one is not None and one.fetch_status == "ok"
    assert two is None


async def test_run_http_error_continues(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all([_disc("a", "001"), _disc("b", "002")])
        await session.commit()
    client = FakeClient(
        {
            "001": OpenDartHttpError("timeout"),
            "002": CompanyOverview(status="013", message="없음"),
        }
    )
    service = _svc(sessionmaker_fixture, client)
    job_id = await service.start()
    await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        one = await session.get(Corp, "001")
        two = await session.get(Corp, "002")
        job = await session.get(ExtractionJob, job_id)
    assert one is not None and one.fetch_status == "api_error"
    assert two is not None and two.fetch_status == "not_found"
    assert job is not None
    assert job.status == "succeeded"


async def test_summarize_counts(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all([_disc("a", "001"), _disc("b", "001"), _disc("c", "002")])
        session.add(Corp(corp_code="001", fetch_status="ok"))
        await session.commit()
    summary = await _svc(sessionmaker_fixture, FakeClient({})).summarize()
    assert summary.disclosure_corps == 2
    assert summary.ok_count == 1
    assert summary.remaining_count == 1
