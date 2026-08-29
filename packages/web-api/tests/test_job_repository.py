"""JobRepository 상태 전이·로그 테스트."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.repositories.job_repository import JobRepository


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


async def test_create_and_find_active(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        await repository.create("job-1", {"report_type": "F001"}, "key-1")
        await session.commit()

    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        active = await repository.find_active("key-1")
        other = await repository.find_active("key-2")

    assert active is not None and active.job_id == "job-1"
    assert active.status == "pending"
    assert other is None


async def test_status_transitions_and_logs(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        await repository.create("job-2", {}, "key-2")
        await repository.mark_running("job-2")
        await repository.add_log("job-2", "info", "수집을 시작합니다.")
        await repository.mark_succeeded("job-2", total_entries=12, saved_entries=12)
        await session.commit()

    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        job = await repository.get("job-2")
        logs = await repository.recent_logs("job-2")
        active = await repository.find_active("key-2")

    assert job is not None
    assert job.status == "succeeded"
    assert (job.total_entries, job.saved_entries) == (12, 12)
    assert job.started_at is not None and job.finished_at is not None
    assert [log.message for log in logs] == ["수집을 시작합니다."]
    assert active is None


async def test_find_any_active_ignores_params_key(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        await repository.create("job-a", {"report_type": "F001"}, "key-a")
        await session.commit()

    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        active = await repository.find_any_active()
        other = await repository.find_active("key-b")

    assert active is not None and active.job_id == "job-a"
    assert other is None


async def test_latest_returns_most_recent_job(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        # 생성 시각이 같은 밀리초에 찍히지 않도록 명시해 정렬만 검증한다.
        old = await repository.create("job-old", {"report_type": "F001"}, "k-old")
        old.created_at = datetime(2026, 7, 25, tzinfo=timezone.utc)
        new = await repository.create("job-new", {"report_type": "A001"}, "k-new")
        new.created_at = datetime(2026, 7, 26, tzinfo=timezone.utc)
        await session.commit()

    async with sessionmaker_fixture() as session:
        latest = await JobRepository(session).latest()

    assert latest is not None
    assert latest.job_id == "job-new"


async def test_latest_returns_none_when_no_job_exists(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        latest = await JobRepository(session).latest()

    assert latest is None


async def test_abandon_orphans_marks_active_jobs_partial(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        await repository.create("job-live", {"report_type": "F001"}, "key-live")
        await repository.mark_running("job-live")
        await repository.update_progress("job-live", saved_entries=3, total_entries=10)
        await repository.create("job-done", {}, "key-done")
        await repository.mark_succeeded("job-done", total_entries=1, saved_entries=1)
        await session.commit()

    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        abandoned = await repository.abandon_orphans()
        await session.commit()

    assert abandoned == ["job-live"]

    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        live = await repository.get("job-live")
        done = await repository.get("job-done")
        active = await repository.find_any_active()
        logs = await repository.recent_logs("job-live")

    assert live is not None and live.status == "partial"
    assert live.saved_entries == 3 and live.total_entries == 10
    assert "서버가 재시작" in (live.error_message or "")
    assert done is not None and done.status == "succeeded"
    assert active is None
    assert any("서버가 재시작" in log.message for log in logs)


async def test_mark_failed_records_message(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        await repository.create("job-3", {}, "key-3")
        await repository.mark_failed("job-3", "수집 프로세스가 비정상 종료되었습니다.")
        await session.commit()

    async with sessionmaker_fixture() as session:
        job = await JobRepository(session).get("job-3")

    assert job is not None
    assert job.status == "failed"
    assert job.error_message == "수집 프로세스가 비정상 종료되었습니다."
