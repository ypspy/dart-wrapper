"""Admin 추출 진단 검토 화면."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ADMIN_TOKEN_COOKIE, get_session, get_settings_dep
from app.config import Settings
from app.extracting.field_bundles import DART_DOCUMENT_VIEW
from app.reviewing.candidates import format_summary
from app.services.extraction_review_service import (
    REVIEW_PAGE_SIZE,
    ExtractionReviewError,
    diagnose,
    get_default_review,
    list_default_reviews,
)

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/admin", tags=["Admin UI"], include_in_schema=False)


def _has_valid_token(request: Request, settings: Settings) -> bool:
    """쿠키의 Admin 토큰이 설정과 같은지 확인한다."""
    return request.cookies.get(ADMIN_TOKEN_COOKIE) == settings.admin_token


def _to_token_page() -> RedirectResponse:
    """토큰 입력 화면으로 보낸다."""
    return RedirectResponse("/admin/token")


async def _render_reviews(
    request: Request,
    session: AsyncSession,
    *,
    page: int,
    bundle: str,
    verdict: str,
    rcept_no: str | None,
    dcm_no: str,
    key_bundle: str,
    signal: str,
    subject: str,
    notice: str = "",
    summary_lines: list[str] | None = None,
) -> HTMLResponse:
    """검토 목록과 상세를 같은 템플릿으로 그린다."""
    rows, total = await list_default_reviews(session, bundle=bundle, verdict=verdict, page=page)
    shown_page = 1 if page < 1 else page
    selected = None
    if rcept_no is not None:
        selected = await get_default_review(
            session,
            rcept_no=rcept_no,
            dcm_no=dcm_no,
            bundle=key_bundle,
            signal=signal,
            subject=subject,
        )
    viewer_url = ""
    if selected is not None:
        viewer_url = DART_DOCUMENT_VIEW.format(rcept_no=selected.rcept_no, dcm_no=selected.dcm_no)
    context = {
        "ops_section": "reviews",
        "rows": rows,
        "total": total,
        "page": shown_page,
        "page_size": REVIEW_PAGE_SIZE,
        "bundle": bundle,
        "verdict": verdict,
        "selected": selected,
        "viewer_url": viewer_url,
        "rcept_no": rcept_no,
        "dcm_no": dcm_no,
        "key_bundle": key_bundle,
        "signal": signal,
        "subject": subject,
        "notice": notice,
        "summary_lines": summary_lines or [],
    }
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request,
            "admin/partials/review_detail.html",
            context,
        )
    return templates.TemplateResponse(
        request,
        "admin/reviews.html",
        context,
    )


@router.get("/reviews", response_class=HTMLResponse, summary="추출 진단 검토")
async def reviews_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
    page: int = Query(default=1),
    bundle: str = Query(default=""),
    verdict: str = Query(default=""),
    rcept_no: str | None = Query(default=None),
    dcm_no: str = Query(default=""),
    key_bundle: str = Query(default=""),
    signal: str = Query(default=""),
    subject: str = Query(default=""),
) -> HTMLResponse:
    """기본 검토 집합을 보여 준다. 진단 요약은 이 조회에서 계산하지 않는다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()
    return await _render_reviews(
        request,
        session,
        page=page,
        bundle=bundle,
        verdict=verdict,
        rcept_no=rcept_no,
        dcm_no=dcm_no,
        key_bundle=key_bundle,
        signal=signal,
        subject=subject,
    )


@router.post("/reviews/diagnose", response_class=HTMLResponse, summary="추출 진단 실행")
async def reviews_diagnose(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
    page: int = Query(default=1),
    bundle: str = Query(default=""),
    verdict: str = Query(default=""),
    rcept_no: str | None = Query(default=None),
    dcm_no: str = Query(default=""),
    key_bundle: str = Query(default=""),
    signal: str = Query(default=""),
    subject: str = Query(default=""),
) -> HTMLResponse:
    """진단을 저장하고 요약을 페이지 위에 그린다. 새로고침은 이 POST를 다시 보낼 수 있다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()
    notice = ""
    summary_lines: list[str] = []
    try:
        summary = await diagnose(session)
        await session.commit()
        summary_lines = [format_summary(row) for row in summary]
    except ExtractionReviewError as exc:
        notice = str(exc)
    return await _render_reviews(
        request,
        session,
        page=page,
        bundle=bundle,
        verdict=verdict,
        rcept_no=rcept_no,
        dcm_no=dcm_no,
        key_bundle=key_bundle,
        signal=signal,
        subject=subject,
        notice=notice,
        summary_lines=summary_lines,
    )
