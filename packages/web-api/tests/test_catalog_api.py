"""Admin 카탈로그 라우터 테스트. 서비스는 가짜 구현으로 대체한다."""

from __future__ import annotations

from app.api.deps import get_catalog_service
from app.errors import CatalogNotFound
from app.main import create_app
from app.schemas.catalog import ExtractRequest, ExtractResponse, JobStatusResponse

PAYLOAD = {"report_type": "F001", "start_date": "20260724", "end_date": "20260724"}
# Admin 라우터는 공유 토큰을 요구한다. 테스트는 기본값을 그대로 쓴다.
HEADERS = {"X-Admin-Token": "dev-admin-token"}


class FakeCatalogService:
    """작업 등록과 실행 호출을 기록하는 가짜 서비스."""

    def __init__(self, status: str = "pending") -> None:
        self._status = status
        self.executed: list[str] = []

    async def start_extract(self, request: ExtractRequest) -> ExtractResponse:
        return ExtractResponse(job_id="job-1", status=self._status)

    async def run_job(self, job_id: str, request: ExtractRequest) -> None:
        self.executed.append(job_id)

    async def get_status(self, job_id: str) -> JobStatusResponse:
        if job_id != "job-1":
            raise CatalogNotFound(f"수집 작업을 찾을 수 없습니다: {job_id}")
        return JobStatusResponse(
            job_id=job_id, status="succeeded", total_entries=3, saved_entries=3
        )


def _app_with(service: object):
    app = create_app()
    app.dependency_overrides[get_catalog_service] = lambda: service
    return app


async def test_extract_accepts_request_and_schedules_job(client_factory) -> None:
    service = FakeCatalogService()

    async with client_factory(_app_with(service)) as client:
        response = await client.post("/admin/catalog/extract", json=PAYLOAD, headers=HEADERS)

    assert response.status_code == 202
    assert response.json() == {"job_id": "job-1", "status": "pending", "mode": "collect"}
    assert service.executed == ["job-1"]


async def test_extract_does_not_reschedule_running_job(client_factory) -> None:
    service = FakeCatalogService(status="running")

    async with client_factory(_app_with(service)) as client:
        response = await client.post("/admin/catalog/extract", json=PAYLOAD, headers=HEADERS)

    assert response.status_code == 202
    assert response.json()["status"] == "running"
    assert service.executed == []


async def test_extract_rejects_invalid_date(client_factory) -> None:
    async with client_factory(_app_with(FakeCatalogService())) as client:
        response = await client.post(
            "/admin/catalog/extract",
            json={**PAYLOAD, "start_date": "2026-07-24"},
            headers=HEADERS,
        )

    assert response.status_code == 422


async def test_status_returns_job_progress(client_factory) -> None:
    async with client_factory(_app_with(FakeCatalogService())) as client:
        response = await client.get(
            "/admin/catalog/status", params={"job_id": "job-1"}, headers=HEADERS
        )

    assert response.status_code == 200
    assert response.json()["saved_entries"] == 3


async def test_status_returns_404_for_unknown_job(client_factory) -> None:
    async with client_factory(_app_with(FakeCatalogService())) as client:
        response = await client.get(
            "/admin/catalog/status", params={"job_id": "job-9"}, headers=HEADERS
        )

    assert response.status_code == 404
