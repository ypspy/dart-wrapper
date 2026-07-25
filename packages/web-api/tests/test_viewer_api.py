"""Viewer 라우터 테스트. 서비스는 가짜 구현으로 대체한다."""

from __future__ import annotations

import pytest

from app.api.deps import get_viewer_service
from app.errors import CatalogNotFound, SourceFetchError
from app.main import create_app
from app.schemas.viewer import DisclosureContent, DisclosureMeta, SectionContent, TableData

SECTION = SectionContent(
    entry_id="e_1",
    source="body",
    dcm_no="11495035",
    ele_id="5",
    path=["감사보고서", "재무상태표"],
    document_name="감사보고서",
    section_name="재무상태표",
    text="재무상태표\n자산총계 1,000",
    tables=[TableData(headers=["과목", "당기"], rows=[["자산총계", "1,000"]])],
)


class FakeViewerService:
    """정상 응답을 돌려주는 가짜 서비스."""

    async def get_disclosure(self, rcept_no: str) -> DisclosureContent:
        return DisclosureContent(
            rcp_no=rcept_no,
            meta=DisclosureMeta(corp_name="제이에스어소시에이츠", report_nm="감사보고서"),
            sections=[SECTION],
        )

    async def get_section(self, rcept_no: str, entry_id: str) -> SectionContent:
        return SECTION


class RaisingViewerService:
    """지정한 예외를 던지는 가짜 서비스."""

    def __init__(self, exception: Exception) -> None:
        self._exception = exception

    async def get_disclosure(self, rcept_no: str) -> DisclosureContent:
        raise self._exception

    async def get_section(self, rcept_no: str, entry_id: str) -> SectionContent:
        raise self._exception


def _app_with(service: object):
    app = create_app()
    app.dependency_overrides[get_viewer_service] = lambda: service
    return app


async def test_get_disclosure_returns_all_sections(client_factory) -> None:
    async with client_factory(_app_with(FakeViewerService())) as client:
        response = await client.get("/api/v1/viewer/20260724000650")

    body = response.json()
    assert response.status_code == 200
    assert body["rcp_no"] == "20260724000650"
    assert body["meta"]["corp_name"] == "제이에스어소시에이츠"
    assert body["sections"][0]["tables"][0]["headers"] == ["과목", "당기"]


async def test_get_section_returns_single_section(client_factory) -> None:
    async with client_factory(_app_with(FakeViewerService())) as client:
        response = await client.get("/api/v1/viewer/20260724000650/sections/e_1")

    assert response.status_code == 200
    assert response.json()["entry_id"] == "e_1"


@pytest.mark.parametrize(
    ("exception", "expected_status"),
    [
        (CatalogNotFound("카탈로그에 없습니다."), 404),
        (SourceFetchError("원문을 가져오지 못했습니다."), 502),
    ],
)
async def test_viewer_errors_map_to_status(
    client_factory, exception: Exception, expected_status: int
) -> None:
    async with client_factory(_app_with(RaisingViewerService(exception))) as client:
        response = await client.get("/api/v1/viewer/20260724000650")

    assert response.status_code == expected_status
    assert response.json() == {"detail": str(exception)}
