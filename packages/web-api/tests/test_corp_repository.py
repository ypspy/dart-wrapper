"""회사 마스터 대상 집합과 upsert 테스트."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.models.corp import Corp
from app.models.disclosure import Disclosure
from app.models.extraction_job import ExtractionJob
from app.repositories.corp_repository import CorpRepository
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.extraction_job_repository import ExtractionJobRepository


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def _disc(rcept_no: str, corp_code: str | None) -> Disclosure:
    return Disclosure(
        rcept_no=rcept_no,
        corp_code=corp_code,
        corp_name="회사",
        report_nm="감사보고서",
        report_type="F001",
        rcept_dt="20200331",
        entry_count=1,
    )


async def test_list_distinct_corp_codes_skips_blank_and_dedupes(
    sessionmaker_fixture,
) -> None:
    """NULL·빈 문자열을 빼고 고유번호만 모은다."""
    async with sessionmaker_fixture() as session:
        session.add_all(
            [
                _disc("a", "00126380"),
                _disc("b", "00126380"),
                _disc("c", ""),
                _disc("d", None),
                _disc("e", "00401731"),
            ]
        )
        await session.commit()
        codes = await DisclosureRepository(session).list_distinct_corp_codes()
    assert codes == ["00126380", "00401731"]


async def test_list_ok_codes_and_upsert(sessionmaker_fixture) -> None:
    """ok만 건너뛸 집합에 들어가고, 같은 PK는 덮어쓴다."""
    async with sessionmaker_fixture() as session:
        repos = CorpRepository(session)
        await repos.upsert(
            Corp(
                corp_code="00126380",
                fetch_status="ok",
                induty_code="264",
                fetched_at=datetime.now(timezone.utc),
            )
        )
        await repos.upsert(
            Corp(
                corp_code="00126380",
                fetch_status="ok",
                induty_code="265",
                fetched_at=datetime.now(timezone.utc),
            )
        )
        await repos.upsert(
            Corp(corp_code="00401731", fetch_status="not_found", opendart_status="013")
        )
        await session.commit()
        ok = await repos.list_ok_codes()
        assert ok == {"00126380"}
        assert await repos.count_ok() == 1
        loaded = await session.get(Corp, "00126380")
        assert loaded is not None
        assert loaded.induty_code == "265"


async def test_extraction_job_find_latest_and_update_params(
    sessionmaker_fixture,
) -> None:
    """extractor별 최신 잡과 JSON params 갱신."""
    async with sessionmaker_fixture() as session:
        jobs = ExtractionJobRepository(session)
        await jobs.create("old", "corp_industry", {"processed_count": 0})
        await jobs.create("new", "corp_industry", {"processed_count": 0})
        await jobs.create("other", "audit_opinion", {})
        await session.commit()
        latest = await jobs.find_latest("corp_industry")
        assert latest is not None
        assert latest.job_id == "new"
        await jobs.update_params("new", {"processed_count": 3, "target_count": 10})
        await session.commit()
        loaded = await jobs.get("new")
        assert loaded is not None
        assert loaded.params["processed_count"] == 3
