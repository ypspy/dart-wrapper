"""AuditReportFact·ExtractionJob 리포지토리 영속화 테스트."""

from __future__ import annotations

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.extracting.constants import EXTRACTOR_VERSION
from app.models.audit_report_fact import AuditReportFact
from app.models.catalog_job import CatalogJobLog
from app.models.extraction_job import ExtractionJob, ExtractionJobLog
from app.repositories.extraction_job_repository import ExtractionJobRepository
from app.repositories.fact_repository import FactRepository

# 스펙 §4.1 컬럼. 테스트가 이 목록을 기준으로 누락을 잡는다.
SPEC_FACT_COLUMNS = (
    "rcept_no",
    "dcm_no",
    "source_report_type",
    "fs_scope",
    "cover_entry_id",
    "opinion_entry_id",
    "activity_entry_id",
    "a001_opinion_entry_id",
    "a001_cover_entry_id",
    "auditor",
    "auditor_body",
    "auditor_a001",
    "auditor_listing",
    "auditor_status",
    "auditor_resolved",
    "auditor_source",
    "opinion_raw",
    "opinion_code",
    "opinion_status",
    "opinion_resolved",
    "opinion_source",
    "audit_report_date_raw",
    "audit_report_date_candidates",
    "audit_report_date",
    "audit_report_date_status",
    "audit_report_date_source",
    "audit_report_date_override",
    "gaap_raw",
    "gaap_code",
    "gaap_status",
    "gaap_resolved",
    "gaap_source",
    "current_period_raw",
    "current_period_status",
    "current_period_resolved",
    "current_period_source",
    "fetch_status",
    "conflicts",
    "extracted_at",
    "extractor_version",
    "date_resolver_model",
    "date_resolver_prompt_version",
    "date_resolver_raw_response",
)


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def _make_fact(**overrides: object) -> AuditReportFact:
    """스펙 컬럼을 채운 샘플 행을 만든다."""
    values: dict[str, object] = {
        "rcept_no": "20260331000001",
        "dcm_no": "111",
        "source_report_type": "F001",
        "fs_scope": "separate",
        "cover_entry_id": "c1",
        "opinion_entry_id": "o1",
        "activity_entry_id": "a1",
        "a001_opinion_entry_id": None,
        "a001_cover_entry_id": None,
        "auditor": "삼일회계법인",
        "auditor_body": "삼일회계법인",
        "auditor_a001": None,
        "auditor_listing": "삼일회계법인",
        "auditor_status": "ok",
        "auditor_resolved": "삼일회계법인",
        "auditor_source": "cover",
        "opinion_raw": "boilerplate_unqualified",
        "opinion_code": "unqualified",
        "opinion_status": "ok",
        "opinion_resolved": "unqualified",
        "opinion_source": "letter",
        "audit_report_date_raw": "2026년3월20일",
        "audit_report_date_candidates": [
            {"date": "2026-03-20", "snippet": "감사보고서일은 2026년 3월 20일입니다."},
        ],
        "audit_report_date": "2026-03-20",
        "audit_report_date_status": "ok",
        "audit_report_date_source": "letter",
        "audit_report_date_override": None,
        "gaap_raw": "한국채택국제회계기준",
        "gaap_code": "k-ifrs",
        "gaap_status": "ok",
        "gaap_resolved": "k-ifrs",
        "gaap_source": "letter",
        "current_period_raw": "제57기",
        "current_period_status": "ok",
        "current_period_resolved": "제57기",
        "current_period_source": "cover",
        "fetch_status": "ok",
        "conflicts": [{"field": "auditor", "left": "표지", "right": "본문"}],
        "extractor_version": EXTRACTOR_VERSION,
        "date_resolver_model": None,
        "date_resolver_prompt_version": None,
        "date_resolver_raw_response": None,
    }
    values.update(overrides)
    return AuditReportFact(**values)


def test_extractor_version_constant() -> None:
    """추출기 버전 상수는 계획에 적힌 값을 쓴다."""
    assert EXTRACTOR_VERSION == "audit_opinion.v1"


def test_audit_report_fact_has_all_spec_columns() -> None:
    """스펙 §4.1에 나온 컬럼이 모두 매핑되어 있다."""
    names = set(AuditReportFact.__table__.columns.keys())
    missing = [name for name in SPEC_FACT_COLUMNS if name not in names]
    assert missing == []


