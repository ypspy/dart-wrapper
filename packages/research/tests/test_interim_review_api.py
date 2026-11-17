"""반기·분기 검토 추출 Admin API. 합성 요청만 보낸다."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text

from app.adapters.dart_http import DartHttpClient
from app.db.session import create_all, create_db_engine, create_sessionmaker
from research.api.deps import get_interim_review_service
from research.models.extraction_job import ExtractionJob
from research.repositories.extraction_job_repository import ExtractionJobRepository

TOKEN = {"X-Admin-Token": "dev-admin-token"}


class _FakeInterim:
    """라우터가 넘기는 인자를 기록하는 가짜 서비스."""

    def __init__(self) -> None:
        self.started: list[tuple[str, str, list[str], str]] = []
        self.executed: list[str] = []

    async def start(
        self,
        start_date: str,
        end_date: str,
        report_types: list[str],
        mode: str,
    ) -> str:
        self.started.append((start_date, end_date, list(report_types), mode))
        return "job-interim-1"

    async def run_job(self, job_id: str) -> None:
        self.executed.append(job_id)


@pytest.fixture
async def memory_app():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)
    from conftest import create_app

    app = create_app()
    app.state.sessionmaker = sessionmaker
    app.state.dart_http = DartHttpClient(
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text="ok")),
            trust_env=False,
        ),
        max_retries=0,
        retry_backoff_seconds=0.0,
    )
    yield app, sessionmaker
    await engine.dispose()


async def test_interim_extract_requires_admin_token(client_factory) -> None:
    """토큰 없이 검토 추출을 요청하면 401이다."""
    from conftest import create_app

    app = create_app()
    async with client_factory(app) as client:
        response = await client.post(
            "/admin/extract/interim-review",
            json={"start_date": "20250801", "end_date": "20250831"},
        )
    assert response.status_code == 401


async def test_interim_extract_defaults_report_types_and_mode(client_factory) -> None:
    """유형과 mode를 생략하면 A002·A003과 extract다."""
    from conftest import create_app

    fake = _FakeInterim()
    app = create_app()
    app.dependency_overrides[get_interim_review_service] = lambda: fake
    async with client_factory(app) as client:
        response = await client.post(
            "/admin/extract/interim-review",
            json={"start_date": "20250801", "end_date": "20250831"},
            headers=TOKEN,
        )
    assert response.status_code == 202
    assert response.json()["job_id"] == "job-interim-1"
    assert response.json()["mode"] == "extract"
    assert fake.started == [("20250801", "20250831", ["A002", "A003"], "extract")]
    assert fake.executed == ["job-interim-1"]


async def test_interim_extract_rejects_other_report_type_and_mode(client_factory) -> None:
    """A002·A003과 extract|resume 밖은 422다."""
    from conftest import create_app

    app = create_app()
    app.dependency_overrides[get_interim_review_service] = lambda: _FakeInterim()
    async with client_factory(app) as client:
        bad_type = await client.post(
            "/admin/extract/interim-review",
            json={
                "start_date": "20250801",
                "end_date": "20250831",
                "report_types": ["A001"],
            },
            headers=TOKEN,
        )
        bad_mode = await client.post(
            "/admin/extract/interim-review",
            json={
                "start_date": "20250801",
                "end_date": "20250831",
                "mode": "reparse",
            },
            headers=TOKEN,
        )
    assert bad_type.status_code == 422
    assert bad_mode.status_code == 422


async def test_interim_extract_409_when_table_missing(client_factory, memory_app) -> None:
    """테이블이 없으면 409와 생성 스크립트 안내를 돌려준다."""
    app, sessionmaker = memory_app
    async with sessionmaker() as session:
        await session.execute(text("DROP TABLE interim_review_facts"))
        await session.commit()
    async with client_factory(app) as client:
        response = await client.post(
            "/admin/extract/interim-review",
            json={
                "start_date": "20250801",
                "end_date": "20250831",
                "report_types": ["A002"],
                "mode": "extract",
            },
            headers=TOKEN,
        )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "interim_review_facts 테이블이 없습니다. 생성 스크립트를 먼저 실행하세요."
    )


async def test_existing_status_reads_interim_job(client_factory, memory_app) -> None:
    """상태 조회는 job_id만으로 검토 추출 잡도 읽는다."""
    app, sessionmaker = memory_app
    async with sessionmaker() as session:
        await ExtractionJobRepository(session).create(
            "interim-status",
            "interim_review",
            {"start_date": "20250801", "end_date": "20250831"},
            mode="resume",
        )
        await session.commit()
    async with client_factory(app) as client:
        response = await client.get(
            "/admin/extract/status",
            params={"job_id": "interim-status"},
            headers=TOKEN,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "interim-status"
    assert body["mode"] == "resume"


async def test_soft_stop_and_force_finish_go_to_interim_service(client_factory, memory_app) -> None:
    """검토 잡의 중단·강제 종료는 검토 서비스의 메모리 플래그를 켠다."""
    app, sessionmaker = memory_app
    async with sessionmaker() as session:
        jobs = ExtractionJobRepository(session)
        await jobs.create("interim-stop", "interim_review", {}, mode="extract")
        await jobs.create("interim-finish", "interim_review", {}, mode="extract")
        await jobs.set_status("interim-finish", "running")
        await session.commit()
    async with client_factory(app) as client:
        stopped = await client.post(
            "/admin/extract/jobs/interim-stop/soft-stop",
            headers=TOKEN,
        )
        finished = await client.post(
            "/admin/extract/jobs/interim-finish/force-finish",
            headers=TOKEN,
        )
    assert stopped.status_code == 202
    assert finished.status_code == 202
    interim = app.state.interim_review_service
    assert "interim-stop" in interim._stop_requested
    assert "interim-finish" in interim._stop_requested
    async with sessionmaker() as session:
        job = await session.get(ExtractionJob, "interim-finish")
    assert job is not None and job.status == "partial"
