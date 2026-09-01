"""Admin 감사 추출 API와 완전성 집계 테스트."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.adapters.dart_http import DartHttpClient
from app.api.deps import get_extraction_service
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import CatalogNotFound
from app.extracting.constants import EXTRACTOR_VERSION
from app.main import create_app
from app.models.audit_report_fact import AuditReportFact
from app.repositories.entry_repository import EntryRepository
from app.repositories.fact_repository import FactRepository
from app.schemas.entry import EntryRecord
from app.schemas.extract import ExtractJobStatusResponse
from app.services.extraction_service import ExtractionService

TOKEN_HEADER = {"X-Admin-Token": "dev-admin-token"}
EXTRACT_PAYLOAD = {
    "start_date": "20200301",
    "end_date": "20200331",
    "report_types": ["F001"],
    "mode": "extract",
}
COMPLETENESS_PARAMS = {
    "start_date": "20200301",
    "end_date": "20200331",
    "report_type": "F001",
}


@pytest.fixture
async def memory_app():
    """메모리 DB를 앱 상태에 연결한다. lifespan은 돌리지 않는다."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)
    app = create_app()
    app.state.sessionmaker = sessionmaker
    yield app, sessionmaker
    await engine.dispose()


def _entry(**overrides: object) -> EntryRecord:
    values: dict[str, object] = {
        "entry_id": "e-cover",
        "rcept_no": "20200331000001",
        "report_type": "F001",
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "submitter": "삼일회계법인",
        "year_end": "(2019.12)",
        "rcept_dt": "2020.03.31",
        "source": "body",
        "dcm_no": "11111",
        "document_name": "감사보고서",
        "section_name": "감사보고서",
        "path": ["감사보고서"],
        "viewer_url": "https://dart.fss.or.kr/report/viewer.do?rcpNo=1",
    }
    values.update(overrides)
    return EntryRecord.model_validate(values)


def _ok_fact(**overrides: object) -> AuditReportFact:
    values: dict[str, object] = {
        "rcept_no": "20200331000001",
        "dcm_no": "11111",
        "source_report_type": "F001",
        "fs_scope": "separate",
        "auditor_status": "ok",
        "opinion_status": "ok",
        "gaap_status": "ok",
        "audit_report_date_status": "ok",
        "audit_report_date": "2020-02-20",
        "audit_report_date_source": "letter",
        "current_period_status": "ok",
        "hours_status": "ok",
        "activities_status": "ok",
        "communications_status": "ok",
        "accounts": [],
        "accounts_status": "ok",
        "fetch_status": "ok",
        "conflicts": [],
        "audit_report_date_candidates": [],
        "extractor_version": EXTRACTOR_VERSION,
    }
    values.update(overrides)
    return AuditReportFact(**values)


async def _seed(sessionmaker, entries: list[EntryRecord], facts: list[AuditReportFact]) -> None:
    async with sessionmaker() as session:
        await EntryRepository(session).upsert_many(entries)
        facts_repo = FactRepository(session)
        for fact in facts:
            await facts_repo.upsert(fact)
        await session.commit()


async def test_extract_requires_admin_token(client_factory) -> None:
    """토큰 없이 추출을 요청하면 401이다."""
    app = create_app()

    async with client_factory(app) as client:
        response = await client.post("/admin/extract/audit-opinion", json=EXTRACT_PAYLOAD)

    assert response.status_code == 401
    assert "토큰" in response.json()["detail"]


