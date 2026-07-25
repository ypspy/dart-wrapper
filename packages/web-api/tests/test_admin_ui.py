"""Admin 화면 스모크 테스트. 렌더링과 인증 흐름만 확인한다."""

from __future__ import annotations

from datetime import datetime, timezone

from app.api.deps import get_catalog_service, get_slice_query_service
from app.main import create_app
from app.schemas.catalog import (
    DisclosureAttemptItem,
    HeatmapCell,
    HeatmapMonthLabel,
    HeatmapResponse,
    HeatmapRow,
    JobLogItem,
    JobStatusResponse,
    SliceDetailResponse,
    SliceListResponse,
    SliceSummary,
)

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

HEATMAP = HeatmapResponse(
    start_date="20250720",
    end_date="20260725",
    month_labels=[HeatmapMonthLabel(week_index=0, label="Jul")],
    rows=[
        HeatmapRow(
            report_type="F001",
            weeks=[
                [
                    HeatmapCell(
                        slice_date="20260724",
                        level="complete",
                        slice_id="s1",
                        status="complete",
                        succeeded=3,
                        listed_count=3,
                    ),
                    HeatmapCell(slice_date="20260725", level="missing"),
                    *[
                        HeatmapCell(slice_date=f"future-{index}", level="future")
                        for index in range(5)
                    ],
                ],
                *[
                    [
                        HeatmapCell(
                            slice_date=f"future-{week}-{day}",
                            level="future",
                        )
                        for day in range(7)
                    ]
                    for week in range(52)
                ],
            ],
        )
    ],
)


class FakeSliceQueryService:
    async def list_slices(self, **kwargs) -> SliceListResponse:
        return SliceListResponse(items=[SUMMARY])

    async def get_slice(self, slice_id: str) -> SliceDetailResponse:
        return SliceDetailResponse(
            slice=SUMMARY,
            attempts=[
                DisclosureAttemptItem(
                    rcept_no="20260724000651",
                    status="failed",
                    entry_count=0,
                    attempt=2,
                    last_error="상세 파싱에 실패했습니다.",
                )
            ],
        )

    async def heatmap(self) -> HeatmapResponse:
        return HEATMAP


JOB_STATUS = JobStatusResponse(
    job_id="job-1234abcd",
    status="running",
    mode="collect",
    params={"report_type": "F001", "start_date": "20260701", "end_date": "20260726"},
    total_entries=10,
    saved_entries=4,
    logs=[
        JobLogItem(
            level="info",
            message="수집을 시작합니다.",
            created_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
        ),
        JobLogItem(
            level="warn",
            message="재시도합니다.",
            created_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
        ),
        JobLogItem(
            level="error",
            message="상세 파싱에 실패했습니다.",
            created_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
        ),
    ],
)


class FakeCatalogService:
    """최신 작업 현황과 중단 요청만 흉내 낸다."""

    def __init__(self, job: JobStatusResponse | None = JOB_STATUS) -> None:
        self.job = job
        self.stopped: list[str] = []

    async def get_latest_status(self) -> JobStatusResponse | None:
        return self.job

    async def request_soft_stop(self, job_id: str) -> None:
        self.stopped.append(job_id)


def _app(catalog: FakeCatalogService | None = None):
    app = create_app()
    app.dependency_overrides[get_slice_query_service] = lambda: FakeSliceQueryService()
    app.dependency_overrides[get_catalog_service] = lambda: catalog or FakeCatalogService()
    return app


async def test_admin_index_redirects_without_token(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/admin")

    assert response.status_code == 307
    assert response.headers["location"].endswith("/admin/token")


async def test_token_form_sets_cookie_and_redirects(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.post("/admin/token", data={"token": "dev-admin-token"})

    assert response.status_code == 303
    assert response.headers["location"].endswith("/admin")
    assert client.cookies.get("admin_token") == "dev-admin-token"


async def test_token_form_rejects_wrong_token(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.post("/admin/token", data={"token": "wrong-token"})

    assert response.status_code == 200
    assert "올바르지" in response.text


async def test_admin_index_renders_collect_form_and_slices(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin")

    assert response.status_code == 200
    body = response.text
    assert "수집 시작" in body
    assert "20260724" in body
    assert "재시도" in body
    assert "이어하기" in body


async def test_admin_index_renders_heatmap_links_and_legend(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin")

    assert response.status_code == 200
    assert "연간 수집 완전성" in response.text
    assert "F001" in response.text
    assert 'href="/admin/slices/s1"' in response.text
    assert (
        'href="/admin?report_type=F001&amp;start_date=20260725'
        '&amp;end_date=20260725"' in response.text
    )
    assert "미입수" in response.text
    assert "미완성" in response.text
    assert "완료" in response.text


async def test_heatmap_partial_requires_cookie_token(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/admin/heatmap")

    assert response.status_code == 307
    assert response.headers["location"].endswith("/admin/token")


async def test_heatmap_partial_renders_for_authenticated_admin(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/heatmap")

    assert response.status_code == 200
    assert "F001" in response.text
    assert "미입수" in response.text
    assert "미완성" in response.text
    assert "완료" in response.text
    assert 'href="/admin/slices/s1"' in response.text


async def test_admin_query_prefills_collect_form(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get(
            "/admin",
            params={
                "report_type": "A001",
                "start_date": "20260102",
                "end_date": "20260102",
            },
        )

    assert 'name="report_type" value="A001"' in response.text
    assert 'name="start_date" value="20260102"' in response.text
    assert 'name="end_date" value="20260102"' in response.text


async def test_job_status_partial_requires_cookie_token(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/admin/job-status")

    assert response.status_code == 307
    assert response.headers["location"].endswith("/admin/token")


async def test_job_status_partial_renders_running_job(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/job-status")

    assert response.status_code == 200
    body = response.text
    assert "job-1234" in body
    assert "running" in body
    assert "20260701 ~ 20260726" in body
    assert "소프트 스톱" in body


async def test_job_status_partial_renders_idle_without_job(client_factory) -> None:
    async with client_factory(_app(FakeCatalogService(job=None))) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/job-status")

    assert response.status_code == 200
    assert "대기 중" in response.text
    assert "소프트 스톱" not in response.text


async def test_job_logs_partial_defaults_to_warn_and_error(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/job-logs")

    assert response.status_code == 200
    body = response.text
    assert "재시도합니다." in body
    assert "상세 파싱에 실패했습니다." in body
    assert "수집을 시작합니다." not in body


async def test_job_logs_partial_can_include_info_level(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/job-logs", params={"levels": "info,warn,error"})

    assert response.status_code == 200
    assert "수집을 시작합니다." in response.text


async def test_soft_stop_form_requests_stop_and_redirects(client_factory) -> None:
    catalog = FakeCatalogService()
    async with client_factory(_app(catalog)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post("/admin/jobs/job-1234abcd/soft-stop")

    assert response.status_code == 303
    assert response.headers["location"].endswith("/admin")
    assert catalog.stopped == ["job-1234abcd"]


async def test_slice_detail_page_lists_failed_disclosure(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/slices/s1")

    assert response.status_code == 200
    assert "20260724000651" in response.text
    assert "상세 파싱에 실패했습니다." in response.text
