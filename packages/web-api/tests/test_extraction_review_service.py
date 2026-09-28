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
    REVIEW_PAGE_SIZE,
    ExtractionReviewError,
    diagnose,
    export_tsv,
    fact_to_view,
    has_source_and_logic_iqr_stratum,
    import_tsv,
    list_default_reviews,
    save_review_form,
)
from scripts.extraction_reviews import build_parser


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


def _review(**overrides: object) -> ExtractionReview:
    values: dict[str, object] = {
        "rcept_no": "20200331000001",
        "dcm_no": "11111",
        "bundle": "accounts",
        "signal": "iqr_high",
        "subject": "total_asset",
        "extractor_version": EXTRACTOR_VERSION,
        "in_research_panel": True,
        "stratum": "F001|separate|total_asset",
        "tail": "high",
        "queue_order": 1,
        "raw_value": "10",
        "active": True,
        "verdict": "hold",
        "tag": "",
        "note": "",
    }
    values.update(overrides)
    return ExtractionReview(**values)  # type: ignore[arg-type]


async def test_export_default_and_next_slice(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_review(queue_order=1, verdict="source", tag="real_magnitude"))
        session.add(
            _review(
                signal="iqr_low",
                tail="low",
                queue_order=1,
                verdict="logic",
                subject="total_asset",
            )
        )
        session.add(
            _review(signal="iqr_high", queue_order=6, raw_value="99", subject="total_equity")
        )
        session.add(
            _review(
                bundle="hours",
                signal="hours_nonpositive",
                subject="audit_current_total",
                tail="",
                queue_order=None,
                stratum="F001|separate|audit_current_total",
            )
        )
        await session.commit()
        default_rows = await export_tsv(session, next_slice=False)
        next_rows = await export_tsv(session, next_slice=True)
    default_signals = {row["signal"] for row in default_rows}
    assert "hours_nonpositive" in default_signals
    assert "iqr_high" in default_signals
    assert all(row["queue_order"] != "6" for row in default_rows)
    assert {row["subject"] for row in next_rows} == {"total_equity"}
    assert default_rows[0]["viewer_url"].startswith("https://dart.fss.or.kr/")


async def test_mixed_stratum_with_empty_next_window(sessionmaker_fixture) -> None:
    """판정이 갈린 층의 다음 hold 창이 비어도 혼합 층은 있다."""
    async with sessionmaker_fixture() as session:
        session.add(_review(queue_order=1, verdict="source", tag="real_magnitude"))
        session.add(
            _review(
                signal="iqr_low",
                tail="low",
                queue_order=1,
                verdict="logic",
            )
        )
        session.add(
            _review(
                signal="iqr_high",
                queue_order=10,
                raw_value="99",
                subject="total_equity",
            )
        )
        await session.commit()
        mixed = await has_source_and_logic_iqr_stratum(session)
        next_rows = await export_tsv(session, next_slice=True)
    assert mixed is True
    assert next_rows == []


async def test_import_rejects_bad_file_and_keeps_blanks(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_review(verdict="source", tag="as_written", note="유지"))
        await session.commit()
        header = "rcept_no\tdcm_no\tbundle\tsignal\tsubject\tverdict\ttag\tnote\n"
        good = (
            "\ufeff"
            + header
            + "20200331000001\t11111\taccounts\tiqr_high\ttotal_asset\thold\t-\t\n"
        )
        count = await import_tsv(session, good)
        await session.commit()
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert count == 1
    assert row.verdict == "hold"
    assert row.tag == ""
    assert row.note == "유지"
    async with sessionmaker_fixture() as session:
        bad = (
            header + "20200331000001\t11111\taccounts\tiqr_high\ttotal_asset\tlogic\tas_written\t\n"
        )
        with pytest.raises(ExtractionReviewError):
            await import_tsv(session, bad)
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.verdict == "hold"


def test_parser_accepts_three_commands() -> None:
    parser = build_parser()
    diagnose_args = parser.parse_args(["diagnose", "--summary-out", "out.tsv"])
    export_args = parser.parse_args(["export-tsv", "--next", "--out", "out.tsv"])
    import_args = parser.parse_args(["import-tsv", "--in", "in.tsv"])
    assert diagnose_args.command == "diagnose"
    assert export_args.next_slice is True
    assert import_args.path == "in.tsv"


