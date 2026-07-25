"""슬라이스·공시 시도 ORM이 create_all에 포함되는지 검증한다."""

from __future__ import annotations

from sqlalchemy import select

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.models.catalog_job import CatalogJob
from app.models.slice_progress import DisclosureAttempt, SliceProgress


async def test_slice_and_attempt_roundtrip() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)

    async with sessionmaker() as session:
        session.add(
            SliceProgress(
                slice_id="s1",
                report_type="F001",
                slice_date="20260724",
                status="pending",
                listed_count=None,
            )
        )
        session.add(
            DisclosureAttempt(
                rcept_no="20260724000650",
                slice_id="s1",
                report_type="F001",
                status="pending",
            )
        )
        await session.commit()

        loaded = (
            await session.execute(select(SliceProgress).where(SliceProgress.slice_id == "s1"))
        ).scalar_one()
        assert loaded.slice_date == "20260724"
        assert loaded.listed_count is None
        assert (loaded.attempted, loaded.succeeded, loaded.failed_count) == (0, 0, 0)

        attempt = (
            await session.execute(
                select(DisclosureAttempt).where(DisclosureAttempt.rcept_no == "20260724000650")
            )
        ).scalar_one()
        assert attempt.status == "pending"
        assert attempt.attempt == 0

    await engine.dispose()


async def test_catalog_job_defaults_to_collect_mode() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)

    async with sessionmaker() as session:
        session.add(CatalogJob(job_id="job-1", params={}, params_key="k"))
        await session.commit()

        job = (
            await session.execute(select(CatalogJob).where(CatalogJob.job_id == "job-1"))
        ).scalar_one()
        assert job.mode == "collect"

    await engine.dispose()
