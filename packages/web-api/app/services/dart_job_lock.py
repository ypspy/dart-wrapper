"""카탈로그 수집(DART) 잡의 중복 실행 잠금."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import CatalogConflict
from app.repositories.job_repository import JobRepository


async def assert_dart_idle(session: AsyncSession) -> None:
    """다른 카탈로그 수집이 진행 중이면 CatalogConflict를 발생시킨다.

    감사 추출 잡은 연구 패키지에서 관리하므로 이 잠금은 보지 않는다.
    """
    catalog = await JobRepository(session).find_any_active()
    if catalog is not None:
        raise CatalogConflict(
            "다른 수집 작업이 이미 진행 중입니다. "
            f"현재 작업({catalog.job_id[:8]} · {catalog.status})이 끝난 뒤에 "
            "다시 시작해 주세요."
        )
