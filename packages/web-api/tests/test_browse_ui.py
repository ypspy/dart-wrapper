"""Browse UI 테스트. 서비스는 가짜 구현으로 대체한다."""

from __future__ import annotations

from app.api.deps import (
    get_catalog_query_service,
    get_entry_repository,
    get_viewer_service,
)
from app.errors import CatalogNotFound, SourceFetchError
from app.main import create_app
from app.schemas.catalog_query import (
    DisclosureEntriesResponse,
    DisclosureListResponse,
    DisclosureSummary,
    EntrySummary,
)
from app.schemas.viewer import SectionContent


class FakeCatalogQueryService:
    """Browse용 고정 응답 조회 서비스."""

    async def list_disclosures(self, **kwargs: object) -> DisclosureListResponse:
        return DisclosureListResponse(
            items=[
                DisclosureSummary(
                    rcp_no="20260724000650",
                    corp_name="테스트회사",
                    report_nm="감사보고서",
                    report_type="F001",
                    rcept_dt="20260724",
                    entry_count=2,
                    disclosure_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260724000650",
                )
            ],
            next_cursor="eyJuZXh0IjoxfQ",
        )

    async def get_disclosure(self, rcp_no: str) -> DisclosureSummary:
        if rcp_no != "20260724000650":
            raise CatalogNotFound(f"공시를 찾을 수 없습니다: {rcp_no}")
        return DisclosureSummary(
            rcp_no=rcp_no,
            corp_name="테스트회사",
            report_nm="감사보고서",
            report_type="F001",
            rcept_dt="20260724",
            entry_count=2,
            disclosure_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260724000650",
        )

    async def list_entries(self, rcp_no: str) -> DisclosureEntriesResponse:
        if rcp_no != "20260724000650":
            raise CatalogNotFound(f"공시를 찾을 수 없습니다: {rcp_no}")
        primary = EntrySummary(
            entry_id="e_1",
            source="body",
            section_name="재무상태표",
            document_name="감사보고서",
            path=["감사보고서", "재무상태표"],
        )
        other = EntrySummary(
            entry_id="e_2",
            source="attachment",
            section_name="첨부문서",
            document_name="첨부",
            path=["첨부", "첨부문서"],
        )
        return DisclosureEntriesResponse(
            rcp_no=rcp_no,
            report_type="F001",
            primary_entries=[primary],
            all_entries=[primary, other],
        )


class EmptyPrimaryService(FakeCatalogQueryService):
    async def list_entries(self, rcp_no: str) -> DisclosureEntriesResponse:
        other = EntrySummary(
            entry_id="e_2",
            source="attachment",
            section_name="첨부문서",
            document_name="첨부",
            path=["첨부", "첨부문서"],
        )
        return DisclosureEntriesResponse(
            rcp_no=rcp_no,
            report_type="ZZZZ",
            primary_entries=[],
            all_entries=[other],
        )


SECTION = SectionContent(
    entry_id="e_1",
    source="body",
    dcm_no="11495035",
    ele_id="5",
    path=["감사보고서", "재무상태표"],
    document_name="감사보고서",
    section_name="재무상태표",
    blocks=[
        {"type": "heading", "level": 2, "text": "재무상태표"},
        {"type": "paragraph", "text": "자산총계는 다음과 같다."},
        {"type": "table", "headers": ["과목", "당기"], "rows": [["자산총계", "1,000"]]},
    ],
    text="재무상태표\n자산총계는 다음과 같다.",
)


class FakeViewerService:
    async def get_section(self, rcept_no: str, entry_id: str) -> SectionContent:
        return SECTION


class RaisingViewerService:
    def __init__(self, exception: Exception) -> None:
        self._exception = exception

    async def get_section(self, rcept_no: str, entry_id: str) -> SectionContent:
        raise self._exception


class FakeEntryRepository:
    async def get_by_entry_id(self, entry_id: str):
        return None


def _app(catalog: object | None = None, viewer: object | None = None):
    app = create_app()
    app.dependency_overrides[get_catalog_query_service] = lambda: (
        catalog or FakeCatalogQueryService()
    )
    if viewer is not None:
        app.dependency_overrides[get_viewer_service] = lambda: viewer
    app.dependency_overrides[get_entry_repository] = lambda: FakeEntryRepository()
    return app