async def test_completeness_counts_unextracted_and_lists_remaining(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """대상 문서 2건 중 facts가 1건이면 unextracted는 1이고 목록에 나머지가 나온다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [
            _entry(),
            _entry(
                entry_id="e-other",
                rcept_no="20200331000002",
                dcm_no="22222",
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=2",
            ),
        ],
        [_ok_fact()],
    )

    async with client_factory(app) as client:
        counts = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params=COMPLETENESS_PARAMS,
            headers=TOKEN_HEADER,
        )
        listing = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params={**COMPLETENESS_PARAMS, "status": "unextracted"},
            headers=TOKEN_HEADER,
        )

    assert counts.status_code == 200
    body = counts.json()
    assert body["target"] == 2
    assert body["ok"] == 1
    assert body["unextracted"] == 1

    assert listing.status_code == 200
    listed = listing.json()
    assert listed["unextracted"] == 1
    assert listed["items"] == [{"rcept_no": "20200331000002", "dcm_no": "22222"}]
    assert listed["next_cursor"] is None


class FakeExtractionService:
    """작업 등록과 백그라운드 실행 호출을 기록하는 가짜 서비스."""

    def __init__(self) -> None:
        self.started: list[tuple[str, str, list[str], str]] = []
        self.executed: list[str] = []
        self.soft_stopped: list[str] = []
        self.force_finished: list[str] = []

    async def start(
        self,
        start_date: str,
        end_date: str,
        report_types: list[str],
        mode: str,
    ) -> str:
        self.started.append((start_date, end_date, list(report_types), mode))
        return "job-extract-1"

    async def run_job(self, job_id: str) -> None:
        self.executed.append(job_id)

    async def get_status(self, job_id: str) -> ExtractJobStatusResponse:
        if job_id != "job-extract-1":
            raise CatalogNotFound(f"추출 작업을 찾을 수 없습니다: {job_id}")
        return ExtractJobStatusResponse(
            job_id=job_id, status="succeeded", mode="extract", params=EXTRACT_PAYLOAD
        )

    async def request_soft_stop(self, job_id: str) -> None:
        self.soft_stopped.append(job_id)

    async def force_finish(self, job_id: str) -> None:
        if job_id != "job-extract-1":
            raise CatalogNotFound(f"추출 작업을 찾을 수 없습니다: {job_id}")
        self.force_finished.append(job_id)


def _app_with_extract(service: FakeExtractionService):
    app = create_app()
    app.dependency_overrides[get_extraction_service] = lambda: service
    return app


async def test_extract_rejects_wrong_token(client_factory) -> None:
    """잘못된 Admin 토큰은 401이다."""
    async with client_factory(_app_with_extract(FakeExtractionService())) as client:
        response = await client.post(
            "/admin/extract/audit-opinion",
            json=EXTRACT_PAYLOAD,
            headers={"X-Admin-Token": "wrong-token"},
        )

    assert response.status_code == 401


async def test_extract_accepts_request_and_schedules_job(client_factory) -> None:
    """토큰이 있으면 202과 job_id를 주고 백그라운드에서 run_job을 돌린다."""
    service = FakeExtractionService()

    async with client_factory(_app_with_extract(service)) as client:
        response = await client.post(
            "/admin/extract/audit-opinion", json=EXTRACT_PAYLOAD, headers=TOKEN_HEADER
        )

    assert response.status_code == 202
    assert response.json() == {
        "job_id": "job-extract-1",
        "status": "pending",
        "mode": "extract",
    }
    assert service.started == [("20200301", "20200331", ["F001"], "extract")]
    assert service.executed == ["job-extract-1"]


async def test_extract_defaults_to_extract_mode(client_factory) -> None:
    """mode를 생략하면 extract로 등록한다."""
    service = FakeExtractionService()
    payload = {
        "start_date": "20200301",
        "end_date": "20200331",
        "report_types": ["F001", "F002"],
    }

    async with client_factory(_app_with_extract(service)) as client:
        response = await client.post(
            "/admin/extract/audit-opinion", json=payload, headers=TOKEN_HEADER
        )

    assert response.status_code == 202
    assert response.json()["mode"] == "extract"
    assert service.started[0][2] == ["F001", "F002"]
    assert service.started[0][3] == "extract"


async def test_extract_status_returns_job_progress(client_factory) -> None:
    """job_id로 추출 작업 현황을 조회한다."""
    async with client_factory(_app_with_extract(FakeExtractionService())) as client:
        response = await client.get(
            "/admin/extract/status",
            params={"job_id": "job-extract-1"},
            headers=TOKEN_HEADER,
        )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-extract-1"
    assert response.json()["status"] == "succeeded"


async def test_extract_status_returns_404_for_unknown_job(client_factory) -> None:
    """없는 추출 작업은 404이다."""
    async with client_factory(_app_with_extract(FakeExtractionService())) as client:
        response = await client.get(
            "/admin/extract/status",
            params={"job_id": "missing"},
            headers=TOKEN_HEADER,
        )

    assert response.status_code == 404


async def test_extract_status_requires_admin_token(client_factory) -> None:
    """작업 현황 조회도 Admin 토큰이 필요하다."""
    app = create_app()

    async with client_factory(app) as client:
        response = await client.get("/admin/extract/status", params={"job_id": "job-extract-1"})

    assert response.status_code == 401


async def test_extract_status_reads_job_registered_by_start(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """start가 등록만 한 잡을 실제 get_status로 조회하면 pending과 로그가 나온다."""
    app, sessionmaker = memory_app
    async with httpx.AsyncClient() as http_client:
        service = ExtractionService(
            sessionmaker,
            DartHttpClient(http_client, max_retries=0, retry_backoff_seconds=0.0),
        )
        app.dependency_overrides[get_extraction_service] = lambda: service
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")

        async with client_factory(app) as client:
            response = await client.get(
                "/admin/extract/status",
                params={"job_id": job_id},
                headers=TOKEN_HEADER,
            )

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job_id
    assert body["status"] == "pending"
    assert body["mode"] == "extract"
    assert body["params"]["start_date"] == "20200301"
    assert body["params"]["report_types"] == ["F001"]
    assert body["logs"][0]["message"] == "추출 작업을 등록했습니다."


async def test_extract_accepts_resume_and_reparse_modes(client_factory) -> None:
    """resume·reparse 모드도 202으로 등록한다."""
    for mode in ("resume", "reparse"):
        service = FakeExtractionService()
        payload = {**EXTRACT_PAYLOAD, "mode": mode}

        async with client_factory(_app_with_extract(service)) as client:
            response = await client.post(
                "/admin/extract/audit-opinion", json=payload, headers=TOKEN_HEADER
            )

        assert response.status_code == 202
        assert response.json()["mode"] == mode
        assert service.started[0][3] == mode


async def test_completeness_requires_admin_token(client_factory) -> None:
    """완전성 조회도 Admin 토큰이 필요하다."""
    app = create_app()

    async with client_factory(app) as client:
        response = await client.get(
            "/admin/extract/audit-opinion/completeness", params=COMPLETENESS_PARAMS
        )

    assert response.status_code == 401


async def test_completeness_fully_ok_row_is_not_field_partial(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """핵심 필드가 모두 ok이면 field_partial은 0이다."""
    app, sessionmaker = memory_app
    await _seed(sessionmaker, [_entry()], [_ok_fact()])

    async with client_factory(app) as client:
        response = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params=COMPLETENESS_PARAMS,
            headers=TOKEN_HEADER,
        )

    body = response.json()
    assert response.status_code == 200
    assert body["target"] == 1
    assert body["ok"] == 1
    assert body["field_partial"] == 0


async def test_completeness_field_partial_includes_skipped(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """fetch ok여도 skipped 필드가 있으면 field_partial로 센다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [_entry()],
        [_ok_fact(gaap_status="skipped")],
    )

    async with client_factory(app) as client:
        response = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params=COMPLETENESS_PARAMS,
            headers=TOKEN_HEADER,
        )

    body = response.json()
    assert response.status_code == 200
    assert body["target"] == 1
    assert body["ok"] == 1
    assert body["field_partial"] == 1


