"""Admin 감사 추출 API와 완전성 집계 테스트."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.adapters.dart_http import DartHttpClient
from app.api.deps import get_extraction_service
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import BadRequest, CatalogNotFound
from app.extracting.constants import EXTRACTOR_VERSION
from app.extracting.field_bundles import (
    BUNDLE_KEYS,
    DART_DOCUMENT_VIEW,
    add_fact_outcomes,
    empty_field_bundle_counts,
    icfr_period_year,
)
from app.main import create_app
from app.models.audit_report_fact import AuditReportFact
from app.models.corp import Corp
from app.models.disclosure import Disclosure
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.entry_repository import EntryRepository
from app.repositories.fact_repository import FactRepository
from app.schemas.entry import EntryRecord
from app.schemas.extract import ExtractJobStatusResponse
from app.services.completeness_service import CompletenessService
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
        "icfr_status": "ok",
        "going_concern": 0,
        "going_concern_status": "ok",
        "subsidiary_status": "not_applicable",
        "fetch_status": "ok",
        "conflicts": [],
        "audit_report_date_candidates": [],
        "extractor_version": EXTRACTOR_VERSION,
    }
    values.update(overrides)
    return AuditReportFact(**values)


def _disclosures_from_entries(entries: list[EntryRecord]) -> list[Disclosure]:
    """완전성 집계가 쓰는 disclosures 행을 entry에서 만든다."""
    by_rcept: dict[str, Disclosure] = {}
    for entry in entries:
        existing = by_rcept.get(entry.rcept_no)
        if existing is not None:
            existing.entry_count += 1
            continue
        by_rcept[entry.rcept_no] = Disclosure(
            rcept_no=entry.rcept_no,
            corp_code=entry.corp_code,
            corp_name=entry.corp_name,
            report_nm=entry.report_nm,
            report_type=entry.report_type,
            correction_type=entry.correction_type,
            submitter=entry.submitter,
            rcept_dt=entry.rcept_dt or "",
            bsns_year=entry.bsns_year,
            year_end=entry.year_end,
            disclosure_url=entry.disclosure_url,
            entry_count=1,
        )
    return list(by_rcept.values())


async def _seed(sessionmaker, entries: list[EntryRecord], facts: list[AuditReportFact]) -> None:
    async with sessionmaker() as session:
        await EntryRepository(session).upsert_many(entries)
        await DisclosureRepository(session).upsert_many(_disclosures_from_entries(entries))
        facts_repo = FactRepository(session)
        for fact in facts:
            await facts_repo.upsert(fact)
        await session.commit()


async def _seed_corp(
    sessionmaker,
    corp_code: str = "00126380",
    corp_cls: str | None = "Y",
) -> None:
    """완전성 조인에 쓸 corps 한 행."""
    async with sessionmaker() as session:
        session.add(Corp(corp_code=corp_code, fetch_status="ok", corp_cls=corp_cls))
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


async def test_completeness_stale_version_is_not_ok(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """옛 파서 ok 행은 추출 ok가 아니라 구버전(재추출 필요)이다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [
            _entry(),
            _entry(
                entry_id="e-current",
                rcept_no="20200331000002",
                dcm_no="22222",
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=2",
            ),
        ],
        [
            _ok_fact(extractor_version="audit_opinion.v2"),
            _ok_fact(
                rcept_no="20200331000002",
                dcm_no="22222",
                extractor_version=EXTRACTOR_VERSION,
            ),
        ],
    )

    async with client_factory(app) as client:
        counts = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params=COMPLETENESS_PARAMS,
            headers=TOKEN_HEADER,
        )
        listing = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params={**COMPLETENESS_PARAMS, "status": "stale_version"},
            headers=TOKEN_HEADER,
        )

    assert counts.status_code == 200
    body = counts.json()
    assert body["target"] == 2
    assert body["ok"] == 1
    assert body["stale_version"] == 1
    assert body["unextracted"] == 0
    assert body["field_partial"] == 0

    assert listing.status_code == 200
    listed = listing.json()
    assert listed["stale_version"] == 1
    assert listed["items"] == [{"rcept_no": "20200331000001", "dcm_no": "11111"}]


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
    for mode in ("resume", "reparse", "patch"):
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
    assert body["all_success"] == 1


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


