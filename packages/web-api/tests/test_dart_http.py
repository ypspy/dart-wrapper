"""인코딩 자동 처리와 원문 fetch 테스트."""

from __future__ import annotations

import time

import httpx
import pytest

from app.adapters.dart_http import DartHttpClient, decode_html
from app.errors import SourceFetchError

EUC_KR_HTML = '<html><head><meta charset="euc-kr"></head><body>재무상태표</body></html>'


def test_decode_html_uses_meta_charset() -> None:
    content = EUC_KR_HTML.encode("euc-kr")

    assert "재무상태표" in decode_html(content, content_type="text/html")


def test_decode_html_uses_header_charset() -> None:
    content = "<html><body>손익계산서</body></html>".encode("utf-8")

    assert "손익계산서" in decode_html(content, content_type="text/html; charset=utf-8")


def test_decode_html_falls_back_to_korean_codec() -> None:
    content = "<html><body>현금흐름표</body></html>".encode("cp949")

    assert "현금흐름표" in decode_html(content, content_type=None)


async def test_fetch_html_decodes_euc_kr_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=EUC_KR_HTML.encode("euc-kr"),
            headers={"Content-Type": "text/html"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        html = await DartHttpClient(client).fetch_html("https://dart.fss.or.kr/report/viewer.do")

    assert "재무상태표" in html


async def test_fetch_html_retries_then_raises_on_server_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500, content=b"error")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = DartHttpClient(client, max_retries=1, retry_backoff_seconds=0.0)
        with pytest.raises(SourceFetchError):
            await fetcher.fetch_html("https://dart.fss.or.kr/report/viewer.do")

    assert attempts == 2


async def test_fetch_html_attaches_status_code_on_client_error() -> None:
    """4xx는 재시도하지 않고 SourceFetchError.status_code에 HTTP 코드를 담는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=b"forbidden")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = DartHttpClient(client, max_retries=2, retry_backoff_seconds=0.0)
        with pytest.raises(SourceFetchError) as exc_info:
            await fetcher.fetch_html("https://dart.fss.or.kr/report/viewer.do")

    assert exc_info.value.status_code == 403


async def test_fetch_html_waits_min_interval_between_requests() -> None:
    """min_interval_seconds가 있으면 다음 요청 전에 그만큼 쉰다."""
    times: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        times.append(time.perf_counter())
        return httpx.Response(200, text="<html></html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = DartHttpClient(client, min_interval_seconds=0.05)
        await fetcher.fetch_html("https://dart.fss.or.kr/a")
        await fetcher.fetch_html("https://dart.fss.or.kr/b")

    assert len(times) == 2
    assert times[1] - times[0] >= 0.05
