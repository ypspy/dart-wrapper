"""카탈로그 수집과 감사 추출(DART) 잡의 상호 배타 잠금."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import CatalogConflict
from app.repositories.extraction_job_repository import ExtractionJobRepository
from app.repositories.job_repository import JobRepository

DART_EXTRACTOR_ID = "audit_opinion"


async def assert_dart_idle(session: AsyncSession) -> None:
    """카탈로그 또는 감사 추출이 진행 중이면 CatalogConflict를 발생시킨다.

    날짜 LLM 잡(`resolve_dates`)은 DART를 치지 않으므로 잠금 대상이 아니다.
    """
    catalog = await JobRepository(session).find_any_active()
    if catalog is not None:
        raise CatalogConflict(
            "다른 수집 작업이 이미 진행 중입니다. "
            f"현재 작업({catalog.job_id[:8]} · {catalog.status})이 끝난 뒤에 "
            "다시 시작해 주세요."
        )

    extraction = await ExtractionJobRepository(session).find_any_active(
        extractor_id=DART_EXTRACTOR_ID
    )
    if extraction is not None:
        raise CatalogConflict(
            "감사 추출 작업이 이미 진행 중입니다. "
            f"현재 작업({extraction.job_id[:8]} · {extraction.status})이 끝난 뒤에 "
            "다시 시작해 주세요."
        )
