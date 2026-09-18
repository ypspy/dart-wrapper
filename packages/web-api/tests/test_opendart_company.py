"""OpenDART company.json 클라이언트 테스트. 실호출 없음."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.adapters.opendart_company import (
    COMPANY_URL,
    OpenDartCompanyClient,
    OpenDartHttpError,
)


def _client(handler: object, max_retries: int = 0) -> OpenDartCompanyClient:
    transport = httpx.MockTransport(handler)
    return OpenDartCompanyClient(
        httpx.AsyncClient(transport=transport),
        timeout_seconds=1.0,
        max_retries=max_retries,
        max_per_minute=0,
    )


async def test_fetch_maps_flat_000() -> None:
    """최상위 status=000과 개황 필드를 매핑한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(COMPANY_URL)
        assert request.url.params["crtfc_key"] == "key"
        assert request.url.params["corp_code"] == "00126380"
        return httpx.Response(
            200,
            json={
                "status": "000",
                "message": "정상",
                "corp_name": "삼성전자",
                "stock_name": "삼성전자",
                "stock_code": "005930",
                "corp_cls": "Y",
                "bizr_no": "1248100998",
                "acc_mt": "12",
                "induty_code": "264",
            },
        )

    overview = await _client(handler).fetch("00126380", "key")
    assert overview.status == "000"
    assert overview.corp_name == "삼성전자"
    assert overview.stock_code == "005930"
    assert overview.induty_code == "264"


async def test_fetch_reads_status_under_result() -> None:
    """result.status도 읽는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"result": {"status": "013", "message": "조회된 데이타가 없습니다."}},
        )

    overview = await _client(handler).fetch("00000000", "key")
    assert overview.status == "013"
    assert overview.induty_code is None


async def test_fetch_blank_stock_code_becomes_none() -> None:
    """비상장 빈 종목코드는 None이다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "000", "message": "정상", "stock_code": "  ", "induty_code": ""},
        )

    overview = await _client(handler).fetch("001", "key")
    assert overview.stock_code is None
    assert overview.induty_code is None


async def test_fetch_retries_then_raises() -> None:
    """HTTP 오류는 재시도 후 OpenDartHttpError."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(500, text="err")

    with pytest.raises(OpenDartHttpError):
        await _client(handler, max_retries=1).fetch("00126380", "key")
    assert attempts["n"] == 2


async def test_fetch_http_error_does_not_expose_api_key() -> None:
    """HTTP 오류 메시지에 OpenDART 인증키를 포함하지 않는다."""
    api_key = "secret-opendart-api-key"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="err")

    with pytest.raises(OpenDartHttpError) as caught:
        await _client(handler).fetch("00126380", api_key)

    assert api_key not in str(caught.value)
    assert "500" in str(caught.value)


async def test_fetch_mixed_payload_top_status_result_induty_code() -> None:
    """status는 최상위, induty_code는 result에만 있을 때 둘 다 읽는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "000",
                "message": "정상",
                "corp_name": "삼성전자",
                "result": {"induty_code": "264"},
            },
        )

    overview = await _client(handler).fetch("00126380", "key")
    assert overview.status == "000"
    assert overview.message == "정상"
    assert overview.corp_name == "삼성전자"
    assert overview.induty_code == "264"


async def test_fetch_json_array_does_not_retry() -> None:
    """200이지만 JSON 배열이면 재시도 없이 OpenDartHttpError."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(200, json=[{"status": "000"}])

    with pytest.raises(OpenDartHttpError, match="객체가 아닙니다"):
        await _client(handler, max_retries=2).fetch("00126380", "key")
    assert attempts["n"] == 1


async def test_fetch_spaces_starts_under_per_minute_cap() -> None:
    """HTTP 시작은 분당 한도 바로 아래 간격으로 직렬화한다."""
    started: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        started.append(time.monotonic())
        return httpx.Response(200, json={"status": "000", "message": "정상"})

    transport = httpx.MockTransport(handler)
    client = OpenDartCompanyClient(
        httpx.AsyncClient(transport=transport),
        timeout_seconds=1.0,
        max_retries=0,
        max_per_minute=1200,
    )
    await asyncio.gather(*(client.fetch(f"00{i}", "key") for i in range(3)))
    started.sort()
    interval = 60.0 / 1200
    assert started[1] - started[0] >= interval * 0.9
    assert started[2] - started[0] >= interval * 1.8
