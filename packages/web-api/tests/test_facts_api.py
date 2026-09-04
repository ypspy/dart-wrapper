"""Public 감사 추출 결과 조회 API 테스트."""

from __future__ import annotations

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.extracting.constants import EXTRACTOR_VERSION
from app.main import create_app
from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
from app.repositories.fact_repository import FactRepository

FACTS_PATH = "/api/v1/disclosures/{rcp_no}/audit-facts"


async def _memory_app():
    """메모리 DB를 앱 상태에 연결한다. lifespan은 돌리지 않는다."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)
    app = create_app()
    app.state.sessionmaker = sessionmaker
    return app, sessionmaker, engine


def _fact(**overrides: object) -> AuditReportFact:
    """조회 응답에 필요한 해소 필드가 채워진 샘플 행."""
    values: dict[str, object] = {
        "rcept_no": "20200331000001",
        "dcm_no": "11111",
        "source_report_type": "F001",
        "fs_scope": "separate",
        "auditor_resolved": "삼일회계법인",
        "auditor_source": "cover",
        "opinion_resolved": "unqualified",
        "opinion_source": "letter",
        "audit_report_date": "2020-02-20",
        "audit_report_date_source": "letter",
        "gaap_resolved": "k-ifrs",
        "gaap_source": "letter",
        "current_period_resolved": "제51기",
        "current_period_source": "cover",
        "hours": [
            {
                "role": "engagement_partner",
                "role_raw": "담당이사 (업무수행이사)",
                "metric": "audit",
                "period": "current",
                "value": 80,
            }
        ],
        "hours_status": "ok",
        "activities": [],
        "activities_status": "ok",
        "communications": {"has_audit_committee": False, "items": []},
        "communications_status": "not_found",
        "accounts": [
            {
                "account": "total_asset",
                "period": "current",
                "value": 1,
                "status": "ok",
            }
        ],
        "accounts_status": "ok",
        "icfr_engagement": "review",
        "icfr_opinion_code": "unqualified",
        "icfr_status": "ok",
        "going_concern": 0,
        "going_concern_status": "ok",
        "subsidiary_count": None,
        "subsidiary_status": "not_applicable",
        "fetch_status": "ok",
        "conflicts": [{"field": "auditor", "left": "표지", "right": "본문"}],
        "audit_report_date_candidates": [],
        "extractor_version": EXTRACTOR_VERSION,
        "date_resolver_model": "gpt-4o-mini",
        "date_resolver_prompt_version": "v1",
        "date_resolver_raw_response": '{"index":0}',
    }
    values.update(overrides)
    return AuditReportFact(**values)


async def _seed(sessionmaker, facts: list[AuditReportFact]) -> None:
    async with sessionmaker() as session:
        repo = FactRepository(session)
        for fact in facts:
            await repo.upsert(fact)
        await session.commit()


async def test_audit_facts_returns_empty_list_when_missing(client_factory) -> None:
    """카탈로그에 공시가 있어도 추출 행이 없으면 404가 아니라 빈 목록이다."""
    app, _sessionmaker, engine = await _memory_app()
    try:
        async with client_factory(app) as client:
            response = await client.get(FACTS_PATH.format(rcp_no="20200331000001"))
    finally:
        await engine.dispose()

    assert response.status_code == 200
    assert response.json() == []


async def test_audit_facts_returns_resolved_source_conflicts_and_fetch_status(
    client_factory,
) -> None:
    """저장된 행의 해소 값·출처·conflicts·fetch_status를 그대로 돌려준다."""
    app, sessionmaker, engine = await _memory_app()
    try:
        await _seed(sessionmaker, [_fact()])
        async with client_factory(app) as client:
            response = await client.get(FACTS_PATH.format(rcp_no="20200331000001"))
    finally:
        await engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    row = body[0]
    assert row["rcept_no"] == "20200331000001"
    assert row["dcm_no"] == "11111"
    assert row["auditor_resolved"] == "삼일회계법인"
    assert row["auditor_source"] == "cover"
    assert row["opinion_resolved"] == "unqualified"
    assert row["opinion_source"] == "letter"
    assert row["gaap_resolved"] == "k-ifrs"
    assert row["gaap_source"] == "letter"
    assert row["current_period_resolved"] == "제51기"
    assert row["current_period_source"] == "cover"
    assert row["fetch_status"] == "ok"
    assert "hours" in row
    assert row["hours"] == [
        {
            "role": "engagement_partner",
            "role_raw": "담당이사 (업무수행이사)",
            "metric": "audit",
            "period": "current",
            "value": 80,
        }
    ]
    assert row["hours_status"] == "ok"
    assert row["activities"] == []
    assert row["activities_status"] == "ok"
    assert row["communications"] == {"has_audit_committee": False, "items": []}
    assert row["communications_status"] == "not_found"
    assert "accounts" in row
    assert row["accounts"] == [
        {
            "account": "total_asset",
            "period": "current",
            "value": 1,
            "status": "ok",
        }
    ]
    assert row["accounts_status"] == "ok"
    assert row["icfr_status"] == "ok"
    assert row["icfr_engagement"] == "review"
    assert row["icfr_opinion_code"] == "unqualified"
    assert "going_concern" in row
    assert row["going_concern"] == 0
    assert row["going_concern_status"] == "ok"
    assert "subsidiary_count" in row
    assert row["subsidiary_count"] is None
    assert "subsidiary_status" in row
    assert row["subsidiary_status"] == "not_applicable"
    assert row["conflicts"] == [{"field": "auditor", "left": "표지", "right": "본문"}]
    assert "date_resolver_model" not in row
    assert "date_resolver_prompt_version" not in row
    assert "date_resolver_raw_response" not in row


async def test_audit_facts_does_not_require_admin_token(client_factory) -> None:
    """Public 조회는 Admin 토큰 없이 200을 준다."""
    app, sessionmaker, engine = await _memory_app()
    try:
        await _seed(sessionmaker, [_fact()])
        async with client_factory(app) as client:
            response = await client.get(
                FACTS_PATH.format(rcp_no="20200331000001"),
                headers={},
            )
    finally:
        await engine.dispose()

    assert response.status_code == 200
    assert response.json()[0]["dcm_no"] == "11111"


async def test_audit_facts_lists_documents_in_dcm_no_order(client_factory) -> None:
    """같은 접수의 문서 행을 dcm_no 오름차순으로 반환한다."""
    app, sessionmaker, engine = await _memory_app()
    try:
        await _seed(
            sessionmaker,
            [
                _fact(dcm_no="22222", fs_scope="consolidated", source_report_type="F002"),
                _fact(dcm_no="11111"),
            ],
        )
        async with client_factory(app) as client:
            response = await client.get(FACTS_PATH.format(rcp_no="20200331000001"))
    finally:
        await engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert [row["dcm_no"] for row in body] == ["11111", "22222"]
    assert body[1]["fs_scope"] == "consolidated"
    assert body[1]["source_report_type"] == "F002"


LIST_PATH = "/api/v1/facts"


async def test_list_facts_empty_is_not_404(client_factory) -> None:
    app, _sessionmaker, engine = await _memory_app()
    try:
        async with client_factory(app) as client:
            response = await client.get(LIST_PATH)
    finally:
        await engine.dispose()
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


async def test_list_facts_pages_and_rejects_bad_cursor(client_factory) -> None:
    app, sessionmaker, engine = await _memory_app()
    try:
        async with sessionmaker() as session:
            session.add(
                Disclosure(
                    rcept_no="20200331000001",
                    rcept_dt="2020.03.31",
                    corp_name="갑",
                    correction_type="최초공시",
                    year_end="(2019.12)",
                    entry_count=1,
                )
            )
            session.add(
                Disclosure(
                    rcept_no="20200331000002",
                    rcept_dt="2020.03.31",
                    corp_name="을",
                    correction_type="최초공시",
                    year_end="(2019.12)",
                    entry_count=1,
                )
            )
            await session.commit()
        await _seed(
            sessionmaker,
            [
                _fact(rcept_no="20200331000002", dcm_no="2"),
                _fact(rcept_no="20200331000001", dcm_no="1"),
            ],
        )
        async with client_factory(app) as client:
            first = await client.get(LIST_PATH, params={"limit": 1})
            assert first.status_code == 200
            body = first.json()
            assert len(body["items"]) == 1
            assert list(body["items"][0])[:4] == [
                "corp_name",
                "year_end",
                "rcept_dt",
                "correction_type",
            ]
            assert body["items"][0]["rcept_no"] == "20200331000002"
            assert body["items"][0]["corp_name"] == "을"
            assert "going_concern" in body["items"][0]
            assert "subsidiary_count" in body["items"][0]
            assert "subsidiary_status" in body["items"][0]
            assert "accounts" in body["items"][0]
            assert "date_resolver_model" not in body["items"][0]
            assert body["next_cursor"]
            second = await client.get(
                LIST_PATH, params={"limit": 1, "cursor": body["next_cursor"]}
            )
            assert [row["rcept_no"] for row in second.json()["items"]] == [
                "20200331000001"
            ]
            bad = await client.get(LIST_PATH, params={"cursor": "!!!"})
            assert bad.status_code == 400
    finally:
        await engine.dispose()
