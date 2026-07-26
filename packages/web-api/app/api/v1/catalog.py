"""Public 카탈로그 목록·단건·목차 라우터."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_catalog_query_service
from app.schemas.catalog_query import (
    DisclosureEntriesResponse,
    DisclosureListResponse,
    DisclosureSummary,
)
from app.services.catalog_query_service import CatalogQueryService

router = APIRouter(prefix="/api/v1/catalog", tags=["Catalog"])


@router.get("/disclosures", response_model=DisclosureListResponse, summary="공시 목록 조회")
async def list_disclosures(
    corp_code: str | None = None,
    corp_name: str | None = None,
    report_nm: str | None = None,
    report_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    service: CatalogQueryService = Depends(get_catalog_query_service),
) -> DisclosureListResponse:
    """회사·보고서·기간으로 공시 목록을 조회한다(keyset cursor)."""
    return await service.list_disclosures(
        corp_code=corp_code,
        corp_name=corp_name,
        report_nm=report_nm,
        report_type=report_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/disclosures/{rcp_no}",
    response_model=DisclosureSummary,
    summary="공시 단건 조회",
)
async def get_disclosure(
    rcp_no: str,
    service: CatalogQueryService = Depends(get_catalog_query_service),
) -> DisclosureSummary:
    """접수번호에 해당하는 공시 요약을 반환한다."""
    return await service.get_disclosure(rcp_no)


@router.get(
    "/disclosures/{rcp_no}/entries",
    response_model=DisclosureEntriesResponse,
    summary="공시 leaf 목차 조회",
)
async def list_disclosure_entries(
    rcp_no: str,
    service: CatalogQueryService = Depends(get_catalog_query_service),
) -> DisclosureEntriesResponse:
    """공시 메타와 leaf 목록을 반환한다. 본문 파싱은 하지 않는다."""
    return await service.list_entries(rcp_no)
