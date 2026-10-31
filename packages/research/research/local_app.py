"""연구 패키지 로컬 진입점.

실행: ``uvicorn research.local_app:app --port 8010``
골드 검수는 ``/admin/gold`` 이다. 날짜 LLM은 켜지 않는다.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from app.local import create_local_app
from research.api.admin import corps as admin_corps
from research.api.admin import extract as admin_extract
from research.api.admin import extract_ui as admin_extract_ui
from research.api.admin import gold as admin_gold
from research.api.admin import reviews as admin_reviews
from research.api.facts import ui as facts_ui
from research.api.v1 import facts as audit_facts


def create_app() -> FastAPI:
    """로컬 앱에 연구 라우터와 골드 검수 화면을 붙인다."""
    os.environ.setdefault("DART_LLM_ENABLED", "false")
    app = create_local_app()
    app.include_router(admin_corps.router)
    app.include_router(admin_extract.router)
    app.include_router(admin_extract_ui.router)
    app.include_router(admin_reviews.router)
    app.include_router(admin_gold.router)
    app.include_router(facts_ui.router)
    app.include_router(audit_facts.router)
    app.include_router(audit_facts.list_router)
    return app


os.environ.setdefault("DART_LLM_ENABLED", "false")
app = create_app()
