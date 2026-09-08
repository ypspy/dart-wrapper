"""OpenDART 기업개황으로 회사 업종을 채우는 잡."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.opendart_company import (
    CompanyOverview,
    OpenDartCompanyClient,
    OpenDartHttpError,
)
from app.errors import BadRequest, CatalogConflict, CatalogNotFound
from app.ksic import KsicEntry, names_for
from app.models.corp import Corp
from app.models.extraction_job import ExtractionJob, ExtractionJobLog
from app.repositories.corp_repository import CorpRepository
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.extraction_job_repository import ExtractionJobRepository

logger = logging.getLogger(__name__)

CORP_INDUSTRY_EXTRACTOR_ID = "corp_industry"
FILL_MISSING_MODE = "fill_missing"
FATAL_OPENDART_STATUSES = frozenset({"010", "011", "012", "020", "800", "901"})
STALE_RUNNING_SECONDS = 3600


@dataclass(frozen=True)
class CorpIndustrySummary:
    """회사 업종 채움 현황."""

    disclosure_corps: int
    ok_count: int
    remaining_count: int


class OpenDartFatalError(Exception):
    """잡 전체를 중단해야 하는 OpenDART 상태."""


def _is_stale_running(job: ExtractionJob) -> bool:
    """오래된 running 잡인지 확인한다."""
    if job.status != "running":
        return False
    stamp = job.started_at or job.created_at
    if stamp is None:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() >= STALE_RUNNING_SECONDS


def _fatal_message(status: str) -> str:
    """치명 상태를 운영자가 이해할 수 있는 메시지로 바꾼다."""
    if status == "020":
        return (
            "OpenDART 요청 한도를 넘었습니다. 이미 채운 회사는 유지됩니다. "
            "다음 날 다시 실행해 주세요."
        )
    if status == "800":
        return "OpenDART가 점검 중입니다. 이미 채운 회사는 유지됩니다."
    return "OpenDART 인증키 또는 접근 권한을 확인해 주세요."


class CorpIndustryService:
    """공시에 등장한 회사 중 업종이 비어 있는 회사만 채운다."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        client: OpenDartCompanyClient,
        ksic: dict[str, KsicEntry],
        *,
        api_key: str,
        concurrency: int = 2,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._client = client
        self._ksic = ksic
        self._api_key = api_key
        self._concurrency = max(1, concurrency)
        self._stop_requested: set[str] = set()
        self._start_lock = asyncio.Lock()

    async def start(self) -> str:
        """동일 추출기의 활성 잡만 확인하고 새 잡을 등록한다."""
        async with self._start_lock:
            if not self._api_key.strip():
                raise BadRequest(
                    "OpenDART 인증키가 없습니다. OPENDART_API_KEY를 설정한 뒤 다시 시작해 주세요."
                )

            async with self._sessionmaker() as session:
                jobs = ExtractionJobRepository(session)
                active = await jobs.find_any_active(extractor_id=CORP_INDUSTRY_EXTRACTOR_ID)
                if active is not None:
                    if _is_stale_running(active):
                        await jobs.set_status(
                            active.job_id,
                            "failed",
                            error_message="작업이 오래 실행 중이라 중단된 것으로 보고 종료했습니다.",
                        )
                        await jobs.add_log(
                            active.job_id,
                            "warning",
                            "오래된 회사 업종 작업을 종료하고 잠금을 해제했습니다.",
                        )
                    else:
                        raise CatalogConflict(
                            "회사 업종 작업이 이미 진행 중입니다. "
                            f"현재 작업({active.job_id[:8]} · {active.status})이 끝난 뒤에 "
                            "다시 시작해 주세요."
                        )

                job_id = uuid.uuid4().hex
                await jobs.create(
                    job_id,
                    CORP_INDUSTRY_EXTRACTOR_ID,
                    {},
                    mode=FILL_MISSING_MODE,
                )
                await jobs.add_log(job_id, "info", "회사 업종 작업을 등록했습니다.")
                await session.commit()
            return job_id

    async def run_job(self, job_id: str) -> None:
        """누락 회사를 제한된 동시성으로 조회하고 회사별로 커밋한다."""
        async with self._sessionmaker() as session:
            job = await session.get(ExtractionJob, job_id)
            if job is None:
                raise ValueError(f"회사 업종 작업을 찾을 수 없습니다: {job_id}")
            await ExtractionJobRepository(session).set_status(job_id, "running")
            await session.commit()

        try:
            async with self._sessionmaker() as session:
                disclosure_codes = await DisclosureRepository(session).list_distinct_corp_codes()
                ok_codes = await CorpRepository(session).list_ok_codes()
            missing = sorted(set(disclosure_codes) - ok_codes)
            params = {"target_count": len(missing), "processed_count": 0}
            await self._update_params(job_id, params)

            if not missing:
                await self._finish(job_id, "succeeded", "채울 회사가 없습니다.")
                return

            queue = deque(missing)
            claim_lock = asyncio.Lock()
            progress_lock = asyncio.Lock()
            semaphore = asyncio.Semaphore(self._concurrency)
            fatal_event = asyncio.Event()
            processed = 0

            async def save_result(corp: Corp, message: str, level: str = "info") -> None:
                nonlocal processed
                async with progress_lock:
                    processed += 1
                    params["processed_count"] = processed
                    async with self._sessionmaker() as session:
                        await CorpRepository(session).upsert(corp)
                        jobs = ExtractionJobRepository(session)
                        await jobs.update_params(job_id, dict(params))
                        await jobs.add_log(job_id, level, message)
                        await session.commit()

            async def process_one(corp_code: str) -> None:
                try:
                    async with semaphore:
                        overview = await self._client.fetch(corp_code, self._api_key)
                except OpenDartHttpError as exc:
                    await save_result(
                        self._http_error_corp(corp_code),
                        f"{corp_code} api_error · {exc}",
                        "warning",
                    )
                    return

                if overview.status in FATAL_OPENDART_STATUSES:
                    raise OpenDartFatalError(_fatal_message(overview.status))

                fetch_status = (
                    "ok"
                    if overview.status == "000"
                    else "not_found" if overview.status == "013" else "api_error"
                )
                corp = self._overview_corp(corp_code, overview, fetch_status)
                if fetch_status == "ok":
                    class_name = corp.induty_name_class or ""
                    message = f"{corp_code} ok · {overview.induty_code or ''} {class_name}"
                    level = "info"
                else:
                    message = (
                        f"{corp_code} {fetch_status} · {overview.status} " f"{overview.message}"
                    )
                    level = "warning"
                await save_result(corp, message, level)

            async def worker() -> Exception | None:
                while True:
                    async with claim_lock:
                        if fatal_event.is_set() or job_id in self._stop_requested or not queue:
                            return None
                        corp_code = queue.popleft()
                    try:
                        await process_one(corp_code)
                    except OpenDartFatalError as exc:
                        fatal_event.set()
                        return exc
                    except Exception as exc:
                        fatal_event.set()
                        return exc

            worker_count = min(self._concurrency, len(missing))
            results = await asyncio.gather(
                *(worker() for _ in range(worker_count)),
                return_exceptions=True,
            )
            failure = next(
                (result for result in results if isinstance(result, Exception)),
                None,
            )
            if failure is not None:
                raise failure
            if job_id in self._stop_requested:
                await self._finish(
                    job_id,
                    "partial",
                    f"중단 요청으로 회사 업종 작업을 멈췄습니다. 처리 {processed}건.",
                    level="warning",
                )
                return
            await self._finish(
                job_id,
                "succeeded",
                f"회사 업종 작업을 마쳤습니다. 처리 {processed}건.",
            )
        except OpenDartFatalError as exc:
            await self._fail(job_id, str(exc))
        except Exception as exc:
            logger.exception("회사 업종 작업이 중단되었습니다: %s", job_id)
            await self._fail(job_id, str(exc))

    async def request_soft_stop(self, job_id: str) -> None:
        """새 회사를 시작하지 않고 진행 중인 회사까지만 처리한다."""
        self._stop_requested.add(job_id)
        async with self._sessionmaker() as session:
            job = await session.get(ExtractionJob, job_id)
            if job is None:
                raise CatalogNotFound("회사 업종 작업을 찾을 수 없습니다.")
            await ExtractionJobRepository(session).add_log(
                job_id,
                "warning",
                "중단 요청을 받았습니다. 진행 중인 회사까지만 처리합니다.",
            )
            await session.commit()

    async def force_finish(self, job_id: str) -> None:
        """활성 잡을 즉시 부분 종료한다."""
        self._stop_requested.add(job_id)
        async with self._sessionmaker() as session:
            job = await session.get(ExtractionJob, job_id)
            if job is None:
                raise CatalogNotFound("회사 업종 작업을 찾을 수 없습니다.")
            if job.status not in {"pending", "running"}:
                return
            jobs = ExtractionJobRepository(session)
            message = "운영자가 작업을 강제 종료했습니다."
            await jobs.set_status(job_id, "partial", error_message=message)
            await jobs.add_log(job_id, "warning", message)
            await session.commit()

    async def get_status(self, job_id: str | None) -> tuple[ExtractionJob, list[ExtractionJobLog]]:
        """지정 잡 또는 가장 최근 회사 업종 잡과 최신순 로그를 반환한다."""
        async with self._sessionmaker() as session:
            jobs = ExtractionJobRepository(session)
            job = (
                await jobs.find_latest(CORP_INDUSTRY_EXTRACTOR_ID)
                if job_id is None
                else await jobs.get(job_id)
            )
            if job is None:
                raise CatalogNotFound("회사 업종 작업을 찾을 수 없습니다.")
            logs = await jobs.recent_logs(job.job_id)
        return job, logs

    async def summarize(self) -> CorpIndustrySummary:
        """공시 회사 수와 완료·잔여 수를 집계한다."""
        async with self._sessionmaker() as session:
            disclosure_corps = await DisclosureRepository(
                session
            ).count_distinct_corp_codes()
            ok_count = await CorpRepository(session).count_ok()
        return CorpIndustrySummary(
            disclosure_corps=disclosure_corps,
            ok_count=ok_count,
            remaining_count=max(0, disclosure_corps - ok_count),
        )

    def _overview_corp(
        self,
        corp_code: str,
        overview: CompanyOverview,
        fetch_status: str,
    ) -> Corp:
        """기업개황과 KSIC 이름으로 저장 행을 만든다."""
        names = names_for(overview.induty_code, self._ksic)
        return Corp(
            corp_code=corp_code,
            corp_name=overview.corp_name,
            stock_name=overview.stock_name,
            stock_code=overview.stock_code,
            corp_cls=overview.corp_cls,
            bizr_no=overview.bizr_no,
            acc_mt=overview.acc_mt,
            induty_code=overview.induty_code,
            induty_name_div=names.induty_name_div,
            induty_name_group=names.induty_name_group,
            induty_name_class=names.induty_name_class,
            induty_name_subclass=names.induty_name_subclass,
            induty_name_item=names.induty_name_item,
            fetch_status=fetch_status,
            opendart_status=overview.status,
            fetched_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _http_error_corp(corp_code: str) -> Corp:
        """HTTP 실패를 재시도 가능한 회사 행으로 만든다."""
        return Corp(
            corp_code=corp_code,
            fetch_status="api_error",
            fetched_at=datetime.now(timezone.utc),
        )

    async def _update_params(self, job_id: str, params: dict[str, int]) -> None:
        """잡 진행 파라미터를 짧은 세션으로 저장한다."""
        async with self._sessionmaker() as session:
            await ExtractionJobRepository(session).update_params(job_id, params)
            await session.commit()

    async def _finish(
        self,
        job_id: str,
        status: str,
        message: str,
        *,
        level: str = "info",
    ) -> None:
        """잡을 종료 상태로 바꾸고 로그를 남긴다."""
        async with self._sessionmaker() as session:
            jobs = ExtractionJobRepository(session)
            await jobs.set_status(job_id, status)
            await jobs.add_log(job_id, level, message)
            await session.commit()
        self._stop_requested.discard(job_id)

    async def _fail(self, job_id: str, message: str) -> None:
        """잡 실패 상태와 사용자 메시지를 저장한다."""
        async with self._sessionmaker() as session:
            jobs = ExtractionJobRepository(session)
            await jobs.set_status(job_id, "failed", error_message=message)
            await jobs.add_log(
                job_id,
                "error",
                f"회사 업종 작업이 중단되었습니다: {message}",
            )
            await session.commit()
        self._stop_requested.discard(job_id)
