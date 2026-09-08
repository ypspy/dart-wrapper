"""회사 업종 Admin HTML 패널 테스트."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI

from app.api.deps import (
    get_catalog_service,
    get_corp_industry_service,
    get_settings_dep,
    get_slice_query_service,
)
from app.config import Settings
from app.main import create_app
from app.models.extraction_job import ExtractionJob, ExtractionJobLog
from app.errors import CatalogConflict
from app.services.corp_industry_service import CorpIndustrySummary
from tests.test_admin_ui import FakeCatalogService, FakeSliceQueryService

ClientFactory = Callable[[FastAPI], httpx.AsyncClient]


class FakeCorpIndustryService:
    """회사 업종 패널 요청을 기록하고 고정 현황을 반환한다."""

    def __init__(self) -> None:
        self.started = 0
        self.executed: list[str] = []
        self.stopped: list[str] = []
        self.finished: list[str] = []

    async def summarize(self) -> CorpIndustrySummary:
        """서로 다른 공시 회사 기준 집계를 반환한다."""
        return CorpIndustrySummary(disclosure_corps=3, ok_count=1, remaining_count=2)

    async def get_status(
        self,
        job_id: str | None,
    ) -> tuple[ExtractionJob, list[ExtractionJobLog]]:
        """진행 중인 회사 업종 작업과 최근 로그를 반환한다."""
        resolved_job_id = job_id or "corp-job-1"
        now = datetime.now(timezone.utc)
        return (
            ExtractionJob(
                job_id=resolved_job_id,
                extractor_id="corp_industry",
                status="running",
                mode="fill_missing",
                params={"processed_count": 1, "target_count": 2},
                started_at=now,
            ),
            [
                ExtractionJobLog(
                    job_id=resolved_job_id,
                    level="info",
                    message="회사 업종 작업을 실행 중입니다.",
                    created_at=now,
                )
            ],
        )

    async def start(self) -> str:
        """새 테스트 잡을 등록한다."""
        self.started += 1
        return "corp-job-1"

    async def run_job(self, job_id: str) -> None:
        """백그라운드 실행 요청을 기록한다."""
        self.executed.append(job_id)

    async def request_soft_stop(self, job_id: str) -> None:
        """소프트 스톱 요청을 기록한다."""
        self.stopped.append(job_id)

    async def force_finish(self, job_id: str) -> None:
        """강제 종료 요청을 기록한다."""
        self.finished.append(job_id)


class ConflictCorpIndustryService(FakeCorpIndustryService):
    """start()가 CatalogConflict를 내는 회사 업종 서비스 대역."""

    async def start(self) -> str:
        """이미 진행 중인 작업 충돌을 시뮬레이션한다."""
        self.started += 1
        raise CatalogConflict("회사 업종 작업이 이미 진행 중입니다.")


def _app(
    corps: FakeCorpIndustryService,
    *,
    api_key: str = "opendart-test-key",
) -> FastAPI:
    """Admin 화면용 의존성을 테스트 대역으로 바꾼다."""
    app = create_app()
    app.dependency_overrides[get_catalog_service] = lambda: FakeCatalogService()
    app.dependency_overrides[get_slice_query_service] = lambda: FakeSliceQueryService()
    app.dependency_overrides[get_corp_industry_service] = lambda: corps
    app.dependency_overrides[get_settings_dep] = lambda: Settings(opendart_api_key=api_key)
    return app


async def test_admin_index_renders_corp_industry_panel(
    client_factory: ClientFactory,
) -> None:
    """대시보드 첫 화면에 회사 업종 패널을 함께 렌더링한다."""
    async with client_factory(_app(FakeCorpIndustryService())) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin")

    assert response.status_code == 200
    assert "회사 업종" in response.text
    assert "빠진 회사 채우기" in response.text


async def test_corps_panel_renders_distinct_company_summary(
    client_factory: ClientFactory,
) -> None:
    """부분 갱신은 공시 건수가 아닌 회사 수 집계를 표시한다."""
    async with client_factory(_app(FakeCorpIndustryService())) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/corps-panel")

    assert response.status_code == 200
    assert "공시 회사 3 · 채움(ok) 1 · 남음 2" in response.text
    assert "실행 중 · 처리 1 / 대상 2" in response.text
    assert "회사 업종 작업을 실행 중입니다." in response.text


async def test_corps_panel_disables_start_without_opendart_key(
    client_factory: ClientFactory,
) -> None:
    """OpenDART 키가 없으면 시작 버튼과 직접 POST 모두 작업을 만들지 않는다."""
    corps = FakeCorpIndustryService()
    async with client_factory(_app(corps, api_key="")) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        panel = await client.get("/admin/corps-panel")
        start = await client.post("/admin/corps/start")

    assert panel.status_code == 200
    assert "disabled" in panel.text
    assert "OpenDART 인증키가 없습니다." in panel.text
    assert start.status_code == 303
    assert start.headers["location"].endswith("/admin")
    assert corps.started == 0


async def test_start_corps_conflict_redirects_to_admin(
    client_factory: ClientFactory,
) -> None:
    """시작 충돌 시에도 HTML 폼은 JSON 오류 대신 대시보드로 돌아간다."""
    corps = ConflictCorpIndustryService()
    async with client_factory(_app(corps)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post("/admin/corps/start")

    assert response.status_code == 303
    assert response.headers["location"].endswith("/admin")
    assert corps.executed == []


async def test_start_corps_job_redirects_to_admin(
    client_factory: ClientFactory,
) -> None:
    """HTML 시작 폼은 회사 업종 잡을 등록하고 대시보드로 돌아간다."""
    corps = FakeCorpIndustryService()
    async with client_factory(_app(corps)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post("/admin/corps/start")

    assert response.status_code == 303
    assert response.headers["location"].endswith("/admin")
    assert corps.started == 1
    assert corps.executed == ["corp-job-1"]


async def test_corp_job_controls_redirect_to_admin(
    client_factory: ClientFactory,
) -> None:
    """회사 업종 중단·종료 폼은 서비스를 호출한 뒤 대시보드로 돌아간다."""
    corps = FakeCorpIndustryService()
    async with client_factory(_app(corps)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        stop = await client.post("/admin/corps/jobs/corp-job-1/stop")
        finish = await client.post("/admin/corps/jobs/corp-job-1/finish")

    assert stop.status_code == 303
    assert finish.status_code == 303
    assert stop.headers["location"].endswith("/admin")
    assert finish.headers["location"].endswith("/admin")
    assert corps.stopped == ["corp-job-1"]
    assert corps.finished == ["corp-job-1"]