def test_extraction_job_log_columns_match_catalog() -> None:
    """ExtractionJobLog 컬럼 이름은 CatalogJobLog와 같다."""
    catalog = set(CatalogJobLog.__table__.columns.keys())
    extraction = set(ExtractionJobLog.__table__.columns.keys())
    assert extraction == catalog


async def test_upsert_and_get_roundtrip(sessionmaker_fixture) -> None:
    """복합 PK로 upsert한 행을 조회하면 JSON 포함 값이 그대로 남는다."""
    fact = _make_fact()
    async with sessionmaker_fixture() as session:
        await FactRepository(session).upsert(fact)
        await session.commit()

    async with sessionmaker_fixture() as session:
        loaded = await FactRepository(session).get("20260331000001", "111")

    assert loaded is not None
    assert loaded.source_report_type == "F001"
    assert loaded.fs_scope == "separate"
    assert loaded.cover_entry_id == "c1"
    assert loaded.opinion_entry_id == "o1"
    assert loaded.activity_entry_id == "a1"
    assert loaded.auditor_resolved == "삼일회계법인"
    assert loaded.opinion_code == "unqualified"
    assert loaded.gaap_code == "k-ifrs"
    assert loaded.current_period_resolved == "제57기"
    assert loaded.audit_report_date == "2026-03-20"
    assert loaded.audit_report_date_candidates == [
        {"date": "2026-03-20", "snippet": "감사보고서일은 2026년 3월 20일입니다."},
    ]
    assert loaded.conflicts == [{"field": "auditor", "left": "표지", "right": "본문"}]
    assert loaded.extractor_version == "audit_opinion.v1"
    assert loaded.extracted_at is not None
    assert loaded.fetch_status == "ok"


async def test_get_returns_none_when_missing(sessionmaker_fixture) -> None:
    """없는 복합 키는 None이다."""
    async with sessionmaker_fixture() as session:
        loaded = await FactRepository(session).get("missing", "0")
    assert loaded is None


async def test_upsert_replaces_existing_row(sessionmaker_fixture) -> None:
    """같은 rcept_no·dcm_no로 다시 저장하면 필드가 덮인다."""
    async with sessionmaker_fixture() as session:
        repo = FactRepository(session)
        await repo.upsert(_make_fact(opinion_code="unqualified", fetch_status="ok"))
        await session.commit()

    async with sessionmaker_fixture() as session:
        repo = FactRepository(session)
        await repo.upsert(
            _make_fact(
                opinion_code="qualified",
                opinion_resolved="qualified",
                fetch_status="ok",
                conflicts=[],
                audit_report_date_candidates=[],
            )
        )
        await session.commit()

    async with sessionmaker_fixture() as session:
        loaded = await FactRepository(session).get("20260331000001", "111")

    assert loaded is not None
    assert loaded.opinion_code == "qualified"
    assert loaded.conflicts == []


async def test_list_by_rcept_no_returns_same_filing(sessionmaker_fixture) -> None:
    """접수번호로 조회하면 그 접수의 문서 행만 나온다."""
    async with sessionmaker_fixture() as session:
        repo = FactRepository(session)
        await repo.upsert(_make_fact(dcm_no="111"))
        await repo.upsert(_make_fact(dcm_no="222", fs_scope="consolidated"))
        await repo.upsert(_make_fact(rcept_no="20260331000002", dcm_no="111"))
        await session.commit()

    async with sessionmaker_fixture() as session:
        rows = await FactRepository(session).list_by_rcept_no("20260331000001")

    dcm_nos = sorted(row.dcm_no for row in rows)
    assert dcm_nos == ["111", "222"]


async def test_list_by_rcept_nos_batches_filings(sessionmaker_fixture) -> None:
    """여러 접수번호를 한 번에 조회한다."""
    async with sessionmaker_fixture() as session:
        repo = FactRepository(session)
        await repo.upsert(_make_fact(dcm_no="111"))
        await repo.upsert(_make_fact(rcept_no="20260331000002", dcm_no="222"))
        await repo.upsert(_make_fact(rcept_no="20260331000003", dcm_no="333"))
        await session.commit()

    async with sessionmaker_fixture() as session:
        rows = await FactRepository(session).list_by_rcept_nos(
            ["20260331000001", "20260331000003"]
        )

    assert sorted(row.rcept_no for row in rows) == [
        "20260331000001",
        "20260331000003",
    ]