async def test_browse_list_page_renders(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/browse")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "공시" in response.text


async def test_browse_css_is_served(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/static/browse.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]


async def test_browse_list_shows_disclosure_rows(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/browse")
    assert "테스트회사" in response.text
    assert "감사보고서" in response.text


async def test_browse_list_has_next_cursor_link(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/browse")
    assert "cursor=eyJuZXh0IjoxfQ" in response.text
    assert "다음" in response.text


class BadCursorCatalog(FakeCatalogQueryService):
    def __init__(self) -> None:
        self._raised = False

    async def list_disclosures(self, **kwargs: object) -> DisclosureListResponse:
        # 첫 호출(cursor 있음)만 실패시키고, 되돌린 첫 페이지 호출은 정상 응답한다.
        from app.errors import BadRequest

        if not self._raised and kwargs.get("cursor"):
            self._raised = True
            raise BadRequest("커서 값이 올바르지 않습니다.")
        return await super().list_disclosures(**kwargs)


async def test_browse_list_bad_cursor_shows_message(client_factory) -> None:
    async with client_factory(_app(catalog=BadCursorCatalog())) as client:
        response = await client.get("/browse", params={"cursor": "!!!"})
    assert response.status_code == 200
    assert "커서" in response.text
    assert "테스트회사" in response.text


async def test_browse_disclosure_shows_primary_toc(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/browse/20260724000650")
    assert response.status_code == 200
    assert "browse-layout" in response.text
    assert "재무상태표" in response.text
    assert "바로가기" in response.text
    assert "toc-tree" in response.text
    assert "toc-header" in response.text
    assert "감사보고서" in response.text
    assert "전체 보기" not in response.text
    assert "--toc-indent" not in response.text
    # 첫 primary 섹션을 자동 로드하도록 패널이 hx-trigger="load"를 건다.
    assert 'hx-trigger="load"' in response.text
    assert "/browse/20260724000650/sections/e_1" in response.text


async def test_browse_disclosure_empty_primary_opens_all(client_factory) -> None:
    async with client_factory(_app(catalog=EmptyPrimaryService())) as client:
        response = await client.get("/browse/20260724000650")
    assert response.status_code == 200
    assert "첨부문서" in response.text
    assert "바로가기" not in response.text
    assert "첨부" in response.text
    assert "본문" not in response.text  # EmptyPrimary는 attachment만
    assert "전체 보기" not in response.text


async def test_browse_disclosure_shows_shortcut_and_tree(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/browse/20260724000650")
    assert response.status_code == 200
    assert "바로가기" in response.text
    assert "toc-tree" in response.text
    assert "toc-branch" in response.text or "toc-section" in response.text
    assert "본문" in response.text
    assert "첨부" in response.text
    assert "--toc-indent" not in response.text
    assert "전체 보기" not in response.text


async def test_browse_disclosure_not_found(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/browse/99999999999999")
    assert response.status_code == 404
    assert "없" in response.text


async def test_browse_section_partial_renders_blocks(client_factory) -> None:
    async with client_factory(_app(viewer=FakeViewerService())) as client:
        response = await client.get(
            "/browse/20260724000650/sections/e_1",
            headers={"HX-Request": "true"},
        )
    assert response.status_code == 200
    assert "재무상태표" in response.text
    assert "자산총계는 다음과 같다." in response.text
    assert "block-table" in response.text
    # partial이므로 전체 문서 뼈대는 포함하지 않는다.
    assert "<html" not in response.text.lower()


async def test_browse_section_error_panel(client_factory) -> None:
    viewer = RaisingViewerService(SourceFetchError("원문을 가져오지 못했습니다."))
    async with client_factory(_app(viewer=viewer)) as client:
        response = await client.get(
            "/browse/20260724000650/sections/e_1",
            headers={"HX-Request": "true"},
        )
    assert response.status_code == 200
    assert "section-error" in response.text
    assert "다시" in response.text


async def test_browse_section_not_found(client_factory) -> None:
    viewer = RaisingViewerService(CatalogNotFound("섹션을 찾을 수 없습니다."))
    async with client_factory(_app(viewer=viewer)) as client:
        response = await client.get("/browse/20260724000650/sections/missing")
    assert response.status_code == 404
    assert "없" in response.text
