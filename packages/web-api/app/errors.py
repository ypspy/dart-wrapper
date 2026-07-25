"""서비스 도메인 예외와 HTTP 변환 핸들러."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DartWrapperError(Exception):
    """서비스 공통 예외의 기반 클래스."""


class CatalogNotFound(DartWrapperError):
    """요청한 공시/섹션이 카탈로그에 없을 때 발생한다."""


class CatalogConflict(DartWrapperError):
    """이미 진행 중인 수집이 있어 새 작업을 시작할 수 없을 때 발생한다."""


class BadRequest(DartWrapperError):
    """잘못된 요청 파라미터(예: 손상된 cursor)일 때 발생한다."""


class Unauthorized(DartWrapperError):
    """Admin 인증이 없거나 토큰이 일치하지 않을 때 발생한다."""


class SourceFetchError(DartWrapperError):
    """DART 원문을 가져오지 못했을 때 발생한다."""


class ParseError(DartWrapperError):
    """원문 HTML 정제·표 파싱에 실패했을 때 발생한다."""


_STATUS_BY_EXCEPTION: dict[type[DartWrapperError], int] = {
    CatalogNotFound: 404,
    CatalogConflict: 409,
    BadRequest: 400,
    Unauthorized: 401,
    SourceFetchError: 502,
    ParseError: 502,
}


def register_exception_handlers(app: FastAPI) -> None:
    """도메인 예외를 한국어 메시지 JSON 응답으로 변환하는 핸들러를 등록한다."""

    async def handle(request: Request, exc: DartWrapperError) -> JSONResponse:
        status_code = _STATUS_BY_EXCEPTION.get(type(exc), 500)
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    for exception_type in _STATUS_BY_EXCEPTION:
        app.add_exception_handler(exception_type, handle)
