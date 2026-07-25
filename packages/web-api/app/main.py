"""FastAPI 앱 생성 및 라우터 등록."""

from __future__ import annotations

from fastapi import FastAPI

from app.errors import register_exception_handlers


def create_app() -> FastAPI:
    """DART 공시 파이프라인 API 앱을 생성한다."""
    app = FastAPI(
        title="DART 공시 파이프라인 API",
        description="Admin 카탈로그 수집과 Public Viewer(Lazy Retrieval)를 제공합니다.",
        version="0.1.0",
    )
    register_exception_handlers(app)

    @app.get("/health", tags=["시스템"])
    async def health() -> dict[str, str]:
        """서비스 생존 여부를 반환한다."""
        return {"status": "ok"}

    return app


app = create_app()