async def test_list_ambiguous_dates(sessionmaker_fixture) -> None:
    """감사보고서일 상태가 ambiguous인 행만 반환한다."""
    async with sessionmaker_fixture() as session:
        repo = FactRepository(session)
        await repo.upsert(_make_fact(dcm_no="ok-date", audit_report_date_status="ok"))
        await repo.upsert(
            _make_fact(
                dcm_no="amb-1",
                audit_report_date=None,
                audit_report_date_status="ambiguous",
            )
        )
        await repo.upsert(
            _make_fact(
                rcept_no="20260331000002",
                dcm_no="amb-2",
                audit_report_date=None,
                audit_report_date_status="ambiguous",
            )
        )
        await session.commit()

    async with sessionmaker_fixture() as session:
        rows = await FactRepository(session).list_ambiguous_dates()

    keys = sorted((row.rcept_no, row.dcm_no) for row in rows)
    assert keys == [
        ("20260331000001", "amb-1"),
        ("20260331000002", "amb-2"),
    ]


async def test_extraction_job_create_and_find_any_active(sessionmaker_fixture) -> None:
    """생성한 잡은 pending이며 활성 조회에 잡힌다."""
    async with sessionmaker_fixture() as session:
        repo = ExtractionJobRepository(session)
        job = await repo.create(
            "ext-1",
            "audit_opinion",
            {"start_date": "20260101", "end_date": "20260331"},
            mode="extract",
        )
        await session.commit()

    assert job.status == "pending"
    assert job.extractor_id == "audit_opinion"
    assert job.mode == "extract"
    assert job.params == {"start_date": "20260101", "end_date": "20260331"}

    async with sessionmaker_fixture() as session:
        active = await ExtractionJobRepository(session).find_any_active()

    assert active is not None and active.job_id == "ext-1"


async def test_extraction_job_set_status_and_logs(sessionmaker_fixture) -> None:
    """상태 전이와 로그가 카탈로그 잡과 같이 남는다."""
    async with sessionmaker_fixture() as session:
        repo = ExtractionJobRepository(session)
        await repo.create("ext-2", "resolve_dates", {}, mode="resume")
        await repo.set_status("ext-2", "running")
        await repo.add_log("ext-2", "info", "날짜 해소를 시작합니다.")
        await repo.set_status("ext-2", "succeeded")
        await session.commit()

    async with sessionmaker_fixture() as session:
        repo = ExtractionJobRepository(session)
        job = await session.get(ExtractionJob, "ext-2")
        active = await repo.find_any_active()
        logs = await repo.recent_logs("ext-2")

    assert job is not None
    assert job.status == "succeeded"
    assert job.extractor_id == "resolve_dates"
    assert job.mode == "resume"
    assert job.started_at is not None and job.finished_at is not None
    assert active is None
    assert [log.message for log in logs] == ["날짜 해소를 시작합니다."]


async def test_extraction_job_set_status_failed_records_message(
    sessionmaker_fixture,
) -> None:
    """실패 상태와 오류 메시지를 기록한다."""
    async with sessionmaker_fixture() as session:
        repo = ExtractionJobRepository(session)
        await repo.create("ext-3", "audit_opinion", {}, mode="reparse")
        await repo.set_status("ext-3", "failed", error_message="DART 차단으로 중단했습니다.")
        await session.commit()

    async with sessionmaker_fixture() as session:
        job = await session.get(ExtractionJob, "ext-3")
        active = await ExtractionJobRepository(session).find_any_active()

    assert job is not None
    assert job.status == "failed"
    assert job.error_message == "DART 차단으로 중단했습니다."
    assert job.finished_at is not None
    assert active is None


async def test_find_any_active_ignores_finished_jobs(sessionmaker_fixture) -> None:
    """succeeded 잡은 활성으로 보지 않고 pending만 고른다."""
    async with sessionmaker_fixture() as session:
        repo = ExtractionJobRepository(session)
        await repo.create("done", "audit_opinion", {})
        await repo.set_status("done", "succeeded")
        await repo.create("live", "resolve_dates", {}, mode="extract")
        await session.commit()

    async with sessionmaker_fixture() as session:
        active = await ExtractionJobRepository(session).find_any_active()

    assert active is not None and active.job_id == "live"
