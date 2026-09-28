"""진단 적재·TSV."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.extracting.constants import EXTRACTOR_VERSION
from app.models.audit_report_fact import AuditReportFact
from app.models.corp import Corp
from app.models.disclosure import Disclosure
from app.models.extraction_job import ExtractionJob
from app.models.extraction_review import ExtractionReview
from app.services.extraction_review_service import (
    ExtractionReviewError,
    diagnose,
    fact_to_view,
)


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def _fact(**overrides: object) -> AuditReportFact:
    values: dict[str, object] = {
        "rcept_no": "20200331000001",
        "dcm_no": "11111",
        "source_report_type": "F001",
        "fs_scope": "separate",
        "fetch_status": "ok",
        "extractor_version": EXTRACTOR_VERSION,
        "hours_status": "not_found",
        "conflicts": [],
    }
    values.update(overrides)
    return AuditReportFact(**values)  # type: ignore[arg-type]


async def test_diagnose_inserts_hold_and_does_not_touch_facts(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        await session.commit()
    async with sessionmaker_fixture() as session:
        await diagnose(session)
        await session.commit()
        fact = (await session.execute(select(AuditReportFact))).scalar_one()
        review = (await session.execute(select(ExtractionReview))).scalars().all()
    assert fact.hours_status == "not_found"
    assert any(row.verdict == "hold" and row.signal == "fail" for row in review)


async def test_diagnose_resets_verdict_when_value_changes(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        await session.commit()
    async with sessionmaker_fixture() as session:
        await diagnose(session)
        await session.commit()
        row = (await session.execute(select(ExtractionReview))).scalars().first()
        assert row is not None
        row.verdict = "source"
        row.tag = "as_written"
        row.note = "원문"
        row.raw_value = "stale"
        await session.commit()
    async with sessionmaker_fixture() as session:
        await diagnose(session)
        await session.commit()
        row = (await session.execute(select(ExtractionReview))).scalars().first()
    assert row is not None
    assert row.verdict == "hold"
    assert row.tag == ""
    assert row.note.startswith("이전 판정=source; 이전 태그=as_written; 이전 값=stale")


async def test_diagnose_keeps_verdict_when_raw_value_matches(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        await session.commit()
    async with sessionmaker_fixture() as session:
        await diagnose(session)
        await session.commit()
        row = (
            (
                await session.execute(
                    select(ExtractionReview).where(ExtractionReview.signal == "fail")
                )
            )
            .scalars()
            .first()
        )
        assert row is not None
        row.verdict = "logic"
        row.note = "파서"
        await session.commit()
    async with sessionmaker_fixture() as session:
        await diagnose(session)
        await session.commit()
        row = (
            (
                await session.execute(
                    select(ExtractionReview).where(ExtractionReview.signal == "fail")
                )
            )
            .scalars()
            .first()
        )
    assert row is not None
    assert row.verdict == "logic"
    assert row.note == "파서"
    assert row.active is True


async def test_diagnose_deactivates_missing_candidate(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(
            ExtractionReview(
                rcept_no="20200331000001",
                dcm_no="11111",
                bundle="hours",
                signal="fail",
                subject="not_found|missing=1|conflicts=0",
                extractor_version=EXTRACTOR_VERSION,
                in_research_panel=False,
                stratum="*|*|hours",
                tail="",
                raw_value="not_found|missing=1|conflicts=0",
                active=True,
                verdict="logic",
                tag="",
                note="",
            )
        )
        session.add(_fact(hours_status="ok", hours=[]))
        await session.commit()
    async with sessionmaker_fixture() as session:
        await diagnose(session)
        await session.commit()
        rows = (await session.execute(select(ExtractionReview))).scalars().all()
    # 상태가 비어 있는 다른 묶음도 fail 후보라, 심어 둔 감사시간 fail만 센다.
    failed = [row for row in rows if row.bundle == "hours" and row.signal == "fail"]
    missing = [row for row in rows if row.signal == "hours_total_missing"]
    assert len(failed) == 1
    assert failed[0].active is False
    assert failed[0].verdict == "logic"
    assert len(missing) == 1
    assert missing[0].active is True


async def test_diagnose_refuses_empty_population(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(
            ExtractionReview(
                rcept_no="x",
                dcm_no="y",
                bundle="hours",
                signal="fail",
                subject="s",
                extractor_version=EXTRACTOR_VERSION,
                in_research_panel=False,
                stratum="",
                tail="",
                raw_value="",
                active=True,
                verdict="hold",
                tag="",
                note="",
            )
        )
        await session.commit()
    async with sessionmaker_fixture() as session:
        with pytest.raises(ExtractionReviewError, match="현재 추출기"):
            await diagnose(session)
        await session.commit()
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.active is True


async def test_diagnose_blocks_when_extraction_job_is_active(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        session.add(
            ExtractionJob(
                job_id="job-1",
                status="running",
                extractor_id="audit_opinion",
                mode="extract",
                params={},
            )
        )
        await session.commit()
    async with sessionmaker_fixture() as session:
        with pytest.raises(ExtractionReviewError, match="추출"):
            await diagnose(session)


def test_fact_to_view_overlays_disclosure_and_corp() -> None:
    fact = _fact()
    disclosure = Disclosure(
        rcept_no=fact.rcept_no,
        corp_code="00123456",
        year_end="2019.12",
        rcept_dt="20200331",
    )
    corp = Corp(corp_code="00123456", corp_cls="Y")
    view = fact_to_view(fact, disclosure, corp)
    assert view.rcept_no == fact.rcept_no
    assert view.hours_status == "not_found"
    assert view.corp_code == "00123456"
    assert view.year_end == "2019.12"
    assert view.rcept_dt == "20200331"
    assert view.corp_cls == "Y"


def test_fact_to_view_without_disclosure_clears_rcept_dt() -> None:
    view = fact_to_view(_fact(), None, None)
    assert view.rcept_dt == ""
    assert view.corp_code is None
    assert view.year_end is None
    assert view.corp_cls is None