async def test_completeness_field_partial_includes_accounts_skipped(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """다른 필드가 ok여도 accounts_status=skipped면 field_partial이다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [_entry()],
        [_ok_fact(accounts_status="skipped")],
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


async def test_completeness_field_partial_includes_icfr_skipped(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """상장 F001의 icfr_status=skipped는 field_partial이다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [_entry()],
        [_ok_fact(icfr_status="skipped")],
    )
    await _seed_corp(sessionmaker, corp_cls="N")

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
    assert body["all_success"] == 0


async def test_completeness_unlisted_f001_icfr_skipped_is_not_field_partial(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """비상장 F001 icfr skipped는 제도상없음이며 field_partial이 아니다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [_entry()],
        [_ok_fact(icfr_status="skipped")],
    )
    await _seed_corp(sessionmaker, corp_cls="E")

    async with client_factory(app) as client:
        counts = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params=COMPLETENESS_PARAMS,
            headers=TOKEN_HEADER,
        )
        bundles = await client.get(
            "/admin/extract/audit-opinion/field-bundles",
            params={"start_date": "20200301", "end_date": "20200331"},
            headers=TOKEN_HEADER,
        )

    assert counts.status_code == 200
    assert counts.json()["field_partial"] == 0
    assert counts.json()["all_success"] == 1
    icfr = next(row for row in bundles.json()["bundles"] if row["bundle"] == "icfr")
    assert icfr["expected_missing"] == 1
    assert icfr["fail"] == 0


async def test_list_field_bundle_fail_items_skips_unlisted_f001_icfr_only(
    memory_app: tuple[FastAPI, object],
) -> None:
    """비상장 F001 내부회계 skipped는 실패 목록에 없고, 코넥스는 들어간다."""
    _app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [
            _entry(),
            _entry(
                entry_id="e-listed",
                rcept_no="20200331000002",
                dcm_no="22222",
                corp_code="00401731",
            ),
        ],
        [
            _ok_fact(icfr_status="skipped"),
            _ok_fact(
                rcept_no="20200331000002",
                dcm_no="22222",
                icfr_status="skipped",
            ),
        ],
    )
    await _seed_corp(sessionmaker, corp_code="00126380", corp_cls="E")
    await _seed_corp(sessionmaker, corp_code="00401731", corp_cls="N")

    async with sessionmaker() as session:
        listed = await CompletenessService(session).list_field_bundle_fail_items(
            start_date="20200301",
            end_date="20200331",
            bundle="icfr",
        )
    assert [(item.rcept_no, item.dcm_no) for item in listed.items] == [
        ("20200331000002", "22222")
    ]


async def test_completeness_field_partial_includes_going_concern_skipped(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """다른 필드가 ok여도 going_concern_status=skipped면 field_partial이다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [_entry()],
        [_ok_fact(going_concern_status="skipped")],
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


async def test_completeness_separate_not_applicable_is_not_field_partial(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """별도 문서의 subsidiary_status=not_applicable은 field_partial이 아니다."""
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


async def test_completeness_subsidiary_not_found_is_field_partial(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """연결 문서의 subsidiary_status=not_found는 field_partial이다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [_entry()],
        [_ok_fact(fs_scope="consolidated", subsidiary_status="not_found")],
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
    """실시내용 1–3절 ok이고 4절만 not_found면 제도상없음이라 부분실패가 아니다."""
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
    assert body["field_partial"] == 0
    assert body["all_success"] == 1


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
    assert body["all_success"] == 0
    assert body["unextracted"] == 0


async def test_completeness_ignores_f001_company_overview_attachment(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """F001 기업개황자료 첨부 facts는 대상·시도 실패에 넣지 않는다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [
            _entry(),
            _entry(
                entry_id="e-overview",
                dcm_no="99999",
                source="attachment",
                document_name="기업개황자료",
                section_name="기업개황자료",
                path=["기업개황자료"],
            ),
        ],
        [
            _ok_fact(),
            _ok_fact(
                rcept_no="20200331000001",
                dcm_no="99999",
                fetch_status="section_missing",
            ),
        ],
    )

    async with client_factory(app) as client:
        response = await client.get(
            "/admin/extract/audit-opinion/completeness",
            params={**COMPLETENESS_PARAMS, "status": "section_missing"},
            headers=TOKEN_HEADER,
        )

    body = response.json()
    assert response.status_code == 200
    assert body["target"] == 1
    assert body["ok"] == 1
    assert body["section_missing"] == 0
    assert body["items"] == []


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


async def test_field_bundles_exclude_stale_and_fetch_failed_and_classify(
    memory_app: tuple[FastAPI, object],
) -> None:
    """현재 버전 ok만 모집단. 별도 종속 NA, 4절만 없음은 제도상없음, 연결 종속 구멍은 실패."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [
            _entry(),
            _entry(
                entry_id="e-stale",
                rcept_no="20200331000002",
                dcm_no="22222",
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=2",
            ),
            _entry(
                entry_id="e-failfetch",
                rcept_no="20200331000003",
                dcm_no="33333",
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=3",
            ),
            _entry(
                entry_id="e-cons",
                rcept_no="20200331000004",
                dcm_no="44444",
                report_type="F002",
                document_name="연결감사보고서",
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=4",
            ),
        ],
        [
            _ok_fact(
                hours_status="ok",
                activities_status="ok",
                communications_status="not_found",
                subsidiary_status="not_applicable",
            ),
            _ok_fact(
                rcept_no="20200331000002",
                dcm_no="22222",
                extractor_version="audit_opinion.v2",
                opinion_status="not_found",
            ),
            _ok_fact(
                rcept_no="20200331000003",
                dcm_no="33333",
                fetch_status="fetch_failed",
                opinion_status="skipped",
            ),
            _ok_fact(
                rcept_no="20200331000004",
                dcm_no="44444",
                source_report_type="F002",
                fs_scope="consolidated",
                subsidiary_status="not_found",
            ),
        ],
    )
    async with sessionmaker() as session:
        summary = await CompletenessService(session).summarize_field_bundles(
            start_date="20200301",
            end_date="20200331",
        )
    by_key = {row.bundle: row for row in summary.bundles}
    assert summary.eligible == 2
    assert list(by_key) == list(BUNDLE_KEYS)
    assert by_key["subsidiary"].not_applicable == 1
    assert by_key["subsidiary"].fail == 1
    assert by_key["subsidiary"].ok == 0
    assert by_key["communications"].expected_missing == 1
    assert by_key["opinion"].ok == 2


async def test_field_bundle_sql_counts_match_python_rules(
    memory_app: tuple[FastAPI, object],
) -> None:
    """SQL SUM(CASE) 네 칸이 add_fact_outcomes와 같다."""
    _app, sessionmaker = memory_app
    facts = [
        _ok_fact(
            rcept_no="20200331000001",
            dcm_no="1",
            fs_scope="separate",
            subsidiary_status="not_applicable",
        ),
        _ok_fact(
            rcept_no="20200331000002",
            dcm_no="2",
            communications_status="not_found",
            hours_status="ok",
            activities_status="ok",
        ),
        _ok_fact(
            rcept_no="20200331000003",
            dcm_no="3",
            communications_status="not_found",
            hours_status="skipped",
            activities_status="ok",
        ),
        _ok_fact(
            rcept_no="20200331000004",
            dcm_no="4",
            source_report_type="F002",
            fs_scope="consolidated",
            subsidiary_status="not_found",
        ),
        _ok_fact(
            rcept_no="20200331000005",
            dcm_no="5",
            opinion_status="ok",
        ),
        _ok_fact(
            rcept_no="20200331000006",
            dcm_no="6",
            icfr_status="skipped",
        ),
        _ok_fact(
            rcept_no="20200331000007",
            dcm_no="7",
            source_report_type="F002",
            fs_scope="consolidated",
            icfr_status="skipped",
        ),
        _ok_fact(
            rcept_no="20200331000008",
            dcm_no="8",
            source_report_type="F002",
            fs_scope="consolidated",
            icfr_status="skipped",
        ),
    ]
    entries = [
        _entry(
            entry_id=f"e-{fact.rcept_no}",
            rcept_no=fact.rcept_no,
            dcm_no=fact.dcm_no,
            report_type=fact.source_report_type,
            year_end={
                "20200331000007": "(2022.12)",
                "20200331000008": "(2023.12)",
            }.get(fact.rcept_no, "(2019.12)"),
            viewer_url=f"https://dart.fss.or.kr/report/viewer.do?rcpNo={fact.rcept_no}",
        )
        for fact in facts
    ]
    await _seed(sessionmaker, entries, facts)
    await _seed_corp(sessionmaker, corp_cls="E")

    expected = empty_field_bundle_counts()
    disclosures = _disclosures_from_entries(entries)
    by_rcept = {row.rcept_no: row for row in disclosures}
    for fact in facts:
        if fact.fetch_status != "ok":
            continue
        disclosure = by_rcept[fact.rcept_no]
        add_fact_outcomes(
            expected,
            fact,
            corp_cls="E",
            period_year=icfr_period_year(disclosure.year_end, disclosure.rcept_dt),
        )

    async with sessionmaker() as session:
        summary = await CompletenessService(session).summarize_field_bundles(
            start_date="20200301",
            end_date="20200331",
        )

    by_key = {row.bundle: row for row in summary.bundles}
    for key in BUNDLE_KEYS:
        row = by_key[key]
        assert (
            row.ok,
            row.not_applicable,
            row.expected_missing,
            row.fail,
        ) == (
            expected[key]["ok"],
            expected[key]["not_applicable"],
            expected[key]["expected_missing"],
            expected[key]["fail"],
        )


async def test_field_bundle_fail_items_list_subsidiary_holes_only(
    memory_app: tuple[FastAPI, object],
) -> None:
    """실패 목록은 현재 버전 ok 모집단의 해당 묶음 구멍만 남기고 entry viewer_url을 붙인다."""
    _app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [
            _entry(),
            _entry(
                entry_id="e-stale",
                rcept_no="20200331000002",
                dcm_no="22222",
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=2",
            ),
            _entry(
                entry_id="e-failfetch",
                rcept_no="20200331000003",
                dcm_no="33333",
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=3",
            ),
            _entry(
                entry_id="e-cons",
                rcept_no="20200331000004",
                dcm_no="44444",
                report_type="F002",
                document_name="연결감사보고서",
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=4",
            ),
        ],
        [
            _ok_fact(
                hours_status="ok",
                activities_status="ok",
                communications_status="not_found",
                subsidiary_status="not_applicable",
            ),
            _ok_fact(
                rcept_no="20200331000002",
                dcm_no="22222",
                extractor_version="audit_opinion.v2",
                opinion_status="not_found",
            ),
            _ok_fact(
                rcept_no="20200331000003",
                dcm_no="33333",
                fetch_status="fetch_failed",
                opinion_status="skipped",
            ),
            _ok_fact(
                rcept_no="20200331000004",
                dcm_no="44444",
                source_report_type="F002",
                fs_scope="consolidated",
                subsidiary_status="not_found",
            ),
        ],
    )
    async with sessionmaker() as session:
        service = CompletenessService(session)
        listed = await service.list_field_bundle_fail_items(
            start_date="20200301",
            end_date="20200331",
            bundle="subsidiary",
            cursor=None,
            limit=50,
        )
        comms = await service.list_field_bundle_fail_items(
            start_date="20200301",
            end_date="20200331",
            bundle="communications",
            cursor=None,
            limit=50,
        )
    assert [(item.rcept_no, item.dcm_no) for item in listed.items] == [
        ("20200331000004", "44444")
    ]
    item = listed.items[0]
    assert item.report_type == "F002"
    assert item.fs_scope == "consolidated"
    assert item.bundle == "subsidiary"
    assert item.status == "not_found"
    assert item.extractor_version == EXTRACTOR_VERSION
    assert item.viewer_url == DART_DOCUMENT_VIEW.format(
        rcept_no="20200331000004", dcm_no="44444"
    )
    assert listed.next_cursor is None
    assert comms.items == []


async def test_field_bundle_fail_items_reject_unknown_bundle(
    memory_app: tuple[FastAPI, object],
) -> None:
    """bundle이 12개 키가 아니면 BadRequest다."""
    _app, sessionmaker = memory_app
    async with sessionmaker() as session:
        with pytest.raises(BadRequest, match="bundle은 12개 필드 키 중 하나여야 합니다"):
            await CompletenessService(session).list_field_bundle_fail_items(
                start_date="20200301",
                end_date="20200331",
                bundle="not-a-bundle",
                cursor=None,
                limit=50,
            )


async def test_field_bundle_fail_items_use_document_main_view(
    memory_app: tuple[FastAPI, object],
) -> None:
    """원문 링크는 섹션 viewer.do가 아니라 문서 전체 main.do다."""
    _app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [_entry(viewer_url=None)],
        [_ok_fact(opinion_status="not_found")],
    )
    async with sessionmaker() as session:
        listed = await CompletenessService(session).list_field_bundle_fail_items(
            start_date="20200301",
            end_date="20200331",
            bundle="opinion",
            cursor=None,
            limit=50,
        )
    assert listed.items[0].viewer_url == DART_DOCUMENT_VIEW.format(
        rcept_no="20200331000001",
        dcm_no="11111",
    )


async def test_field_bundle_fail_items_paginate_by_cursor(
    memory_app: tuple[FastAPI, object],
) -> None:
    """실패 목록은 rcept_no·dcm_no 순으로 limit·cursor 페이지를 잇는다."""
    _app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [
            _entry(entry_id="e1", rcept_no="20200331000001", dcm_no="111"),
            _entry(entry_id="e2", rcept_no="20200331000002", dcm_no="222"),
            _entry(entry_id="e3", rcept_no="20200331000003", dcm_no="333"),
        ],
        [
            _ok_fact(rcept_no="20200331000001", dcm_no="111", opinion_status="skipped"),
            _ok_fact(rcept_no="20200331000002", dcm_no="222", opinion_status="not_found"),
            _ok_fact(rcept_no="20200331000003", dcm_no="333", opinion_status="skipped"),
        ],
    )
    async with sessionmaker() as session:
        service = CompletenessService(session)
        page1 = await service.list_field_bundle_fail_items(
            start_date="20200301",
            end_date="20200331",
            bundle="opinion",
            cursor=None,
            limit=1,
        )
        page2 = await service.list_field_bundle_fail_items(
            start_date="20200301",
            end_date="20200331",
            bundle="opinion",
            cursor=page1.next_cursor,
            limit=1,
        )
    assert [(item.rcept_no, item.dcm_no) for item in page1.items] == [
        ("20200331000001", "111")
    ]
    assert page1.next_cursor
    assert [(item.rcept_no, item.dcm_no) for item in page2.items] == [
        ("20200331000002", "222")
    ]
    assert page2.next_cursor


async def test_field_bundles_api_requires_token(client_factory) -> None:
    """필드 묶음 집계도 Admin 토큰이 필요하다."""
    app = create_app()
    async with client_factory(app) as client:
        response = await client.get(
            "/admin/extract/audit-opinion/field-bundles",
            params={"start_date": "20200301", "end_date": "20200331"},
        )
    assert response.status_code == 401


async def test_field_bundle_items_reject_unknown_bundle(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """알 수 없는 bundle은 400이다."""
    app, _sessionmaker = memory_app
    async with client_factory(app) as client:
        response = await client.get(
            "/admin/extract/audit-opinion/field-bundles/items",
            params={
                "start_date": "20200301",
                "end_date": "20200331",
                "bundle": "nope",
                "outcome": "fail",
            },
            headers=TOKEN_HEADER,
        )
    assert response.status_code == 400
    assert "bundle" in response.json()["detail"]


async def test_field_bundle_export_tsv_and_fail_list(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """실패 목록과 TSV export가 동일 시드의 연결 종속 구멍을 반환한다."""
    app, sessionmaker = memory_app
    await _seed(
        sessionmaker,
        [
            _entry(
                report_type="F002",
                document_name="연결감사보고서",
            )
        ],
        [
            _ok_fact(
                source_report_type="F002",
                fs_scope="consolidated",
                subsidiary_status="not_found",
            )
        ],
    )
    params = {
        "start_date": "20200301",
        "end_date": "20200331",
        "bundle": "subsidiary",
        "outcome": "fail",
    }
    async with client_factory(app) as client:
        listing = await client.get(
            "/admin/extract/audit-opinion/field-bundles/items",
            params=params,
            headers=TOKEN_HEADER,
        )
        export = await client.get(
            "/admin/extract/audit-opinion/field-bundles/export",
            params=params,
            headers=TOKEN_HEADER,
        )
    assert listing.status_code == 200
    item = listing.json()["items"][0]
    assert item["report_type"] == "F002"
    assert item["dcm_no"] == "11111"
    assert item["status"] == "not_found"
    assert "viewer.do" in (item["viewer_url"] or "") or "rcpNo=" in (item["viewer_url"] or "")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/tab-separated-values")
    assert "report_type" in export.text.splitlines()[0]
    assert "F002" in export.text


async def test_field_bundle_items_reject_non_fail_outcome(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """outcome=ok는 400이다."""
    app, _sessionmaker = memory_app
    async with client_factory(app) as client:
        response = await client.get(
            "/admin/extract/audit-opinion/field-bundles/items",
            params={
                "start_date": "20200301",
                "end_date": "20200331",
                "bundle": "opinion",
                "outcome": "ok",
            },
            headers=TOKEN_HEADER,
        )
    assert response.status_code == 400
    assert "outcome" in response.json()["detail"]

