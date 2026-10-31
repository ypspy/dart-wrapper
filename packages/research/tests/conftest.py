"""연구 테스트 공용 픽스처. 로컬 앱에 연구 라우터를 붙인 테스트용 앱을 만든다."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

# 연구 UI 테스트가 web-api의 가짜 서비스(test_admin_ui)를 재사용한다.
_WEB_API_TESTS = Path(__file__).resolve().parents[2] / "web-api" / "tests"
if str(_WEB_API_TESTS) not in sys.path:
    sys.path.append(str(_WEB_API_TESTS))

from research.local_app import create_app  # noqa: E402

__all__ = ["create_app"]


@pytest.fixture
def client_factory():
    """lifespan을 실행하지 않고 앱에 직접 요청하는 httpx 클라이언트를 만든다."""

    def _factory(app: FastAPI) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    return _factory
