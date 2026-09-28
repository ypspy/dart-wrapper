"""Admin 진단 검토 화면."""

from __future__ import annotations

import re
from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_session
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.extracting.constants import EXTRACTOR_VERSION
from app.main import create_app
from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
from app.models.extraction_job import ExtractionJob
from app.models.extraction_review import ExtractionReview
from app.services.extraction_review_service import REVIEW_PAGE_SIZE

ClientFactory = Callable[[FastAPI], httpx.AsyncClient]


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


async def _app() -> tuple[FastAPI, async_sessionmaker[AsyncSession]]:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)
    app = create_app()

    async def _session():
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    return app, sessionmaker


async def test_reviews_page_redirects_without_token(client_factory: ClientFactory) -> None:
    app, _sessionmaker = await _app()
    async with client_factory(app) as client:
        response = await client.get("/admin/reviews")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/admin/token")


async def test_reviews_page_lists_default_slice_and_nav(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_review(rcept_no="20200331000003", in_research_panel=False, queue_order=1))
        session.add(
            _review(
                rcept_no="20200331000001",
                signal="hours_nonpositive",
                subject="audit_current_total",
                tail="",
                queue_order=None,
            )
        )
        session.add(_review(rcept_no="20200331000002", queue_order=2, subject="total_equity"))
        session.add(_review(rcept_no="20200331000004", queue_order=6, subject="net_income"))
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/reviews")
    text = response.text
    assert response.status_code == 200
    assert 'href="/admin/reviews" class="is-selected"' in text
    assert "검토" in text
    assert "진단을 실행하면 요약이 나옵니다." in text
    assert "왼쪽에서 한 건을 고르세요." in text
    assert text.index("20200331000002") < text.index("20200331000001")
    assert text.index("20200331000001") < text.index("20200331000003")
    assert "20200331000004" not in text


async def test_reviews_page_filters_and_pages(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
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
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        page2 = await client.get(
            "/admin/reviews", params={"page": 2, "bundle": "hours", "verdict": "hold"}
        )
        ignored = await client.get("/admin/reviews", params={"bundle": "nope", "verdict": "nope"})
    assert f"20200331{REVIEW_PAGE_SIZE:06d}" in page2.text
    assert "20200331000000" not in page2.text
    assert "20200331000000" in ignored.text


async def test_reviews_page_opens_default_row_and_rejects_queue_six(
    client_factory: ClientFactory,
) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_review(raw_value="10", note="이전 판정=source\n유지"))
        session.add(_review(rcept_no="20200331000006", queue_order=6, subject="total_equity"))
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        opened = await client.get(
            "/admin/reviews",
            params={
                "rcept_no": "20200331000001",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_asset",
            },
        )
        partial = await client.get(
            "/admin/reviews",
            params={
                "rcept_no": "20200331000001",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_asset",
            },
            headers={"HX-Request": "true"},
        )
        missing = await client.get(
            "/admin/reviews",
            params={
                "rcept_no": "20200331000006",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_equity",
            },
        )
    assert "이전 판정=source" in opened.text
    assert (
        "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20200331000001&amp;dcmNo=11111" in opened.text
    )
    assert 'target="_blank"' in opened.text
    assert "DART 수집 운영" not in partial.text
    assert "10" in partial.text
    assert "이 행은 기본 검토 목록에 없습니다." in missing.text
    assert ">20200331000006</a>" not in missing.text
    assert not re.search(
        r'hx-get="/admin/reviews\?[^"]*rcept_no=20200331000006',
        missing.text,
    )
    assert (
        'action="/admin/reviews/diagnose?page=1&amp;bundle=&amp;verdict=&amp;rcept_no=20200331000006&amp;dcm_no=11111&amp;key_bundle=accounts&amp;signal=iqr_high&amp;subject=total_equity"'
        in missing.text
    )


def _fact() -> AuditReportFact:
    return AuditReportFact(
        rcept_no="20200331000001",
        dcm_no="11111",
        source_report_type="F001",
        fs_scope="separate",
        fetch_status="ok",
        extractor_version=EXTRACTOR_VERSION,
        hours_status="not_found",
        conflicts=[],
    )


async def test_diagnose_shows_summary_and_keeps_catalog(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_fact())
        session.add(Disclosure(rcept_no="20200331000001", corp_name="그대로", rcept_dt="20200331"))
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post("/admin/reviews/diagnose")
    assert response.status_code == 200
    assert "실패 " in response.text
    async with sessionmaker() as session:
        fact = (await session.execute(select(AuditReportFact))).scalar_one()
        disclosure = (await session.execute(select(Disclosure))).scalar_one()
        reviews = (await session.execute(select(ExtractionReview))).scalars().all()
    assert fact.hours_status == "not_found"
    assert disclosure.corp_name == "그대로"
    assert reviews


async def test_diagnose_running_job_does_not_change_reviews(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_fact())
        session.add(_review(verdict="logic", note="유지"))
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
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post("/admin/reviews/diagnose")
    assert "추출 잡이 진행 중이라 진단을 시작하지 않습니다." in response.text
    async with sessionmaker() as session:
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.verdict == "logic"
    assert row.note == "유지"


