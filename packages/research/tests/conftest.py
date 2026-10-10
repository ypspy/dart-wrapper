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

from app.local import create_local_app
from research.api.admin import corps as admin_corps
from research.api.admin import extract as admin_extract
from research.api.admin import extract_ui as admin_extract_ui
from research.api.admin import reviews as admin_reviews
from research.api.facts import ui as facts_ui
from research.api.v1 import facts as audit_facts


def create_app() -> FastAPI:
    """로컬 앱에 연구 라우터(추출·검토·업종·Facts)를 붙여 돌려준다."""
    app = create_local_app()
    app.include_router(admin_corps.router)
    app.include_router(admin_extract.router)
    app.include_router(admin_extract_ui.router)
    app.include_router(admin_reviews.router)
    app.include_router(facts_ui.router)
    app.include_router(audit_facts.router)
    app.include_router(audit_facts.list_router)
    return app


@pytest.fixture
def client_factory():
    """lifespan을 실행하지 않고 앱에 직접 요청하는 httpx 클라이언트를 만든다."""

    def _factory(app: FastAPI) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    return _factory
