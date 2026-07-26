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
    YearSummaryItem,
    YearSummaryResponse,
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


YEAR_SUMMARY = YearSummaryResponse(
    items=[
        YearSummaryItem(year=2024, level="complete"),
        YearSummaryItem(year=2025, level="incomplete"),
        YearSummaryItem(year=2026, level="missing"),
    ],
    selected_year=2025,
)


class FakeSliceQueryService:
    def __init__(self) -> None:
        self.heatmap_calls: list[tuple[int | None, str | None]] = []
        self.list_calls: list[dict[str, object]] = []

    async def list_slices(self, **kwargs) -> SliceListResponse:
        self.list_calls.append(kwargs)
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

    async def heatmap(
        self,
        today=None,
        *,
        year: int | None = None,
        report_type: str | None = None,
    ) -> HeatmapResponse:
        self.heatmap_calls.append((year, report_type))
        return HEATMAP

    async def year_summary(self, **kwargs) -> YearSummaryResponse:
        return YEAR_SUMMARY


JOB_STATUS = JobStatusResponse(
    job_id="job-1234abcd",
    status="running",
    mode="collect",
    params={"report_type": "F001", "start_date": "20260701", "end_date": "20260726"},
    total_entries=10,
    saved_entries=4,
    started_at=datetime(2026, 7, 26, 1, 0, tzinfo=timezone.utc),
    stop_requested=False,
    logs=[
        JobLogItem(
            level="error",
            message="상세 파싱에 실패했습니다.",
            created_at=datetime(2026, 7, 26, 1, 3, tzinfo=timezone.utc),
        ),
        JobLogItem(
            level="warn",
            message="재시도합니다.",
            created_at=datetime(2026, 7, 26, 1, 2, tzinfo=timezone.utc),
        ),
        JobLogItem(
            level="info",
            message="수집을 시작합니다.",
            created_at=datetime(2026, 7, 26, 1, 0, tzinfo=timezone.utc),
        ),
    ],
)


class FakeCatalogService:
    """최신 작업 현황과 중단 요청만 흉내 낸다."""

    def __init__(self, job: JobStatusResponse | None = JOB_STATUS) -> None:
        self.job = job
        self.stopped: list[str] = []
        self.force_finished: list[str] = []

    async def get_latest_status(self) -> JobStatusResponse | None:
        return self.job

    async def get_status(self, job_id: str) -> JobStatusResponse:
        assert self.job is not None
        return self.job

    async def request_soft_stop(self, job_id: str) -> None:
        self.stopped.append(job_id)

    async def force_finish(self, job_id: str) -> None:
        self.force_finished.append(job_id)


def _app(
    catalog: FakeCatalogService | None = None,
    slices: FakeSliceQueryService | None = None,
):
    app = create_app()
    query_service = slices or FakeSliceQueryService()
    app.dependency_overrides[get_slice_query_service] = lambda: query_service
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


async def test_admin_index_defaults_to_latest_job_report_type(client_factory) -> None:
    job = JOB_STATUS.model_copy(
        update={
            "params": {
                "report_type": "A001",
                "start_date": "20260701",
                "end_date": "20260701",
            }
        }
    )
    async with client_factory(_app(FakeCatalogService(job=job))) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin")

    body = response.text
    assert response.status_code == 200
    assert 'href="/admin?report_type=A001"' in body
    assert "연도 요약 · A001 사업보고서" in body
    assert 'class="report-type-chip is-selected"' in body


