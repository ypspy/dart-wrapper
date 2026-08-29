"""ambiguous 감사보고서일을 LLM 인덱스로 해소하는 잡."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.errors import CatalogConflict
from app.extracting.dates import (
    DateCandidate,
    parse_rcept_dt,
    parse_year_end,
    pick_audit_report_date,
)
from app.models.audit_report_fact import AuditReportFact
from app.models.extraction_job import ExtractionJob
from app.ports.date_resolver import DateResolver
from app.repositories.entry_repository import EntryRepository
from app.repositories.extraction_job_repository import ExtractionJobRepository
from app.repositories.fact_repository import FactRepository

logger = logging.getLogger(__name__)

RESOLVE_DATES_EXTRACTOR_ID = "resolve_dates"


class DateResolverService:
    """ambiguous 날짜 행만 모아 LLM에 인덱스를 묻고 성공 시 ISO를 저장한다."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        resolver: DateResolver,
        *,
        model: str = "gpt-4o-mini",
        prompt_version: str = "v1",
    ) -> None:
        self._sessionmaker = sessionmaker
        self._resolver = resolver
        self._model = model
        self._prompt_version = prompt_version

    async def start(self) -> str:
        """DART 잠금 없이 해소 잡을 등록한다. 실행은 호출측에서 run으로 돌린다."""
        async with self._sessionmaker() as session:
            jobs = ExtractionJobRepository(session)
            existing = await jobs.find_any_active(
                extractor_id=RESOLVE_DATES_EXTRACTOR_ID
            )
            if existing is not None:
                raise CatalogConflict(
                    "날짜 해소 작업이 이미 진행 중입니다. "
                    f"현재 작업({existing.job_id[:8]} · {existing.status})이 끝난 뒤에 "
                    "다시 시작해 주세요."
                )
            job_id = uuid.uuid4().hex
            await jobs.create(job_id, RESOLVE_DATES_EXTRACTOR_ID, {})
            await jobs.add_log(job_id, "info", "날짜 해소 작업을 등록했습니다.")
            await session.commit()
        return job_id

    async def run(self, job_id: str) -> None:
        """ambiguous 행을 순회하며 인덱스를 해소한다. DART는 호출하지 않는다."""
        async with self._sessionmaker() as session:
            job = await session.get(ExtractionJob, job_id)
            if job is None:
                raise ValueError(f"날짜 해소 작업을 찾을 수 없습니다: {job_id}")
            jobs = ExtractionJobRepository(session)
            await jobs.set_status(job_id, "running")
            await session.commit()

        try:
            async with self._sessionmaker() as session:
                facts = await FactRepository(session).list_ambiguous_dates()

            resolved = 0
            for fact in facts:
                if await self._resolve_one(job_id, fact):
                    resolved += 1

            async with self._sessionmaker() as session:
                jobs = ExtractionJobRepository(session)
                await jobs.set_status(job_id, "succeeded")
                await jobs.add_log(
                    job_id,
                    "info",
                    f"날짜 해소 작업을 마쳤습니다. 해소 {resolved}건.",
                )
                await session.commit()
        except Exception as exc:
            logger.exception("날짜 해소 작업이 중단되었습니다: %s", job_id)
            async with self._sessionmaker() as session:
                jobs = ExtractionJobRepository(session)
                await jobs.set_status(job_id, "failed", error_message=str(exc))
                await jobs.add_log(
                    job_id, "error", f"날짜 해소 작업이 중단되었습니다: {exc}"
                )
                await session.commit()

    async def _resolve_one(self, job_id: str, fact: AuditReportFact) -> bool:
        """한 행을 해소한다. 성공하면 True, 그대로 ambiguous면 False."""
        stored = list(fact.audit_report_date_candidates or [])
        llm_candidates = _llm_candidates(stored)
        period_end, rcept_dt = await self._window_for(fact)

        index = await self._resolver.pick_index(
            candidates=llm_candidates,
            period_end=period_end,
            rcept_dt=rcept_dt,
        )
        if index is None or index < 0 or index >= len(stored):
            return False
        iso = _candidate_iso(stored[index]) if isinstance(stored[index], dict) else None
        if not iso:
            return False

        period_date = date.fromisoformat(period_end) if period_end else None
        received_date = date.fromisoformat(rcept_dt) if rcept_dt else None
        chosen = DateCandidate(date_raw=iso, iso=iso, snippet="", index=index)
        _picked, window_status, _passing = pick_audit_report_date(
            [chosen],
            period_end=period_date,
            rcept_dt=received_date,
        )
        if window_status != "ok":
            return False

        raw_response = self._resolver.last_raw_response
        async with self._sessionmaker() as session:
            facts = FactRepository(session)
            current = await facts.get(fact.rcept_no, fact.dcm_no)
            if current is None:
                return False
            current.audit_report_date = iso
            current.audit_report_date_status = "ok"
            current.audit_report_date_source = "llm"
            current.date_resolver_model = self._model
            current.date_resolver_prompt_version = self._prompt_version
            current.date_resolver_raw_response = raw_response
            await facts.upsert(current)
            await ExtractionJobRepository(session).add_log(
                job_id,
                "info",
                f"{fact.rcept_no}/{fact.dcm_no} 감사보고서일을 LLM으로 해소했습니다.",
            )
            await session.commit()
        return True

    async def _window_for(self, fact: AuditReportFact) -> tuple[str, str]:
        """목록 year_end·rcept_dt를 ISO 문자열로 바꾼다. 없으면 빈 문자열."""
        async with self._sessionmaker() as session:
            entries = await EntryRepository(session).list_by_rcept_no(fact.rcept_no)
        sample = next((item for item in entries if item.dcm_no == fact.dcm_no), None)
        if sample is None and entries:
            sample = entries[0]
        if sample is None:
            return "", ""
        period = parse_year_end(sample.year_end)
        received = parse_rcept_dt(sample.rcept_dt)
        return (
            period.isoformat() if period else "",
            received.isoformat() if received else "",
        )


def _llm_candidates(stored: list[Any]) -> list[dict]:
    """저장 후보와 1:1로 LLM payload를 만든다. 잘못된 칸은 빈 값으로 둔다."""
    payload: list[dict] = []
    for item in stored:
        if not isinstance(item, dict):
            payload.append({"date_raw": "", "snippet": ""})
            continue
        payload.append(
            {
                "date_raw": str(
                    item.get("date_raw") or item.get("date") or item.get("iso") or ""
                ),
                "snippet": str(item.get("snippet") or ""),
            }
        )
    return payload


def _candidate_iso(item: dict) -> str | None:
    """저장 후보의 ISO(date 또는 iso 키)를 꺼낸다."""
    value = item.get("date") or item.get("iso")
    if isinstance(value, str) and value:
        return value
    return None
