"""Admin 화면 스모크 테스트. 렌더링과 인증 흐름만 확인한다."""

from __future__ import annotations

from datetime import datetime, timezone

from app.api.deps import get_slice_query_service
from app.main import create_app
from app.schemas.catalog import (
    DisclosureAttemptItem,
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


def _app():
    app = create_app()
    app.dependency_overrides[get_slice_query_service] = lambda: FakeSliceQueryService()
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


async def test_slice_detail_page_lists_failed_disclosure(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/slices/s1")

    assert response.status_code == 200
    assert "20260724000651" in response.text
    assert "상세 파싱에 실패했습니다." in response.text
