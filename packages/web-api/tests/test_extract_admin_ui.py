"""감사 추출 Admin HTML 모니터 테스트."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI

from app.api.deps import (
    get_catalog_service,
    get_completeness_service,
    get_corp_industry_service,
    get_extraction_service,
    get_slice_query_service,
)
from app.main import create_app
from app.schemas.catalog import JobLogItem
from app.schemas.extract import CompletenessResponse, ExtractJobStatusResponse
from tests.test_admin_ui import FakeCatalogService, FakeSliceQueryService
from tests.test_corps_admin_ui import FakeCorpIndustryService

ClientFactory = Callable[[FastAPI], httpx.AsyncClient]


class FakeCompletenessService:
    """유형별 고정 집계를 돌려준다."""

    async def summarize(self, **kwargs) -> CompletenessResponse:
        """테스트용 완전성 숫자."""
        return CompletenessResponse(
            target=10,
            ok=7,
            fetch_failed=1,
            blocked=0,
            section_missing=0,
            unextracted=2,
            ambiguous_dates=1,
            field_partial=3,
        )


class FakeExtractionService:
    """최근 추출 잡만 돌려준다."""

    def __init__(self, job: ExtractJobStatusResponse | None = None) -> None:
        self.job = job
        self.started: list[tuple[str, str, list[str], str]] = []
        self.executed: list[str] = []
        self.stopped: list[str] = []
        self.finished: list[str] = []

    async def get_latest_status(self) -> ExtractJobStatusResponse | None:
        """HTML이 쓰는 최신 잡."""
        return self.job

    async def start(
        self,
        start_date: str,
        end_date: str,
        report_types: list[str],
        mode: str,
    ) -> str:
        """폼 시작을 기록한다."""
        self.started.append((start_date, end_date, report_types, mode))
        return "extract-job-1"

    async def run_job(self, job_id: str) -> None:
        """백그라운드 실행 요청을 기록한다."""
        self.executed.append(job_id)

    async def request_soft_stop(self, job_id: str) -> None:
        """소프트 스톱을 기록한다."""
        self.stopped.append(job_id)

    async def force_finish(self, job_id: str) -> None:
        """강제 종료를 기록한다."""
        self.finished.append(job_id)


RUNNING_EXTRACT = ExtractJobStatusResponse(
    job_id="abcdef12deadbeef",
    status="running",
    mode="extract",
    params={
        "start_date": "20160101",
        "end_date": "20260909",
        "report_types": ["F001", "F002"],
        "processed_count": 4,
        "target_count": 10,
    },
    started_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
    logs=[
        JobLogItem(
            level="info",
            message="20200331000001/11111 추출 완료(ok).",
            created_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
        )
    ],
)


def _app(
    extraction: FakeExtractionService | None = None,
    catalog: FakeCatalogService | None = None,
) -> FastAPI:
    """추출 Admin 화면용 의존성을 대역으로 바꾼다."""
    app = create_app()
    app.dependency_overrides[get_slice_query_service] = lambda: FakeSliceQueryService()
    app.dependency_overrides[get_catalog_service] = lambda: catalog or FakeCatalogService(
        job=None
    )
    app.dependency_overrides[get_corp_industry_service] = lambda: FakeCorpIndustryService()
    app.dependency_overrides[get_extraction_service] = lambda: extraction or FakeExtractionService()
    app.dependency_overrides[get_completeness_service] = lambda: FakeCompletenessService()
    return app


async def test_extract_page_redirects_without_token(client_factory: ClientFactory) -> None:
    """토큰 없이 추출 화면은 토큰 페이지로 보낸다."""
    async with client_factory(_app()) as client:
        response = await client.get("/admin/extract")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/admin/token")


async def test_extract_page_defaults_research_window(
    client_factory: ClientFactory,
) -> None:
    """기본 기간은 잠긴 연구 창이다."""
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/extract")
    assert response.status_code == 200
    assert "20160101" in response.text
    assert "20260909" in response.text
    assert "추출 · 완전성" in response.text
    assert 'href="/admin/extract"' in response.text
    assert ">추출</a>" in response.text or "추출</a>" in response.text


async def test_extract_job_card_shows_progress(
    client_factory: ClientFactory,
) -> None:
    """잡 카드는 처리/대상과 최근 로그를 보여 준다."""
    extraction = FakeExtractionService(RUNNING_EXTRACT)
    async with client_factory(_app(extraction)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/extract/job-status")
    assert response.status_code == 200
    assert "처리 4 / 대상 10" in response.text or "4 / 10" in response.text
    assert "추출 완료(ok)" in response.text