async def test_completeness_field_partial_includes_communications_not_found(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """fetch·의견 필드가 ok여도 4절 not_found면 field_partial이다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [_entry()],
        [
            _ok_fact(
                hours_status="ok",
                activities_status="ok",
                communications_status="not_found",
            )
        ],
    )

    async with client_factory(app) as client:
        response = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params=COMPLETENESS_PARAMS,
            headers=TOKEN_HEADER,
        )

    body = response.json()
    assert response.status_code == 200
    assert body["target"] == 1
    assert body["ok"] == 1
    assert body["field_partial"] == 1


async def test_completeness_counts_fetch_states_and_ambiguous_dates(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """fetch 실패·차단·섹션 없음·ambiguous 날짜를 각각 집계한다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [
            _entry(entry_id="e1", rcept_no="20200331000001", dcm_no="1"),
            _entry(entry_id="e2", rcept_no="20200331000002", dcm_no="2"),
            _entry(entry_id="e3", rcept_no="20200331000003", dcm_no="3"),
            _entry(entry_id="e4", rcept_no="20200331000004", dcm_no="4"),
        ],
        [
            _ok_fact(rcept_no="20200331000001", dcm_no="1", fetch_status="fetch_failed"),
            _ok_fact(rcept_no="20200331000002", dcm_no="2", fetch_status="blocked"),
            _ok_fact(rcept_no="20200331000003", dcm_no="3", fetch_status="section_missing"),
            _ok_fact(
                rcept_no="20200331000004",
                dcm_no="4",
                audit_report_date_status="ambiguous",
                audit_report_date=None,
            ),
        ],
    )

    async with client_factory(app) as client:
        response = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params=COMPLETENESS_PARAMS,
            headers=TOKEN_HEADER,
        )

    body = response.json()
    assert response.status_code == 200
    assert body["target"] == 4
    assert body["fetch_failed"] == 1
    assert body["blocked"] == 1
    assert body["section_missing"] == 1
    assert body["ok"] == 1
    assert body["ambiguous_dates"] == 1
    assert body["field_partial"] == 1
    assert body["unextracted"] == 0