async def test_list_default_reviews_sorts_panel_and_drops_queue_six(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_review(rcept_no="20200331000003", in_research_panel=False, queue_order=1))
        session.add(
            _review(
                rcept_no="20200331000001",
                signal="hours_nonpositive",
                subject="audit_current_total",
                tail="",
                queue_order=None,
                in_research_panel=True,
            )
        )
        session.add(_review(rcept_no="20200331000002", in_research_panel=True, queue_order=2))
        session.add(
            _review(
                rcept_no="20200331000004",
                queue_order=6,
                subject="total_equity",
                in_research_panel=True,
            )
        )
        await session.commit()
        rows, total = await list_default_reviews(session, bundle="", verdict="", page=1)
    assert total == 3
    assert [row.rcept_no for row in rows] == [
        "20200331000002",
        "20200331000001",
        "20200331000003",
    ]


async def test_list_default_reviews_pages_and_filters(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        for index in range(REVIEW_PAGE_SIZE + 1):
            session.add(
                _review(
                    rcept_no=f"20200331{index:06d}",
                    signal="hours_nonpositive",
                    subject="audit_current_total",
                    tail="",
                    queue_order=None,
                    in_research_panel=False,
                    bundle="hours",
                )
            )
        await session.commit()
        first, total = await list_default_reviews(session, bundle="nope", verdict="nope", page=0)
        second, _ = await list_default_reviews(session, bundle="hours", verdict="hold", page=2)
        none, _ = await list_default_reviews(session, bundle="accounts", verdict="", page=1)
        past, _ = await list_default_reviews(session, bundle="", verdict="", page=99)
    assert total == REVIEW_PAGE_SIZE + 1
    assert len(first) == REVIEW_PAGE_SIZE
    assert first[0].rcept_no == "20200331000000"
    assert [row.rcept_no for row in second] == [f"20200331{REVIEW_PAGE_SIZE:06d}"]
    assert none == []
    assert past == []


async def test_save_review_form_writes_three_fields_and_clears_tag(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_review(tag="as_written", note="이전 판정=source\n유지"))
        await session.commit()
        saved = await save_review_form(
            session,
            rcept_no="20200331000001",
            dcm_no="11111",
            bundle="accounts",
            signal="iqr_high",
            subject="total_asset",
            verdict="source",
            tag="",
            note="이전 판정=source\n유지",
        )
        await session.commit()
    assert saved.verdict == "source"
    assert saved.tag == ""
    assert saved.note == "이전 판정=source\n유지"
    assert saved.raw_value == "10"
    assert saved.active is True


@pytest.mark.parametrize(
    ("verdict", "tag", "message"),
    [
        ("nope", "", "판정은 hold, source, logic만 적을 수 있습니다."),
        ("source", "nope", "태그는 as_written, real_magnitude, rare_but_valid, other만 적을 수 있습니다."),
        ("logic", "as_written", "logic 또는 hold 판정에는 태그를 적을 수 없습니다."),
        ("hold", "other", "logic 또는 hold 판정에는 태그를 적을 수 없습니다."),
    ],
)
async def test_save_review_form_rejects_without_write(
    sessionmaker_fixture, verdict: str, tag: str, message: str
) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_review())
        await session.commit()
        with pytest.raises(ExtractionReviewError, match=message):
            await save_review_form(
                session,
                rcept_no="20200331000001",
                dcm_no="11111",
                bundle="accounts",
                signal="iqr_high",
                subject="total_asset",
                verdict=verdict,
                tag=tag,
                note="그대로",
            )
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.verdict == "hold"
    assert row.tag == ""
    assert row.note == ""


async def test_save_review_form_rejects_outside_default_slice(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_review(queue_order=6))
        session.add(
            _review(
                rcept_no="20200331000009",
                active=False,
                signal="hours_nonpositive",
                subject="audit_current_total",
            )
        )
        await session.commit()
        for rcept_no, signal, subject in (
            ("20200331000001", "iqr_high", "total_asset"),
            ("20200331000009", "hours_nonpositive", "audit_current_total"),
            ("없는번호", "iqr_high", "total_asset"),
        ):
            with pytest.raises(ExtractionReviewError, match="해당하는 검토 행이 없습니다."):
                await save_review_form(
                    session,
                    rcept_no=rcept_no,
                    dcm_no="11111",
                    bundle="accounts",
                    signal=signal,
                    subject=subject,
                    verdict="logic",
                    tag="",
                    note="",
                )
        kept = (await session.execute(select(ExtractionReview))).scalars().all()
    assert {row.verdict for row in kept} == {"hold"}
