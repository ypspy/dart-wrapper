"""테스트 공통 픽스처."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI


@pytest.fixture
def client_factory():
    """lifespan을 실행하지 않고 앱에 직접 요청하는 httpx 클라이언트를 만든다."""

    def _factory(app: FastAPI) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    return _factory