async def test_completeness_counts_same_document_leaves_once(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """같은 rcept_no·dcm_no의 leaf 여러 건은 문서 1건으로 센다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [
            _entry(),
            _entry(
                entry_id="e-opinion",
                section_name="독립된 감사인의 감사보고서",
                path=["독립된 감사인의 감사보고서"],
            ),
        ],
        [],
    )

    async with client_factory(app) as client:
        response = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params=COMPLETENESS_PARAMS,
            headers=TOKEN_HEADER,
        )

    body = response.json()
    assert response.status_code == 200
    assert body["target"] == 1
    assert body["unextracted"] == 1


async def test_completeness_rejects_unknown_status(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """목록 status가 허용 값이 아니면 400이다."""
    app, _sessionmaker = memory_app

    async with client_factory(app) as client:
        response = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params={**COMPLETENESS_PARAMS, "status": "ok"},
            headers=TOKEN_HEADER,
        )

    assert response.status_code == 400
    assert "status" in response.json()["detail"]


async def test_completeness_rejects_unknown_report_type(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """허용하지 않는 report_type은 400이다."""
    app, _sessionmaker = memory_app

    async with client_factory(app) as client:
        response = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params={**COMPLETENESS_PARAMS, "report_type": "A002"},
            headers=TOKEN_HEADER,
        )

    assert response.status_code == 400
    assert "report_type" in response.json()["detail"]


async def test_completeness_paginates_status_list(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """status 목록은 limit·cursor로 다음 페이지를 잇는다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [
            _entry(entry_id="e1", rcept_no="20200331000001", dcm_no="111"),
            _entry(entry_id="e2", rcept_no="20200331000002", dcm_no="222"),
            _entry(entry_id="e3", rcept_no="20200331000003", dcm_no="333"),
        ],
        [],
    )

    async with client_factory(app) as client:
        page1 = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params={**COMPLETENESS_PARAMS, "status": "unextracted", "limit": 1},
            headers=TOKEN_HEADER,
        )
        assert page1.status_code == 200
        first = page1.json()
        assert first["items"] == [{"rcept_no": "20200331000001", "dcm_no": "111"}]
        assert first["next_cursor"]

        page2 = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params={
                **COMPLETENESS_PARAMS,
                "status": "unextracted",
                "limit": 1,
                "cursor": first["next_cursor"],
            },
            headers=TOKEN_HEADER,
        )

    second = page2.json()
    assert page2.status_code == 200
    assert second["items"] == [{"rcept_no": "20200331000002", "dcm_no": "222"}]
    assert second["next_cursor"]


