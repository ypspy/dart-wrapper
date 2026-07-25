"""SliceRepository의 체크포인트 갱신과 완전성 판정 테스트."""

from __future__ import annotations

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.repositories.slice_repository import SliceRepository


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


async def test_get_or_create_slice_is_idempotent(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = SliceRepository(session)
        first = await repository.get_or_create_slice("F001", "20260724")
        await session.commit()

    async with sessionmaker_fixture() as session:
        repository = SliceRepository(session)
        second = await repository.get_or_create_slice("F001", "20260724")
        await session.commit()

    assert first.slice_id == second.slice_id


async def test_evaluate_complete_when_all_succeeded(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = SliceRepository(session)
        slice_row = await repository.get_or_create_slice("F001", "20260724")
        await repository.set_listed(slice_row.slice_id, 2, "job-1")
        await repository.upsert_attempt(
            rcept_no="1", slice_id=slice_row.slice_id, report_type="F001", status="succeeded"
        )
        await repository.upsert_attempt(
            rcept_no="2", slice_id=slice_row.slice_id, report_type="F001", status="succeeded"
        )
        updated = await repository.evaluate_complete(slice_row.slice_id)
        await session.commit()

    assert updated.status == "complete"
    assert (updated.attempted, updated.succeeded, updated.failed_count) == (2, 2, 0)
    assert updated.finished_at is not None


async def test_evaluate_not_complete_with_failure(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = SliceRepository(session)
        slice_row = await repository.get_or_create_slice("F001", "20260724")
        await repository.set_listed(slice_row.slice_id, 2, "job-1")
        await repository.upsert_attempt(
            rcept_no="1", slice_id=slice_row.slice_id, report_type="F001", status="succeeded"
        )
        await repository.upsert_attempt(
            rcept_no="2",
            slice_id=slice_row.slice_id,
            report_type="F001",
            status="failed",
            last_error="원문을 가져오지 못했습니다.",
        )
        updated = await repository.evaluate_complete(slice_row.slice_id)
        await session.commit()

    assert updated.status != "complete"
    assert (updated.succeeded, updated.failed_count) == (1, 1)


async def test_evaluate_not_complete_when_listed_count_unknown(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = SliceRepository(session)
        slice_row = await repository.get_or_create_slice("F001", "20260724")
        await repository.upsert_attempt(
            rcept_no="1", slice_id=slice_row.slice_id, report_type="F001", status="succeeded"
        )
        updated = await repository.evaluate_complete(slice_row.slice_id)
        await session.commit()

    assert updated.status != "complete"


async def test_upsert_attempt_increments_retry_count(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = SliceRepository(session)
        slice_row = await repository.get_or_create_slice("F001", "20260724")
        await repository.upsert_attempt(
            rcept_no="1",
            slice_id=slice_row.slice_id,
            report_type="F001",
            status="failed",
            last_error="타임아웃",
        )
        await repository.upsert_attempt(
            rcept_no="1",
            slice_id=slice_row.slice_id,
            report_type="F001",
            status="succeeded",
            entry_count=5,
        )
        await session.commit()

        attempt = await repository.get_attempt("1")

    assert attempt is not None
    assert attempt.status == "succeeded"
    assert attempt.attempt == 2
    assert attempt.entry_count == 5


async def test_list_incomplete_returns_unfinished_slices(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = SliceRepository(session)
        done = await repository.get_or_create_slice("F001", "20260723")
        await repository.set_listed(done.slice_id, 1, "job-1")
        await repository.upsert_attempt(
            rcept_no="1", slice_id=done.slice_id, report_type="F001", status="succeeded"
        )
        await repository.evaluate_complete(done.slice_id)

        pending = await repository.get_or_create_slice("F001", "20260724")
        await repository.set_listed(pending.slice_id, 1, "job-1")
        await repository.upsert_attempt(
            rcept_no="2", slice_id=pending.slice_id, report_type="F001", status="failed"
        )
        await repository.evaluate_complete(pending.slice_id)
        await session.commit()

        incomplete = await repository.list_incomplete(report_type="F001")

    assert [row.slice_date for row in incomplete] == ["20260724"]


async def test_list_slices_filters_by_date_range(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = SliceRepository(session)
        for day in ("20260722", "20260723", "20260724"):
            await repository.get_or_create_slice("F001", day)
        await session.commit()

        rows = await repository.list_slices(
            report_type="F001", start_date="20260723", end_date="20260724"
        )

    assert [row.slice_date for row in rows] == ["20260724", "20260723"]
