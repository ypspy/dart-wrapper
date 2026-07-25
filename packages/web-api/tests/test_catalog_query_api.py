"""Public 카탈로그 조회 라우터 테스트. 서비스는 가짜 구현으로 대체한다."""

from __future__ import annotations

from app.api.deps import get_catalog_query_service
from app.errors import BadRequest, CatalogNotFound
from app.main import create_app
from app.schemas.catalog_query import (
    DisclosureEntriesResponse,
    DisclosureListResponse,
    DisclosureSummary,
    EntrySummary,
)


class FakeCatalogQueryService:
    """고정 응답을 돌려주는 가짜 조회 서비스."""

    async def list_disclosures(self, **kwargs: object) -> DisclosureListResponse:
        return DisclosureListResponse(
            items=[
                DisclosureSummary(
                    rcp_no="20260724000650",
                    corp_name="테스트",
                    report_type="F001",
                    rcept_dt="20260724",
                    entry_count=2,
                )
            ],
            next_cursor=None,
        )

    async def get_disclosure(self, rcp_no: str) -> DisclosureSummary:
        if rcp_no != "20260724000650":
            raise CatalogNotFound(f"공시를 찾을 수 없습니다: {rcp_no}")
        return DisclosureSummary(
            rcp_no=rcp_no,
            corp_name="테스트",
            report_type="F001",
            rcept_dt="20260724",
            entry_count=2,
        )

    async def list_entries(self, rcp_no: str) -> DisclosureEntriesResponse:
        if rcp_no != "20260724000650":
            raise CatalogNotFound(f"공시를 찾을 수 없습니다: {rcp_no}")
        entry = EntrySummary(
            entry_id="e1",
            source="body",
            section_name="재무상태표",
            path=["감사보고서", "재무상태표"],
        )
        return DisclosureEntriesResponse(
            rcp_no=rcp_no,
            report_type="F001",
            primary_entries=[entry],
            all_entries=[entry],
        )


class BadCursorService(FakeCatalogQueryService):
    async def list_disclosures(self, **kwargs: object) -> DisclosureListResponse:
        raise BadRequest("커서 값이 올바르지 않습니다.")


def _app_with(service: object):
    app = create_app()
    app.dependency_overrides[get_catalog_query_service] = lambda: service
    return app


async def test_list_disclosures_ok(client_factory) -> None:
    async with client_factory(_app_with(FakeCatalogQueryService())) as client:
        response = await client.get("/api/v1/catalog/disclosures")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["rcp_no"] == "20260724000650"
    assert body["next_cursor"] is None


async def test_list_disclosures_limit_validation(client_factory) -> None:
    async with client_factory(_app_with(FakeCatalogQueryService())) as client:
        response = await client.get("/api/v1/catalog/disclosures", params={"limit": 101})

    assert response.status_code == 422


async def test_list_disclosures_bad_cursor(client_factory) -> None:
    async with client_factory(_app_with(BadCursorService())) as client:
        response = await client.get("/api/v1/catalog/disclosures", params={"cursor": "bad"})

    assert response.status_code == 400


async def test_get_disclosure_not_found(client_factory) -> None:
    async with client_factory(_app_with(FakeCatalogQueryService())) as client:
        response = await client.get("/api/v1/catalog/disclosures/없는번호")

    assert response.status_code == 404


async def test_list_entries_includes_primary_and_entry_id(client_factory) -> None:
    async with client_factory(_app_with(FakeCatalogQueryService())) as client:
        response = await client.get("/api/v1/catalog/disclosures/20260724000650/entries")

    assert response.status_code == 200
    body = response.json()
    assert body["primary_entries"][0]["entry_id"] == "e1"
    assert body["all_entries"][0]["entry_id"] == "e1"
