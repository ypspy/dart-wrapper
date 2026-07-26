"""Public Catalog HTML 탐색 테스트."""

from __future__ import annotations

from app.api.deps import get_catalog_query_service
from app.errors import CatalogNotFound
from app.main import create_app
from app.schemas.catalog_query import (
    DisclosureEntriesResponse,
    DisclosureListResponse,
    DisclosureSummary,
    EntrySummary,
)


DISCLOSURE_HEADERS = (
    "rcp_no",
    "corp_code",
    "corp_name",
    "report_nm",
    "report_type",
    "correction_type",
    "submitter",
    "rcept_dt",
    "year_end",
    "bsns_year",
    "entry_count",
    "disclosure_url",
)

ENTRY_HEADERS = (
    "ordinal",
    "entry_id",
    "rcept_no",
    "report_type",
    "correction_type",
    "report_nm",
    "year_end",
    "corp_code",
    "corp_name",
    "submitter",
    "rcept_dt",
    "bsns_year",
    "disclosure_url",
    "source",
    "dcm_no",
    "document_name",
    "section_name",
    "section_original_name",
    "depth",
    "is_leaf",
    "parent_ele_id",
    "ele_id",
    "offset",
    "length",
    "dtd",
    "path",
    "viewer_url",
)


class FakeCatalogQueryService:
    async def list_disclosures(self, **kwargs: object) -> DisclosureListResponse:
        return DisclosureListResponse(
            items=[
                DisclosureSummary(
                    rcp_no="20260724000650",
                    corp_code="001",
                    corp_name="테스트",
                    report_nm="감사보고서",
                    report_type="F001",
                    correction_type="최초공시",
                    submitter="제출",
                    rcept_dt="20260724",
                    year_end="(2025.12)",
                    entry_count=2,
                    disclosure_url="https://example.com/d",
                )
            ],
            next_cursor="cursor-token",
        )

    async def list_entries(self, rcp_no: str) -> DisclosureEntriesResponse:
        if rcp_no != "20260724000650":
            raise CatalogNotFound(f"공시를 찾을 수 없습니다: {rcp_no}")
        return DisclosureEntriesResponse(
            disclosure=DisclosureSummary(
                rcp_no=rcp_no,
                corp_name="테스트",
                report_type="F001",
                correction_type="최초공시",
                submitter="제출",
                rcept_dt="20260724",
                year_end="(2025.12)",
                entry_count=1,
            ),
            all_entries=[
                EntrySummary(
                    entry_id="e1",
                    rcept_no=rcp_no,
                    source="body",
                    section_name="재무상태표",
                    path=["감사보고서", "재무상태표"],
                    viewer_url="https://example.com/viewer",
                    ordinal=0,
                    is_leaf=True,
                )
            ],
        )


def _app() -> object:
    app = create_app()
    app.dependency_overrides[get_catalog_query_service] = FakeCatalogQueryService
    return app


async def test_catalog_list_shows_all_disclosure_columns(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/catalog")
    assert response.status_code == 200
    assert "page-header" in response.text
    assert "table-scroll" in response.text
    for header in DISCLOSURE_HEADERS:
        assert f"<th>{header}</th>" in response.text
    assert 'href="/catalog/20260724000650"' in response.text
    assert "다음" in response.text
    assert "cursor-token" in response.text


async def test_catalog_entries_shows_all_entry_columns(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/catalog/20260724000650")
    assert response.status_code == 200
    assert "목록으로" in response.text
    for header in ENTRY_HEADERS:
        assert f"<th>{header}</th>" in response.text
    assert "재무상태표" in response.text
    assert "감사보고서 › 재무상태표" in response.text
    assert "correction_type" in response.text


async def test_catalog_entries_not_found(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/catalog/없는번호")
    assert response.status_code == 404
    assert "없" in response.text
