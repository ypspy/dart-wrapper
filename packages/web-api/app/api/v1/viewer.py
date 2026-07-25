"""Public Viewer 라우터. 조회 시점에 원문을 정제해 반환한다."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_viewer_service
from app.schemas.viewer import DisclosureContent, SectionContent
from app.services.viewer_service import ViewerService

router = APIRouter(prefix="/api/v1/viewer", tags=["Viewer"])


@router.get("/{rcp_no}", response_model=DisclosureContent, summary="공시 전체 원문 조회")
async def read_disclosure(
    rcp_no: str,
    service: ViewerService = Depends(get_viewer_service),
) -> DisclosureContent:
    """접수번호에 속한 모든 leaf 섹션의 정제 결과를 반환한다(종합 분석용)."""
    return await service.get_disclosure(rcp_no)


@router.get(
    "/{rcp_no}/sections/{entry_id}",
    response_model=SectionContent,
    summary="특정 leaf 섹션 원문 조회",
)
async def read_section(
    rcp_no: str,
    entry_id: str,
    service: ViewerService = Depends(get_viewer_service),
) -> SectionContent:
    """특정 leaf 섹션 하나의 정제 결과를 반환한다(빠른 단건 조회)."""
    return await service.get_section(rcp_no, entry_id)
