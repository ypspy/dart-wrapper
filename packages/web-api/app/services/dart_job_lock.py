"""카탈로그 수집과 감사 추출(DART) 잡의 상호 배타 잠금."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import CatalogConflict
from app.models.extraction_job import ExtractionJob
from app.repositories.extraction_job_repository import ExtractionJobRepository
from app.repositories.job_repository import JobRepository

DART_EXTRACTOR_ID = "audit_opinion"
# 이 시간 이상 running이면 워커가 죽은 것으로 보고 잠금을 해제한다.
STALE_RUNNING_SECONDS = 3600


def _is_stale_running(job: ExtractionJob) -> bool:
    """running 추출 잡이 오래되었는지 본다."""
    if job.status != "running":
        return False
    stamp = job.started_at or job.created_at
    if stamp is None:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - stamp
    return age.total_seconds() >= STALE_RUNNING_SECONDS


async def assert_dart_idle(session: AsyncSession) -> None:
    """카탈로그 또는 감사 추출이 진행 중이면 CatalogConflict를 발생시킨다.

    날짜 LLM 잡(`resolve_dates`)은 DART를 치지 않으므로 잠금 대상이 아니다.
    오래된 running 추출 잡은 워커가 멈춘 것으로 보고 실패 처리한 뒤 잠금을 푼다.
    """
    catalog = await JobRepository(session).find_any_active()
    if catalog is not None:
        raise CatalogConflict(
            "다른 수집 작업이 이미 진행 중입니다. "
            f"현재 작업({catalog.job_id[:8]} · {catalog.status})이 끝난 뒤에 "
            "다시 시작해 주세요."
        )

    jobs = ExtractionJobRepository(session)
    extraction = await jobs.find_any_active(extractor_id=DART_EXTRACTOR_ID)
    if extraction is None:
        return
    if _is_stale_running(extraction):
        await jobs.set_status(
            extraction.job_id,
            "failed",
            error_message="작업이 오래 실행 중이라 중단된 것으로 보고 종료했습니다.",
        )
        await jobs.add_log(
            extraction.job_id,
            "warning",
            "오래된 추출 작업을 종료하고 잠금을 해제했습니다.",
        )
        return
    raise CatalogConflict(
        "감사 추출 작업이 이미 진행 중입니다. "
        f"현재 작업({extraction.job_id[:8]} · {extraction.status})이 끝난 뒤에 "
        "다시 시작해 주세요."
    )
