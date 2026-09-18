"""회사 업종 잡 오케스트레이션 테스트."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.opendart_company import (
    CompanyOverview,
    OpenDartCompanyClient,
    OpenDartHttpError,
)
from app.config import parse_opendart_api_keys
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
    by_key_and_code: dict[tuple[str, str], CompanyOverview | Exception] | None = None
    seen_keys: list[str] = field(default_factory=list)

    async def fetch(self, corp_code: str, api_key: str) -> CompanyOverview:
        self.seen_keys.append(api_key)
        item: CompanyOverview | Exception | None = None
        if self.by_key_and_code is not None:
            item = self.by_key_and_code.get((api_key, corp_code))
        if item is None:
            item = self.by_code[corp_code]
        if isinstance(item, Exception):
            raise item
        return item


class FailingConcurrentClient:
    """한 워커가 실패한 동안 다른 워커를 대기시키는 클라이언트."""

    def __init__(self) -> None:
        self.both_started = asyncio.Event()
        self.failure_raised = asyncio.Event()
        self.release_sibling = asyncio.Event()

    async def fetch(self, corp_code: str, api_key: str) -> CompanyOverview:
        if corp_code == "001":
            await self.both_started.wait()
            self.failure_raised.set()
            raise RuntimeError("의도한 워커 실패")
        self.both_started.set()
        await self.release_sibling.wait()
        return CompanyOverview(status="000", message="정상", induty_code="264")


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
    api_keys: tuple[str, ...] | None = None,
    concurrency: int = 1,
    ksic: dict[str, KsicEntry] | tuple[dict[str, KsicEntry], ...] | None = None,
) -> CorpIndustryService:
    keys = api_keys if api_keys is not None else ((api_key,) if api_key.strip() else ())
    return CorpIndustryService(
        sessionmaker,
        cast(OpenDartCompanyClient, client),
        KSIC if ksic is None else ksic,
        api_keys=keys,
        concurrency=concurrency,
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


async def test_start_rejects_concurrent_calls(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """동시 start() 호출 중 하나만 성공하고 나머지는 CatalogConflict."""
    service = _svc(sessionmaker_fixture, FakeClient({}))
    results = await asyncio.gather(
        service.start(),
        service.start(),
        return_exceptions=True,
    )
    job_ids = [result for result in results if isinstance(result, str)]
    conflicts = [result for result in results if isinstance(result, CatalogConflict)]
    assert len(job_ids) == 1
    assert len(conflicts) == 1
    async with sessionmaker_fixture() as session:
        job = await ExtractionJobRepository(session).find_latest(CORP_INDUSTRY_EXTRACTOR_ID)
    assert job is not None
    assert job.job_id == job_ids[0]


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


async def test_run_rotates_to_second_key_on_quota(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """한 키 한도가 차면 같은 회사를 다음 키로 다시 조회한다."""
    async with sessionmaker_fixture() as session:
        session.add_all([_disc("a", "001"), _disc("b", "002")])
        await session.commit()
    client = FakeClient(
        {},
        by_key_and_code={
            ("k1", "001"): CompanyOverview(status="000", message="정상", induty_code="264"),
            ("k1", "002"): CompanyOverview(status="020", message="요청 제한"),
            ("k2", "002"): CompanyOverview(status="000", message="정상", induty_code="264"),
        },
    )
    service = _svc(sessionmaker_fixture, client, api_keys=("k1", "k2"))
    job_id = await service.start()
    await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        job = await session.get(ExtractionJob, job_id)
        one = await session.get(Corp, "001")
        two = await session.get(Corp, "002")
        logs = await ExtractionJobRepository(session).recent_logs(job_id)
    assert job is not None
    assert job.status == "succeeded"
    assert one is not None and one.fetch_status == "ok"
    assert two is not None and two.fetch_status == "ok"
    assert "k1" in client.seen_keys
    assert "k2" in client.seen_keys
    assert any("다음 키" in (log.message or "") for log in logs)
    assert "k1" not in " ".join(log.message for log in logs)
    assert "k2" not in " ".join(log.message for log in logs)


async def test_run_fails_when_all_keys_hit_quota(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all([_disc("a", "001"), _disc("b", "002")])
        await session.commit()
    client = FakeClient(
        {},
        by_key_and_code={
            ("k1", "001"): CompanyOverview(status="000", message="정상", induty_code="264"),
            ("k1", "002"): CompanyOverview(status="020", message="요청 제한"),
            ("k2", "002"): CompanyOverview(status="020", message="요청 제한"),
        },
    )
    service = _svc(sessionmaker_fixture, client, api_keys=("k1", "k2"))
    job_id = await service.start()
    await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        job = await session.get(ExtractionJob, job_id)
        two = await session.get(Corp, "002")
    assert job is not None
    assert job.status == "failed"
    assert "한도" in (job.error_message or "")
    assert two is None


def test_parse_opendart_api_keys_dedupes_and_splits() -> None:
    assert parse_opendart_api_keys(" a ", "b", "a") == ("a", "b")
    assert parse_opendart_api_keys("k1, k2") == ("k1", "k2")
    assert parse_opendart_api_keys("") == ()


async def test_run_waits_for_sibling_workers_before_marking_failed(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """워커 예외가 나도 진행 중인 형제 워커 종료 전에는 잡을 실패 처리하지 않는다."""
    async with sessionmaker_fixture() as session:
        session.add_all([_disc("a", "001"), _disc("b", "002")])
        await session.commit()
    client = FailingConcurrentClient()
    service = _svc(
        sessionmaker_fixture,
        cast(FakeClient, client),
        concurrency=2,
    )
    job_id = await service.start()
    task = asyncio.create_task(service.run_job(job_id))

    await client.failure_raised.wait()
    await asyncio.sleep(0.05)
    done_before_release = task.done()
    async with sessionmaker_fixture() as session:
        job_before_release = await session.get(ExtractionJob, job_id)

    client.release_sibling.set()
    await task

    assert not done_before_release
    assert job_before_release is not None
    assert job_before_release.status == "running"
    async with sessionmaker_fixture() as session:
        job = await session.get(ExtractionJob, job_id)
        sibling = await session.get(Corp, "002")
    assert job is not None
    assert job.status == "failed"
    assert sibling is not None


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


async def test_remap_ksic_names_fills_without_opendart(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """저장된 업종코드에 이름을 다시 붙이고 OpenDART는 치지 않는다."""
    async with sessionmaker_fixture() as session:
        session.add_all(
            [
                Corp(corp_code="001", fetch_status="ok", induty_code="264"),
                Corp(corp_code="002", fetch_status="ok", induty_code="99999"),
                Corp(corp_code="003", fetch_status="ok"),
            ]
        )
        await session.commit()
    client = FakeClient({})
    service = _svc(sessionmaker_fixture, client)
    updated, unmatched = await service.remap_ksic_names()
    assert updated == 1
    assert unmatched == 1
    assert client.seen_keys == []
    async with sessionmaker_fixture() as session:
        one = await session.get(Corp, "001")
        two = await session.get(Corp, "002")
        three = await session.get(Corp, "003")
    assert one is not None
    assert one.fetch_status == "ok"
    assert one.induty_name_div == "제조업"
    assert one.induty_name_class == "통신장비"
    assert two is not None
    assert two.induty_name_div is None
    assert three is not None
    assert three.induty_name_div is None


async def test_remap_ksic_names_prefers_11th_then_10th(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """11차에만 있는 코드와 10차에만 있는 코드를 한 번에 채운다."""
    ksic11 = {
        "C": KsicEntry(name="제조업", parent=None, level="div"),
        "21212": KsicEntry(
            name="합성의약품 및 기타 완제 의약품 제조업", parent="C", level="item"
        ),
    }
    async with sessionmaker_fixture() as session:
        session.add_all(
            [
                Corp(corp_code="001", fetch_status="ok", induty_code="21212"),
                Corp(corp_code="002", fetch_status="ok", induty_code="264"),
            ]
        )
        await session.commit()
    service = _svc(sessionmaker_fixture, FakeClient({}), ksic=(ksic11, KSIC))
    updated, unmatched = await service.remap_ksic_names()
    assert updated == 2
    assert unmatched == 0
    async with sessionmaker_fixture() as session:
        one = await session.get(Corp, "001")
        two = await session.get(Corp, "002")
    assert one is not None
    assert one.induty_name_item == "합성의약품 및 기타 완제 의약품 제조업"
    assert two is not None
    assert two.induty_name_class == "통신장비"
