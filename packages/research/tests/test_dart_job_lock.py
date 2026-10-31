"""추출 잠금이 카탈로그 수집과 감사 추출을 함께 보는지 검증한다."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import CatalogConflict
from app.repositories.job_repository import JobRepository
from research.models.extraction_job import ExtractionJob
from research.repositories.extraction_job_repository import ExtractionJobRepository
from research.services.dart_job_lock import STALE_RUNNING_SECONDS, assert_dart_idle


@pytest.fixture
async def sessionmaker_fixture():
    """추출 잡 테이블을 포함한 메모리 DB 세션메이커."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


async def test_assert_dart_idle_rejects_when_audit_extraction_is_running(
    sessionmaker_fixture,
) -> None:
    """감사 추출이 진행 중이면 다른 DART 작업을 거절한다."""
    async with sessionmaker_fixture() as session:
        jobs = ExtractionJobRepository(session)
        await jobs.create("ext-lock", "audit_opinion", {}, mode="extract")
        await jobs.set_status("ext-lock", "running")
        await session.commit()

    async with sessionmaker_fixture() as session:
        with pytest.raises(CatalogConflict, match="이미 진행 중"):
            await assert_dart_idle(session)


async def test_assert_dart_idle_rejects_when_catalog_job_is_running(
    sessionmaker_fixture,
) -> None:
    """카탈로그 수집이 진행 중이면 추출 쪽 잠금도 거절한다."""
    async with sessionmaker_fixture() as session:
        await JobRepository(session).create(
            "cat-lock",
            {"report_type": "F001", "start_date": "20260724", "end_date": "20260724"},
            "key-1",
            mode="collect",
        )
        await session.commit()

    async with sessionmaker_fixture() as session:
        with pytest.raises(CatalogConflict, match="이미 진행 중"):
            await assert_dart_idle(session)


async def test_assert_dart_idle_recovers_stale_running_extraction(
    sessionmaker_fixture,
) -> None:
    """오래된 running 추출 잡은 잠금을 풀고 실패로 마감한다."""
    async with sessionmaker_fixture() as session:
        jobs = ExtractionJobRepository(session)
        await jobs.create("ext-stale", "audit_opinion", {}, mode="extract")
        await jobs.set_status("ext-stale", "running")
        job = await session.get(ExtractionJob, "ext-stale")
        assert job is not None
        job.started_at = datetime.now(timezone.utc) - timedelta(
            seconds=STALE_RUNNING_SECONDS + 60
        )
        await session.commit()

    async with sessionmaker_fixture() as session:
        await assert_dart_idle(session)
        await session.commit()

    async with sessionmaker_fixture() as session:
        stale = await session.get(ExtractionJob, "ext-stale")
    assert stale is not None
    assert stale.status == "failed"
    assert stale.error_message is not None
    assert "중단" in stale.error_message