async def test_admin_index_renders_two_column_ops_console(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin")

    assert response.status_code == 200
    body = response.text
    assert 'class="ops-grid"' in body
    assert "연도 요약" in body
    assert "2025년 일별 완전성" in body
    assert "작업 현황" in body
    assert "수집 시작" in body
    assert "재시도" in body
    assert "이어하기" in body
    assert 'class="report-type-chip' in body
    assert ">A001<" in body
    assert "사업보고서" in body
    assert "연결감사보고서" in body
    assert 'href="/admin?report_type=A002' in body


async def test_admin_index_disables_start_when_job_busy(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin")

    assert response.status_code == 200
    body = response.text
    assert "진행 중인 작업이 있으면 새 수집은 시작할 수 없습니다" in body
    assert "다른 작업이 진행 중이라 새 수집을 시작할 수 없습니다" in body
    assert "disabled>수집 시작</button>" in body or 'disabled">수집 시작</button>' in body
    assert (
        "disabled>미완료 이어하기</button>" in body or 'disabled">미완료 이어하기</button>' in body
    )


async def test_collect_form_partial_keeps_submitted_end_date(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get(
            "/admin/collect-form",
            params={
                "report_type": "A003",
                "start_date": "20260101",
                "end_date": "20260331",
                "expand_form": 1,
            },
        )

    body = response.text
    assert response.status_code == 200
    assert 'value="20260101"' in body
    assert 'value="20260331"' in body
    assert 'value="A003"' in body or "A003 · 분기보고서" in body
    assert 'hx-include="find form"' not in body


async def test_admin_index_collect_form_poll_includes_current_fields(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin")

    assert 'hx-get="/admin/collect-form"' in response.text
    assert 'hx-include="find form"' in response.text
    assert "start_date={{ start_date }}" not in response.text


async def test_admin_index_collect_form_is_collapsed_by_default(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin")

    assert 'class="collect-form' in response.text
    assert "<details class=\"collect-form\" open>" not in response.text
    assert ' open' not in response.text.split("collect-form", 1)[1].split(">", 1)[0]


async def test_admin_index_renders_heatmap_links_and_legend(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin")

    assert response.status_code == 200
    assert "F001" in response.text
    assert 'href="/admin/slices/s1"' in response.text
    assert (
        'href="/admin?report_type=F001&amp;year=2025&amp;start_date=20260725'
        '&amp;end_date=20260725&amp;expand_form=1"' in response.text
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


async def test_admin_query_prefills_and_expands_collect_form(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get(
            "/admin",
            params={
                "report_type": "A001",
                "year": 2024,
                "start_date": "20260102",
                "end_date": "20260102",
                "expand_form": 1,
            },
        )

    body = response.text
    assert "<details" in body and "collect-form" in body and " open" in body
    assert 'value="20260102"' in body
    assert '<option value="A001" selected>' in body
    assert 'name="start_date" value="20260102"' in body
    assert 'name="end_date" value="20260102"' in body
    assert "2024년 일별 완전성" in body


async def test_year_bar_partial_marks_selected_year(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/year-bar", params={"year": 2024})

    assert response.status_code == 200
    body = response.text
    assert "year-bar-complete" in body
    assert "year-bar-incomplete" in body
    assert 'href="/admin?report_type=F001&amp;year=2024"' in body
    assert body.count("is-selected") == 1


async def test_year_bar_partial_falls_back_to_default_year(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/year-bar", params={"year": 1990})

    assert response.status_code == 200
    selected = response.text.split("is-selected")[0]
    assert selected.rstrip().endswith("year-bar-incomplete")


async def test_heatmap_partial_uses_requested_year(client_factory) -> None:
    query_service = FakeSliceQueryService()
    async with client_factory(_app(slices=query_service)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/heatmap", params={"year": 2024, "report_type": "A001"})

    assert response.status_code == 200
    assert query_service.heatmap_calls == [(2024, "A001")]


async def test_heatmap_cells_link_to_collect_form_with_year(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/heatmap", params={"year": 2025})

    assert 'href="/admin/slices/s1"' in response.text
    assert (
        'href="/admin?report_type=F001&amp;year=2025&amp;start_date=20260725'
        '&amp;end_date=20260725&amp;expand_form=1"' in response.text
    )


async def test_slices_summary_partial_lists_problem_slices(client_factory) -> None:
    query_service = FakeSliceQueryService()
    async with client_factory(_app(slices=query_service)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/slices-summary", params={"year": 2024})

    assert response.status_code == 200
    body = response.text
    assert "07-24 · blocked" in body
    assert "전체 보기" in body
    assert query_service.list_calls[-1]["start_date"] == "20240101"
    assert query_service.list_calls[-1]["end_date"] == "20241231"


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
    assert "실행 중" in body
    assert "4 / 10" in body
    assert "20260701 ~ 20260726" in body
    assert "소프트 스톱" in body
    assert "강제 종료" in body
    assert "상세 파싱에 실패했습니다." in body


async def test_job_status_partial_renders_idle_without_job(client_factory) -> None:
    async with client_factory(_app(FakeCatalogService(job=None))) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/job-status")

    assert response.status_code == 200
    assert "대기 중" in response.text
    assert "소프트 스톱" not in response.text


async def test_job_logs_partial_includes_info_while_running(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/job-logs")

    assert response.status_code == 200
    body = response.text
    assert "재시도합니다." in body
    assert "상세 파싱에 실패했습니다." in body
    assert "수집을 시작합니다." in body
    assert "실행 중" in body


async def test_job_logs_partial_hides_info_when_idle(client_factory) -> None:
    idle = JOB_STATUS.model_copy(update={"status": "succeeded"})
    async with client_factory(_app(FakeCatalogService(job=idle))) as client:
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
    assert response.headers["location"].endswith("/admin?report_type=F001")
    assert catalog.stopped == ["job-1234abcd"]


async def test_force_finish_form_finishes_and_redirects(client_factory) -> None:
    catalog = FakeCatalogService()
    async with client_factory(_app(catalog)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post("/admin/jobs/job-1234abcd/force-finish")

    assert response.status_code == 303
    assert response.headers["location"].endswith("/admin?report_type=F001")
    assert catalog.force_finished == ["job-1234abcd"]


async def test_slice_detail_page_lists_failed_disclosure(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/slices/s1")

    assert response.status_code == 200
    assert "20260724000651" in response.text
    assert "상세 파싱에 실패했습니다." in response.text
    assert 'href="/admin?report_type=F001"' in response.text