async def test_diagnose_empty_population_keeps_active(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_review(active=True, verdict="source", tag="as_written"))
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post("/admin/reviews/diagnose")
    assert "현재 추출기 ok 행이 없습니다." in response.text
    async with sessionmaker() as session:
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.active is True
    assert row.verdict == "source"
    assert row.tag == "as_written"


async def test_diagnose_keeps_out_of_slice_natural_key(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_review(rcept_no="20200331000006", queue_order=6, subject="total_equity"))
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post(
            "/admin/reviews/diagnose",
            params={
                "rcept_no": "20200331000006",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_equity",
            },
        )
    assert response.status_code == 200
    assert "이 행은 기본 검토 목록에 없습니다." in response.text
    assert "왼쪽에서 한 건을 고르세요." not in response.text
    assert (
        'action="/admin/reviews/diagnose?page=1&amp;bundle=&amp;verdict=&amp;rcept_no=20200331000006'
        in response.text
    )


async def test_diagnose_requires_token(client_factory: ClientFactory) -> None:
    app, _sessionmaker = await _app()
    async with client_factory(app) as client:
        response = await client.post("/admin/reviews/diagnose")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/admin/token")


async def test_verdict_requires_token(client_factory: ClientFactory) -> None:
    app, _sessionmaker = await _app()
    async with client_factory(app) as client:
        response = await client.post(
            "/admin/reviews/verdict",
            data={
                "rcept_no": "20200331000001",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_asset",
                "verdict": "logic",
                "tag": "",
                "note": "",
            },
        )
    assert response.status_code == 307
    assert response.headers["location"].endswith("/admin/token")


async def test_verdict_keeps_list_filters_after_save(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(
            _review(
                signal="hours_nonpositive",
                subject="audit_current_total",
                tail="",
                queue_order=None,
                in_research_panel=False,
                bundle="hours",
                verdict="hold",
            )
        )
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post(
            "/admin/reviews/verdict?page=2&bundle=hours&verdict=hold",
            data={
                "rcept_no": "20200331000001",
                "dcm_no": "11111",
                "key_bundle": "hours",
                "signal": "hours_nonpositive",
                "subject": "audit_current_total",
                "verdict": "source",
                "tag": "",
                "note": "",
            },
        )
    assert response.status_code == 200
    assert (
        'value="source" selected' in response.text
        or 'value="source" selected="selected"' in response.text
    )
    assert "page=2&amp;bundle=hours&amp;verdict=hold" in response.text
    assert "page=2&amp;bundle=hours&amp;verdict=source" not in response.text
    async with sessionmaker() as session:
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.verdict == "source"


async def test_verdict_saves_three_fields_and_empty_tag(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_fact())
        session.add(Disclosure(rcept_no="20200331000001", corp_name="그대로", rcept_dt="20200331"))
        session.add(_review(tag="as_written", note="이전 판정=source\n유지", raw_value="10"))
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post(
            "/admin/reviews/verdict",
            data={
                "rcept_no": "20200331000001",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_asset",
                "verdict": "source",
                "tag": "",
                "note": "이전 판정=source\n유지",
            },
        )
    assert response.status_code == 200
    assert "hx-swap-oob" in response.text
    assert (
        'value="source" selected' in response.text
        or 'value="source" selected="selected"' in response.text
    )
    async with sessionmaker() as session:
        row = (await session.execute(select(ExtractionReview))).scalar_one()
        fact = (await session.execute(select(AuditReportFact))).scalar_one()
        disclosure = (await session.execute(select(Disclosure))).scalar_one()
    assert row.verdict == "source"
    assert row.tag == ""
    assert row.note == "이전 판정=source\n유지"
    assert row.raw_value == "10"
    assert fact.hours_status == "not_found"
    assert disclosure.corp_name == "그대로"


@pytest.mark.parametrize(
    ("verdict", "tag", "message"),
    [
        ("nope", "", "판정은 hold, source, logic만 적을 수 있습니다."),
        (
            "source",
            "-",
            "태그는 as_written, real_magnitude, rare_but_valid, other만 적을 수 있습니다.",
        ),
        ("logic", "as_written", "logic 또는 hold 판정에는 태그를 적을 수 없습니다."),
        ("hold", "other", "logic 또는 hold 판정에는 태그를 적을 수 없습니다."),
    ],
)
async def test_verdict_rejects_and_shows_reason(
    client_factory: ClientFactory, verdict: str, tag: str, message: str
) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_review())
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post(
            "/admin/reviews/verdict",
            data={
                "rcept_no": "20200331000001",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_asset",
                "verdict": verdict,
                "tag": tag,
                "note": "바꾸지마",
            },
        )
    assert message in response.text
    async with sessionmaker() as session:
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.verdict == "hold"
    assert row.tag == ""
    assert row.note == ""


async def test_verdict_rejects_queue_six(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_review(queue_order=6, verdict="hold"))
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post(
            "/admin/reviews/verdict",
            data={
                "rcept_no": "20200331000001",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_asset",
                "verdict": "logic",
                "tag": "",
                "note": "",
            },
        )
    assert "해당하는 검토 행이 없습니다." in response.text
    async with sessionmaker() as session:
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.verdict == "hold"
