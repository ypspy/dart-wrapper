"""검토보고서 추출 서비스. MockTransport와 임시 DB만 쓴다."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

import app.models  # noqa: F401
from app.adapters.dart_http import DartHttpClient
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import CatalogConflict
from app.models.disclosure import Disclosure
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.entry_repository import EntryRepository
from app.schemas.entry import EntryRecord
from research.extracting.interim_review import INTERIM_EXTRACTOR_VERSION
from research.models.corp import Corp  # noqa: F401  1층 corps를 메타에 올린다
from research.models.extraction_job import ExtractionJob
from research.repositories.extraction_job_repository import ExtractionJobRepository
from research.models.interim_review_fact import InterimReviewFact
from research.repositories.interim_fact_repository import InterimFactRepository
from research.services.extraction_service import ExtractionService
from research.services.interim_review_service import InterimReviewService

REPORT_URL = "https://example.test/interim/report"
_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "interim_review"
    / "half_separate_unmodified.html"
)
REPORT_HTML = _FIXTURE.read_text(encoding="utf-8")
_FIRST_LAYER = (
    "entries",
    "disclosures",
    "corps",
    "slice_progress",
    "catalog_jobs",
    "catalog_job_logs",
    "disclosure_attempts",
)


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def _entry(**overrides: object) -> EntryRecord:
    values: dict[str, object] = {
        "entry_id": "cover-1",
        "rcept_no": "20250814000001",
        "report_type": "A002",
        "corp_code": "00000000",
        "corp_name": "주식회사 테스트",
        "submitter": "가나다회계법인",
        "year_end": "(2025.06)",
        "rcept_dt": "2025.08.14",
        "source": "attachment",
        "dcm_no": "90001",
        "document_name": "반기검토보고서",
        "section_name": "검토보고서",
        "path": ["검토보고서"],
        "viewer_url": "https://example.test/interim/cover",
    }
    values.update(overrides)
    return EntryRecord.model_validate(values)


def _leaves() -> list[EntryRecord]:
    return [
        _entry(),
        _entry(
            entry_id="report-1",
            section_name="반기재무제표 검토보고서",
            path=["반기재무제표 검토보고서"],
            viewer_url=REPORT_URL,
        ),
        _entry(
            entry_id="parent-1",
            section_name="(첨부)반기재무제표",
            path=["(첨부)반기재무제표"],
            viewer_url="https://example.test/interim/parent",
            is_leaf=False,
        ),
        _entry(
            entry_id="notes-1",
            section_name="주석",
            path=["주석"],
            viewer_url="https://example.test/interim/notes",
        ),
    ]


def _disclosures_from_entries(records: list[EntryRecord]) -> list[Disclosure]:
    by_rcept: dict[str, Disclosure] = {}
    for record in records:
        existing = by_rcept.get(record.rcept_no)
        if existing is not None:
            existing.entry_count += 1
            continue
        by_rcept[record.rcept_no] = Disclosure(
            rcept_no=record.rcept_no,
            corp_code=record.corp_code,
            corp_name=record.corp_name,
            report_nm=record.report_nm,
            report_type=record.report_type,
            correction_type=record.correction_type,
            submitter=record.submitter,
            rcept_dt=record.rcept_dt or "",
            bsns_year=record.bsns_year,
            year_end=record.year_end,
            disclosure_url=record.disclosure_url,
            entry_count=1,
        )
    return list(by_rcept.values())


async def _seed(sessionmaker, records: list[EntryRecord]) -> None:
    async with sessionmaker() as session:
        await EntryRepository(session).upsert_many(records)
        await DisclosureRepository(session).upsert_many(_disclosures_from_entries(records))
        await session.commit()


def _client(
    handler,
    sessionmaker,
    **kwargs: object,
) -> tuple[InterimReviewService, httpx.AsyncClient, list[str]]:
    calls: list[str] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped), trust_env=False)
    retries = int(kwargs.pop("max_retries", 0))
    http = DartHttpClient(client, max_retries=retries, retry_backoff_seconds=0.0)
    service = InterimReviewService(sessionmaker, http, **kwargs)
    return service, client, calls


def _ok_handler(request: httpx.Request) -> httpx.Response:
    if str(request.url) == REPORT_URL:
        return httpx.Response(200, text=REPORT_HTML)
    return httpx.Response(404, text="없음")


async def test_extract_ok_saves_fields_and_log(sessionmaker_fixture) -> None:
    """report leaf만 요청하고 적정 검토 결론과 완료 로그를 남긴다."""
    await _seed(sessionmaker_fixture, _leaves())
    service, client, calls = _client(_ok_handler, sessionmaker_fixture)
    async with client:
        job_id = await service.start("20250801", "20250831", ["A002"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await InterimFactRepository(session).get("20250814000001", "90001")
        job = await session.get(ExtractionJob, job_id)
        logs = list(
            (
                await session.execute(
                    text("SELECT message FROM extraction_job_logs WHERE job_id = :job_id"),
                    {"job_id": job_id},
                )
            ).scalars()
        )
    assert calls == [REPORT_URL]
    assert job is not None and job.status == "succeeded"
    assert fact is not None
    assert fact.fetch_status == "ok"
    assert fact.conclusion_code == "unmodified"
    assert fact.review_kind == "half"
    assert fact.fs_scope == "separate"
    assert fact.doc_kind == "review"
    assert fact.cover_entry_id == "cover-1"
    assert fact.report_entry_id == "report-1"
    assert fact.fs_parent_entry_id == "parent-1"
    assert fact.notes_entry_id == "notes-1"
    assert fact.reviewer_resolved == "가나다회계법인"
    assert fact.review_report_date == "2025-08-14"
    assert fact.gaap_code == "k-ifrs"
    assert fact.extractor_version == INTERIM_EXTRACTOR_VERSION
    assert "20250814000001/90001 추출 완료(ok)." in logs


async def test_http_403_is_blocked(sessionmaker_fixture) -> None:
    """403은 blocked이고 재시도하지 않는다."""
    await _seed(sessionmaker_fixture, _leaves())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="거부")

    service, client, calls = _client(handler, sessionmaker_fixture)
    async with client:
        job_id = await service.start("20250801", "20250831", ["A002"], "extract")
        await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        fact = await InterimFactRepository(session).get("20250814000001", "90001")
    assert fact is not None and fact.fetch_status == "blocked"
    assert calls == [REPORT_URL]


async def test_captcha_html_is_blocked(sessionmaker_fixture) -> None:
    """200이어도 차단 본문이면 html_looks_blocked로 blocked다."""
    await _seed(sessionmaker_fixture, _leaves())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>captcha 비정상적인 접근</body></html>")

    service, client, _calls = _client(handler, sessionmaker_fixture)
    async with client:
        job_id = await service.start("20250801", "20250831", ["A002"], "extract")
        await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        fact = await InterimFactRepository(session).get("20250814000001", "90001")
    assert fact is not None and fact.fetch_status == "blocked"


async def test_server_error_retries_then_fetch_failed(sessionmaker_fixture) -> None:
    """5xx는 재시도한 뒤 fetch_failed로 남긴다."""
    await _seed(sessionmaker_fixture, _leaves())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="오류")

    service, client, calls = _client(handler, sessionmaker_fixture, max_retries=1)
    async with client:
        job_id = await service.start("20250801", "20250831", ["A002"], "extract")
        await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        fact = await InterimFactRepository(session).get("20250814000001", "90001")
        logs = list(
            (
                await session.execute(
                    text("SELECT message FROM extraction_job_logs WHERE job_id = :job_id"),
                    {"job_id": job_id},
                )
            ).scalars()
        )
    assert len(calls) == 2
    assert fact is not None and fact.fetch_status == "fetch_failed"
    assert "20250814000001/90001 추출 완료(fetch_failed)." in logs


async def test_missing_report_leaf_is_section_missing_without_request(sessionmaker_fixture) -> None:
    """report leaf가 없으면 요청 없이 section_missing이다."""
    await _seed(sessionmaker_fixture, [_entry(section_name="목차", path=["목차"])])
    service, client, calls = _client(_ok_handler, sessionmaker_fixture)
    async with client:
        job_id = await service.start("20250801", "20250831", ["A002"], "extract")
        await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        fact = await InterimFactRepository(session).get("20250814000001", "90001")
    assert calls == []
    assert fact is not None and fact.fetch_status == "section_missing"


async def test_resume_skips_ok_v1_without_request(sessionmaker_fixture) -> None:
    """resume은 ok·v1 행을 요청하지 않는다."""
    await _seed(sessionmaker_fixture, _leaves())
    async with sessionmaker_fixture() as session:
        await InterimFactRepository(session).upsert(
            InterimReviewFact(
                rcept_no="20250814000001",
                dcm_no="90001",
                source_report_type="A002",
                review_kind="half",
                fs_scope="separate",
                doc_kind="review",
                fetch_status="ok",
                conclusion_code="unmodified",
                conflicts=[],
                review_report_date_candidates=[],
                emphasis_of_matter=False,
                going_concern=False,
                extractor_version=INTERIM_EXTRACTOR_VERSION,
            )
        )
        await session.commit()
    service, client, calls = _client(_ok_handler, sessionmaker_fixture)
    async with client:
        job_id = await service.start("20250801", "20250831", ["A002"], "resume")
        await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        fact = await InterimFactRepository(session).get("20250814000001", "90001")
        job = await session.get(ExtractionJob, job_id)
    assert calls == []
    assert fact is not None and fact.conclusion_code == "unmodified"
    assert job is not None and job.status == "succeeded"


async def test_soft_stop_before_run_marks_partial(sessionmaker_fixture) -> None:
    """실행 전 중단 요청이면 문서를 가져오지 않고 partial이다."""
    await _seed(sessionmaker_fixture, _leaves())
    service, client, calls = _client(_ok_handler, sessionmaker_fixture)
    async with client:
        job_id = await service.start("20250801", "20250831", ["A002"], "extract")
        await service.request_soft_stop(job_id)
        await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        fact = await InterimFactRepository(session).get("20250814000001", "90001")
        job = await session.get(ExtractionJob, job_id)
    assert calls == []
    assert fact is None
    assert job is not None and job.status == "partial"


async def test_force_finish_unlocks_pending_job(sessionmaker_fixture) -> None:
    """강제 종료한 잡은 잠금을 풀어 다음 시작을 허용한다."""
    await _seed(sessionmaker_fixture, _leaves())
    service, client, _calls = _client(_ok_handler, sessionmaker_fixture)
    async with client:
        first = await service.start("20250801", "20250831", ["A002"], "extract")
        await service.force_finish(first)
        second = await service.start("20250801", "20250831", ["A002"], "extract")
    assert first != second
    async with sessionmaker_fixture() as session:
        job = await session.get(ExtractionJob, first)
    assert job is not None and job.status == "partial"


async def test_block_streak_waits_then_fails(
    sessionmaker_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """차단이 5번 이어지면 60초를 기다린 뒤 실패하고 다음 문서는 요청하지 않는다."""
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("research.services.interim_review_service.asyncio.sleep", fake_sleep)
    records: list[EntryRecord] = []
    for index in range(1, 7):
        rcept = f"2025081400000{index}"
        dcm = f"9000{index}"
        url = f"https://example.test/interim/report-{index}"
        records.append(
            _entry(
                entry_id=f"cover-{index}",
                rcept_no=rcept,
                dcm_no=dcm,
                section_name="검토보고서",
            )
        )
        records.append(
            _entry(
                entry_id=f"report-{index}",
                rcept_no=rcept,
                dcm_no=dcm,
                section_name="반기재무제표 검토보고서",
                viewer_url=url,
            )
        )
    await _seed(sessionmaker_fixture, records)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="거부")

    service, client, calls = _client(
        handler,
        sessionmaker_fixture,
        block_streak_threshold=5,
        block_wait_seconds=60.0,
    )
    async with client:
        job_id = await service.start("20250801", "20250831", ["A002"], "extract")
        await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        sixth = await InterimFactRepository(session).get("20250814000006", "90006")
        job = await session.get(ExtractionJob, job_id)
    assert len(calls) == 5
    assert sixth is None
    assert 60.0 in slept
    assert job is not None and job.status == "failed"
    assert job.error_message is not None and "차단" in job.error_message


async def test_run_does_not_write_first_layer(tmp_path: Path) -> None:
    """실행 전후 1층 행 수와 sqlite_master는 같다."""
    path = tmp_path / "catalog.db"
    engine = create_db_engine(f"sqlite+aiosqlite:///{path}")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)
    await _seed(sessionmaker, _leaves())
    before = _snapshot(path)
    service, client, _calls = _client(_ok_handler, sessionmaker)
    async with client:
        job_id = await service.start("20250801", "20250831", ["A002"], "extract")
        await service.run_job(job_id)
    await engine.dispose()
    after = _snapshot(path)
    assert after["master"] == before["master"]
    assert after["counts"] == before["counts"]
    connection = sqlite3.connect(path)
    try:
        stored = connection.execute("SELECT fetch_status FROM interim_review_facts").fetchone()
    finally:
        connection.close()
    assert stored == ("ok",)


async def test_start_rejects_when_table_is_missing(sessionmaker_fixture) -> None:
    """테이블이 없으면 시작을 거절한다."""
    async with sessionmaker_fixture() as session:
        await session.execute(text("DROP TABLE interim_review_facts"))
        await session.commit()
    service, client, _calls = _client(_ok_handler, sessionmaker_fixture)
    async with client:
        with pytest.raises(CatalogConflict, match="interim_review_facts 테이블이 없습니다"):
            await service.start("20250801", "20250831", ["A002"], "extract")


async def test_audit_job_blocks_interim_start(sessionmaker_fixture) -> None:
    """감사 추출이 돌고 있으면 검토 추출을 시작하지 않는다."""
    async with sessionmaker_fixture() as session:
        jobs = ExtractionJobRepository(session)
        await jobs.create("audit-run", "audit_opinion", {}, mode="extract")
        await jobs.set_status("audit-run", "running")
        await session.commit()
    service, client, _calls = _client(_ok_handler, sessionmaker_fixture)
    async with client:
        with pytest.raises(CatalogConflict, match="감사 추출 작업이 이미 진행 중"):
            await service.start("20250801", "20250831", ["A002"], "extract")


async def test_interim_job_blocks_audit_start(sessionmaker_fixture) -> None:
    """검토 추출이 돌고 있으면 감사 추출을 시작하지 않는다."""
    async with sessionmaker_fixture() as session:
        jobs = ExtractionJobRepository(session)
        await jobs.create("interim-run", "interim_review", {}, mode="extract")
        await jobs.set_status("interim-run", "running")
        await session.commit()
    service, client, _calls = _client(_ok_handler, sessionmaker_fixture)
    audit = ExtractionService(sessionmaker_fixture, service._http)
    async with client:
        with pytest.raises(CatalogConflict, match="검토보고서 추출 작업이 이미 진행 중"):
            await audit.start("20250801", "20250831", ["A002"], "extract")


def _snapshot(path: Path) -> dict[str, object]:
    connection = sqlite3.connect(path)
    try:
        master = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in _FIRST_LAYER
        }
    finally:
        connection.close()
    return {
        "master": master,
        "counts": counts,
        "sha": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
