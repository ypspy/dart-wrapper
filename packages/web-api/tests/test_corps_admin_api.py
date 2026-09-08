"""회사 업종 Admin JSON API 테스트."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI

from app.api.deps import get_corp_industry_service, get_settings_dep
from app.config import Settings
from app.errors import CatalogConflict
from app.main import create_app
from app.models.extraction_job import ExtractionJob, ExtractionJobLog
from app.services.corp_industry_service import CorpIndustrySummary

TOKEN_HEADER = {"X-Admin-Token": "dev-admin-token"}
ClientFactory = Callable[[FastAPI], httpx.AsyncClient]


class FakeCorpService:
    """라우터가 회사 업종 서비스에 전달한 요청을 기록한다."""

    def __init__(self) -> None:
        self.started = 0
        self.executed: list[str] = []
        self.soft_stopped: list[str] = []
        self.force_finished: list[str] = []
        self._stop_requested: set[str] = {"job-corps-1"}

    async def start(self) -> str:
        """테스트 잡 식별자를 반환한다."""
        self.started += 1
        return "job-corps-1"

    async def run_job(self, job_id: str) -> None:
        """백그라운드 실행 요청을 기록한다."""
        self.executed.append(job_id)

    async def request_soft_stop(self, job_id: str) -> None:
        """소프트 중단 요청을 기록한다."""
        self.soft_stopped.append(job_id)

    async def force_finish(self, job_id: str) -> None:
        """강제 종료 요청을 기록한다."""
        self.force_finished.append(job_id)

    async def get_status(self, job_id: str | None) -> tuple[ExtractionJob, list[ExtractionJobLog]]:
        """작업과 로그 한 건을 반환한다."""
        resolved_job_id = job_id or "job-corps-1"
        now = datetime.now(timezone.utc)
        return (
            ExtractionJob(
                job_id=resolved_job_id,
                extractor_id="corp_industry",
                status="running",
                mode="fill_missing",
                params={"processed_count": 1},
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

    async def summarize(self) -> CorpIndustrySummary:
        """고정 회사 업종 집계를 반환한다."""
        return CorpIndustrySummary(disclosure_corps=3, ok_count=1, remaining_count=2)


class BusyCorpService(FakeCorpService):
    """진행 중 충돌을 재현하는 서비스."""

    async def start(self) -> str:
        """활성 잡 충돌을 발생시킨다."""
        raise CatalogConflict("회사 업종 작업이 이미 진행 중입니다.")


def _app_with_corps(
    service: FakeCorpService,
    *,
    api_key: str = "opendart-test-key",
) -> FastAPI:
    """회사 업종 서비스와 설정을 주입한 앱을 만든다."""
    app = create_app()
    app.dependency_overrides[get_corp_industry_service] = lambda: service
    app.dependency_overrides[get_settings_dep] = lambda: Settings(opendart_api_key=api_key)
    return app


async def test_enrich_requires_admin_token(client_factory: ClientFactory) -> None:
    """토큰 없이 회사 업종 채움을 요청하면 401이다."""
    async with client_factory(_app_with_corps(FakeCorpService())) as client:
        response = await client.post("/admin/corps/enrich")

    assert response.status_code == 401
    assert "토큰" in response.json()["detail"]


async def test_enrich_rejects_missing_opendart_key(
    client_factory: ClientFactory,
) -> None:
    """OpenDART 키가 비어 있으면 서비스를 시작하지 않는다."""
    service = FakeCorpService()

    async with client_factory(_app_with_corps(service, api_key="")) as client:
        response = await client.post("/admin/corps/enrich", headers=TOKEN_HEADER)

    assert response.status_code == 400
    assert "OpenDART 인증키" in response.json()["detail"]
    assert service.started == 0


async def test_enrich_schedules_corp_job(client_factory: ClientFactory) -> None:
    """유효한 요청은 잡을 등록하고 백그라운드 실행한다."""
    service = FakeCorpService()

    async with client_factory(_app_with_corps(service)) as client:
        response = await client.post("/admin/corps/enrich", headers=TOKEN_HEADER)

    assert response.status_code == 202
    assert response.json() == {
        "job_id": "job-corps-1",
        "status": "pending",
        "mode": "fill_missing",
    }
    assert service.started == 1
    assert service.executed == ["job-corps-1"]


async def test_enrich_conflict_returns_409(client_factory: ClientFactory) -> None:
    """이미 진행 중인 회사 업종 잡은 409로 응답한다."""
    async with client_factory(_app_with_corps(BusyCorpService())) as client:
        response = await client.post("/admin/corps/enrich", headers=TOKEN_HEADER)

    assert response.status_code == 409
    assert "진행" in response.json()["detail"]


async def test_status_uses_latest_job_when_id_is_omitted(
    client_factory: ClientFactory,
) -> None:
    """job_id를 생략하면 최신 회사 업종 잡과 로그를 반환한다."""
    async with client_factory(_app_with_corps(FakeCorpService())) as client:
        response = await client.get("/admin/corps/status", headers=TOKEN_HEADER)

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "job-corps-1"
    assert body["status"] == "running"
    assert body["mode"] == "fill_missing"
    assert body["params"] == {"processed_count": 1}
    assert body["stop_requested"] is True
    assert body["logs"][0]["message"] == "회사 업종 작업을 실행 중입니다."


async def test_soft_stop_and_force_finish_delegate_to_service(
    client_factory: ClientFactory,
) -> None:
    """중단 API는 작업 식별자를 서비스에 전달하고 202를 반환한다."""
    service = FakeCorpService()

    async with client_factory(_app_with_corps(service)) as client:
        soft_stop = await client.post(
            "/admin/corps/jobs/job-corps-1/soft-stop",
            headers=TOKEN_HEADER,
        )
        force_finish = await client.post(
            "/admin/corps/jobs/job-corps-1/force-finish",
            headers=TOKEN_HEADER,
        )

    assert soft_stop.status_code == 202
    assert force_finish.status_code == 202
    assert service.soft_stopped == ["job-corps-1"]
    assert service.force_finished == ["job-corps-1"]


async def test_summary_returns_corp_counts(client_factory: ClientFactory) -> None:
    """회사 업종 요약은 공시 회사·완료·잔여 건수를 반환한다."""
    async with client_factory(_app_with_corps(FakeCorpService())) as client:
        response = await client.get("/admin/corps/summary", headers=TOKEN_HEADER)

    assert response.status_code == 200
    assert response.json() == {
        "disclosure_corps": 3,
        "ok_count": 1,
        "remaining_count": 2,
    }
