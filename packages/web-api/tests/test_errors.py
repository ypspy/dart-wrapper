"""도메인 예외가 HTTP 응답으로 변환되는지 검증한다."""

from __future__ import annotations

import pytest

from app.errors import CatalogConflict, CatalogNotFound, ParseError, SourceFetchError
from app.main import create_app


@pytest.mark.parametrize(
    ("exception", "expected_status", "expected_detail"),
    [
        (CatalogNotFound("카탈로그에 없습니다."), 404, "카탈로그에 없습니다."),
        (
            CatalogConflict("다른 수집 작업이 이미 진행 중입니다."),
            409,
            "다른 수집 작업이 이미 진행 중입니다.",
        ),
        (SourceFetchError("원문을 가져오지 못했습니다."), 502, "원문을 가져오지 못했습니다."),
        (ParseError("본문 파싱에 실패했습니다."), 502, "본문 파싱에 실패했습니다."),
    ],
)
async def test_domain_exception_maps_to_http_response(
    client_factory, exception: Exception, expected_status: int, expected_detail: str
) -> None:
    app = create_app()

    @app.get("/_test/raise")
    async def _raise() -> None:
        raise exception

    async with client_factory(app) as client:
        response = await client.get("/_test/raise")

    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}


async def test_bad_request_returns_400(client_factory) -> None:
    from fastapi import FastAPI

    from app.errors import BadRequest, register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise BadRequest("커서 값이 올바르지 않습니다.")

    async with client_factory(app) as client:
        response = await client.get("/boom")

    assert response.status_code == 400
    assert response.json()["detail"] == "커서 값이 올바르지 않습니다."


async def test_unauthorized_returns_401(client_factory) -> None:
    from fastapi import FastAPI

    from app.errors import Unauthorized, register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/secret")
    async def secret() -> None:
        raise Unauthorized("Admin 토큰이 필요합니다.")

    async with client_factory(app) as client:
        response = await client.get("/secret")

    assert response.status_code == 401
    assert response.json()["detail"] == "Admin 토큰이 필요합니다."
