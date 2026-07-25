"""Admin 인증과 슬라이스·재개 라우터 테스트."""

from __future__ import annotations

from datetime import datetime, timezone

from app.api.deps import get_catalog_service, get_slice_query_service
from app.errors import CatalogNotFound
from app.main import create_app
from app.schemas.catalog import (
    DisclosureAttemptItem,
    ExtractResponse,
    ResumeRequest,
    SliceDetailResponse,
    SliceListResponse,
    SliceSummary,
)

TOKEN_HEADER = {"X-Admin-Token": "dev-admin-token"}
PAYLOAD = {"report_type": "F001", "start_date": "20260724", "end_date": "20260724"}

SUMMARY = SliceSummary(
    slice_id="s1",
    report_type="F001",
    slice_date="20260724",
    status="blocked",
    listed_count=3,
    attempted=2,
    succeeded=1,
    failed_count=1,
    attempt=1,
    last_job_id="job-1",
    updated_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
)


class FakeCatalogService:
    """작업 등록·재개·중단 호출을 기록하는 가짜 서비스."""

    def __init__(self) -> None:
        self.resumed: list[ResumeRequest] = []
        self.executed: list[str] = []
        self.stopped: list[str] = []

    async def start_extract(self, request) -> ExtractResponse:
        return ExtractResponse(job_id="job-1", status="pending", mode="collect")

    async def run_job(self, job_id: str, request) -> None:
        self.executed.append(job_id)

    async def start_resume(self, request: ResumeRequest) -> ExtractResponse:
        self.resumed.append(request)
        return ExtractResponse(job_id="job-2", status="pending", mode="resume")

    async def run_resume_job(self, job_id: str, request: ResumeRequest) -> None:
        self.executed.append(job_id)

    async def request_soft_stop(self, job_id: str) -> None:
        self.stopped.append(job_id)


class FakeSliceQueryService:
    """슬라이스 조회 결과를 고정으로 돌려주는 가짜 서비스."""

    async def list_slices(self, **kwargs) -> SliceListResponse:
        return SliceListResponse(items=[SUMMARY])

    async def get_slice(self, slice_id: str) -> SliceDetailResponse:
        if slice_id != "s1":
            raise CatalogNotFound(f"수집 슬라이스를 찾을 수 없습니다: {slice_id}")
        return SliceDetailResponse(
            slice=SUMMARY,
            attempts=[
                DisclosureAttemptItem(
                    rcept_no="2",
                    status="failed",
                    entry_count=0,
                    attempt=1,
                    last_error="상세 파싱에 실패했습니다.",
                )
            ],
        )


def _app():
    app = create_app()
    catalog = FakeCatalogService()
    app.dependency_overrides[get_catalog_service] = lambda: catalog
    app.dependency_overrides[get_slice_query_service] = lambda: FakeSliceQueryService()
    return app, catalog


async def test_extract_requires_admin_token(client_factory) -> None:
    app, _ = _app()

    async with client_factory(app) as client:
        response = await client.post("/admin/catalog/extract", json=PAYLOAD)

    assert response.status_code == 401
    assert "토큰" in response.json()["detail"]


async def test_extract_rejects_wrong_token(client_factory) -> None:
    app, _ = _app()

    async with client_factory(app) as client:
        response = await client.post(
            "/admin/catalog/extract", json=PAYLOAD, headers={"X-Admin-Token": "wrong-token"}
        )

    assert response.status_code == 401


async def test_extract_accepts_cookie_token(client_factory) -> None:
    app, catalog = _app()

    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post("/admin/catalog/extract", json=PAYLOAD)

    assert response.status_code == 202
    assert catalog.executed == ["job-1"]


async def test_resume_schedules_job(client_factory) -> None:
    app, catalog = _app()

    async with client_factory(app) as client:
        response = await client.post(
            "/admin/catalog/resume", json={"report_type": "F001"}, headers=TOKEN_HEADER
        )

    assert response.status_code == 202
    assert response.json() == {"job_id": "job-2", "status": "pending", "mode": "resume"}
    assert catalog.resumed[0].report_type == "F001"
    assert catalog.executed == ["job-2"]


async def test_list_slices_returns_completeness_summary(client_factory) -> None:
    app, _ = _app()

    async with client_factory(app) as client:
        response = await client.get(
            "/admin/catalog/slices", params={"report_type": "F001"}, headers=TOKEN_HEADER
        )

    body = response.json()
    assert response.status_code == 200
    assert body["items"][0]["slice_date"] == "20260724"
    assert body["items"][0]["listed_count"] == 3
    assert body["items"][0]["succeeded"] == 1


async def test_slice_detail_lists_attempts(client_factory) -> None:
    app, _ = _app()

    async with client_factory(app) as client:
        response = await client.get("/admin/catalog/slices/s1", headers=TOKEN_HEADER)

    body = response.json()
    assert response.status_code == 200
    assert body["attempts"][0]["rcept_no"] == "2"
    assert body["attempts"][0]["status"] == "failed"


async def test_slice_detail_returns_404_for_unknown_slice(client_factory) -> None:
    app, _ = _app()

    async with client_factory(app) as client:
        response = await client.get("/admin/catalog/slices/없음", headers=TOKEN_HEADER)

    assert response.status_code == 404


async def test_slice_retry_starts_resume_for_that_slice(client_factory) -> None:
    app, catalog = _app()

    async with client_factory(app) as client:
        response = await client.post("/admin/catalog/slices/s1/retry", headers=TOKEN_HEADER)

    assert response.status_code == 202
    assert catalog.resumed[0].slice_id == "s1"
    assert catalog.executed == ["job-2"]


async def test_soft_stop_requests_job_stop(client_factory) -> None:
    app, catalog = _app()

    async with client_factory(app) as client:
        response = await client.post("/admin/catalog/jobs/job-1/soft-stop", headers=TOKEN_HEADER)

    assert response.status_code == 202
    assert catalog.stopped == ["job-1"]