async def test_patch_date_sets_override_without_wiping_other_fields(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """PATCH는 날짜 override만 채우고 다른 필드는 그대로 둔다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [_entry()],
        [
            _ok_fact(
                auditor_resolved="삼일회계법인",
                opinion_resolved="unqualified",
                audit_report_date_status="ambiguous",
                audit_report_date=None,
            )
        ],
    )

    async with client_factory(app) as client:
        response = await client.patch(
            "/admin/extract/audit-opinion/20200331000001/11111/date",
            json={"iso": "2020-03-01"},
            headers=TOKEN_HEADER,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["audit_report_date"] == "2020-03-01"
    assert body["audit_report_date_override"] == "2020-03-01"
    assert body["audit_report_date_status"] == "ok"
    assert body["audit_report_date_source"] == "override"

    async with sessionmaker() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.auditor_resolved == "삼일회계법인"
    assert fact.opinion_resolved == "unqualified"
    assert fact.fetch_status == "ok"
    assert fact.audit_report_date == "2020-03-01"
    assert fact.audit_report_date_source == "override"


async def test_patch_date_rejects_invalid_iso(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """YYYY-MM-DD가 아니거나 달력에 없는 날짜는 422다."""
    app, sessionmaker = memory_app
    await _seed(sessionmaker, [_entry()], [_ok_fact()])

    async with client_factory(app) as client:
        for iso in ("not-a-date", "2020-13-01", "20200301", "2020-02-30"):
            response = await client.patch(
                "/admin/extract/audit-opinion/20200331000001/11111/date",
                json={"iso": iso},
                headers=TOKEN_HEADER,
            )
            assert response.status_code == 422, iso


async def test_patch_date_requires_admin_token(client_factory) -> None:
    """날짜 보정도 Admin 토큰이 필요하다."""
    app = create_app()

    async with client_factory(app) as client:
        response = await client.patch(
            "/admin/extract/audit-opinion/20200331000001/11111/date",
            json={"iso": "2020-03-01"},
        )

    assert response.status_code == 401


async def test_patch_date_returns_404_when_fact_missing(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """없는 문서에 날짜를 보정하면 404이다."""
    app, _sessionmaker = memory_app

    async with client_factory(app) as client:
        response = await client.patch(
            "/admin/extract/audit-opinion/20200331000001/11111/date",
            json={"iso": "2020-03-01"},
            headers=TOKEN_HEADER,
        )

    assert response.status_code == 404


async def test_soft_stop_extract_job_requires_token(client_factory) -> None:
    """추출 중단도 Admin 토큰이 필요하다."""
    async with client_factory(_app_with_extract(FakeExtractionService())) as client:
        response = await client.post("/admin/extract/jobs/job-extract-1/soft-stop")

    assert response.status_code == 401


async def test_soft_stop_extract_job_records_request(client_factory) -> None:
    """추출 중단 요청은 202이고 서비스에 job_id를 넘긴다."""
    service = FakeExtractionService()
    async with client_factory(_app_with_extract(service)) as client:
        response = await client.post(
            "/admin/extract/jobs/job-extract-1/soft-stop",
            headers=TOKEN_HEADER,
        )

    assert response.status_code == 202
    assert service.soft_stopped == ["job-extract-1"]


async def test_force_finish_extract_job_records_request(client_factory) -> None:
    """강제 종료는 202이고 없는 잡은 404이다."""
    service = FakeExtractionService()
    async with client_factory(_app_with_extract(service)) as client:
        ok = await client.post(
            "/admin/extract/jobs/job-extract-1/force-finish",
            headers=TOKEN_HEADER,
        )
        missing = await client.post(
            "/admin/extract/jobs/missing/force-finish",
            headers=TOKEN_HEADER,
        )

    assert ok.status_code == 202
    assert service.force_finished == ["job-extract-1"]
    assert missing.status_code == 404
