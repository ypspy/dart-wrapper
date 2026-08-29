"""ambiguous 감사보고서일 LLM 해소 잡 테스트. 실제 LLM은 호출하지 않는다."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.extracting.constants import EXTRACTOR_VERSION
from app.main import create_app
from app.models.audit_report_fact import AuditReportFact
from app.models.extraction_job import ExtractionJob
from app.repositories.entry_repository import EntryRepository
from app.repositories.extraction_job_repository import ExtractionJobRepository
from app.repositories.fact_repository import FactRepository
from app.repositories.job_repository import JobRepository
from app.schemas.entry import EntryRecord

TOKEN_HEADER = {"X-Admin-Token": "dev-admin-token"}

CANDIDATES = [
    {
        "date_raw": "2020년2월1일",
        "date": "2020-02-01",
        "snippet": "머리 2020년2월1일 의견",
    },
    {
        "date_raw": "2020년3월15일",
        "date": "2020-03-15",
        "snippet": "서명 2020년3월15일",
    },
]


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


class FakeDateResolver:
    """테스트용 DateResolver. HTTP/LLM을 호출하지 않는다."""

    def __init__(self, index: int | None, raw: str = '{"index": 1}') -> None:
        self._index = index
        self.last_raw_response = raw
        self.calls: list[dict[str, object]] = []

    async def pick_index(
        self,
        *,
        candidates: list[dict],
        period_end: str,
        rcept_dt: str,
    ) -> int | None:
        self.calls.append(
            {
                "candidates": candidates,
                "period_end": period_end,
                "rcept_dt": rcept_dt,
            }
        )
        return self._index


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


def _ambiguous_fact(**overrides: object) -> AuditReportFact:
    values: dict[str, object] = {
        "rcept_no": "20200331000001",
        "dcm_no": "11111",
        "source_report_type": "F001",
        "fs_scope": "separate",
        "auditor_status": "ok",
        "opinion_status": "ok",
        "gaap_status": "ok",
        "audit_report_date_status": "ambiguous",
        "audit_report_date": None,
        "audit_report_date_source": None,
        "current_period_status": "ok",
        "fetch_status": "ok",
        "conflicts": [],
        "audit_report_date_candidates": list(CANDIDATES),
        "extractor_version": EXTRACTOR_VERSION,
    }
    values.update(overrides)
    return AuditReportFact(**values)


async def _seed(
    sessionmaker,
    *,
    entries: list[EntryRecord] | None = None,
    facts: list[AuditReportFact] | None = None,
) -> None:
    async with sessionmaker() as session:
        if entries:
            await EntryRepository(session).upsert_many(entries)
        facts_repo = FactRepository(session)
        for fact in facts or []:
            await facts_repo.upsert(fact)
        await session.commit()


def _service(sessionmaker, resolver: FakeDateResolver):
    from app.services.date_resolver_service import DateResolverService

    return DateResolverService(
        sessionmaker,
        resolver,
        model="gpt-4o-mini",
        prompt_version="v1",
    )


async def test_run_stores_second_candidate_iso_when_resolver_returns_one(
    sessionmaker_fixture,
) -> None:
    """mock이 1을 주면 두 후보 중 두 번째 ISO가 채워지고 source는 llm이다."""
    await _seed(
        sessionmaker_fixture,
        entries=[_entry()],
        facts=[_ambiguous_fact()],
    )
    resolver = FakeDateResolver(1)
    service = _service(sessionmaker_fixture, resolver)
    job_id = await service.start()
    await service.run(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")
        job = await session.get(ExtractionJob, job_id)

    assert job is not None and job.status == "succeeded"
    assert job.extractor_id == "resolve_dates"
    assert fact is not None
    assert fact.audit_report_date == "2020-03-15"
    assert fact.audit_report_date_status == "ok"
    assert fact.audit_report_date_source == "llm"
    assert fact.date_resolver_model == "gpt-4o-mini"
    assert fact.date_resolver_prompt_version == "v1"
    assert fact.date_resolver_raw_response == '{"index": 1}'
    assert resolver.calls == [
        {
            "candidates": [
                {"date_raw": "2020년2월1일", "snippet": "머리 2020년2월1일 의견"},
                {"date_raw": "2020년3월15일", "snippet": "서명 2020년3월15일"},
            ],
            "period_end": "2019-12-31",
            "rcept_dt": "2020-03-31",
        }
    ]


async def test_run_maps_task7_date_key_into_llm_date_raw(
    sessionmaker_fixture,
) -> None:
    """추출 후보가 date+snippet만 있어도 LLM에는 ISO가 date_raw로 간다."""
    stored = [
        {"date": "2020-02-01", "snippet": "머리 2020년2월1일 의견"},
        {"date": "2020-03-15", "snippet": "서명 2020년3월15일"},
    ]
    await _seed(
        sessionmaker_fixture,
        entries=[_entry()],
        facts=[_ambiguous_fact(audit_report_date_candidates=stored)],
    )
    resolver = FakeDateResolver(1)
    service = _service(sessionmaker_fixture, resolver)
    job_id = await service.start()
    await service.run(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.audit_report_date == "2020-03-15"
    assert fact.audit_report_date_source == "llm"
    assert resolver.calls
    candidates = resolver.calls[0]["candidates"]
    assert candidates == [
        {"date_raw": "2020-02-01", "snippet": "머리 2020년2월1일 의견"},
        {"date_raw": "2020-03-15", "snippet": "서명 2020년3월15일"},
    ]


@pytest.mark.parametrize("index", [-1, None])
async def test_run_keeps_ambiguous_when_resolver_returns_invalid_index(
    sessionmaker_fixture,
    index: int | None,
) -> None:
    """mock이 -1 또는 None을 주면 날짜는 ambiguous로 남는다."""
    await _seed(
        sessionmaker_fixture,
        entries=[_entry()],
        facts=[_ambiguous_fact()],
    )
    resolver = FakeDateResolver(index, raw='{"index": null}')
    service = _service(sessionmaker_fixture, resolver)
    job_id = await service.start()
    await service.run(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.audit_report_date is None
    assert fact.audit_report_date_status == "ambiguous"
    assert fact.audit_report_date_source is None
    assert fact.date_resolver_model is None


async def test_run_keeps_ambiguous_when_llm_picks_out_of_window(
    sessionmaker_fixture,
) -> None:
    """창 밖 ISO를 골라도 ok로 쓰지 않고 ambiguous로 둔다."""
    stored = [
        {
            "date_raw": "2020년2월1일",
            "date": "2020-02-01",
            "snippet": "머리 2020년2월1일",
        },
        {
            "date_raw": "2018년6월1일",
            "date": "2018-06-01",
            "snippet": "옛날짜 2018년6월1일",
        },
    ]
    await _seed(
        sessionmaker_fixture,
        entries=[_entry()],
        facts=[_ambiguous_fact(audit_report_date_candidates=stored)],
    )
    resolver = FakeDateResolver(1)
    service = _service(sessionmaker_fixture, resolver)
    job_id = await service.start()
    await service.run(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.audit_report_date is None
    assert fact.audit_report_date_status == "ambiguous"
    assert fact.audit_report_date_source is None
    assert fact.date_resolver_model is None


async def test_start_rejects_second_active_resolve_dates_job(
    sessionmaker_fixture,
) -> None:
    """이미 진행 중인 resolve_dates 잡이 있으면 CatalogConflict다."""
    from app.errors import CatalogConflict

    await _seed(
        sessionmaker_fixture,
        entries=[_entry()],
        facts=[_ambiguous_fact()],
    )
    service = _service(sessionmaker_fixture, FakeDateResolver(1))
    await service.start()
    with pytest.raises(CatalogConflict, match="이미 진행 중"):
        await service.start()


async def test_run_does_not_take_dart_lock(sessionmaker_fixture) -> None:
    """날짜 해소는 DART 잠금 없이 수집·추출이 살아 있어도 돈다."""
    await _seed(
        sessionmaker_fixture,
        entries=[_entry()],
        facts=[_ambiguous_fact()],
    )
    async with sessionmaker_fixture() as session:
        await JobRepository(session).create(
            "cat-1",
            {"report_type": "F001"},
            '{"report_type":"F001"}',
            mode="collect",
        )
        await ExtractionJobRepository(session).create(
            "extract-1", "audit_opinion", {}, mode="extract"
        )
        await session.commit()

    resolver = FakeDateResolver(1)
    service = _service(sessionmaker_fixture, resolver)
    job_id = await service.start()
    await service.run(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.audit_report_date == "2020-03-15"
    assert fact.audit_report_date_source == "llm"


def _openai_response(content: str, status: int = 200) -> httpx.Response:
    body = {
        "id": "chatcmpl-test",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    return httpx.Response(status, json=body)


async def _parse_index(content: str, candidate_count: int = 2) -> int | None:
    from app.adapters.llm_date_resolver import LlmDateResolver

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _openai_response(content)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = LlmDateResolver(
            client,
            api_key="sk-test",
            model="gpt-4o-mini",
            prompt_version="v1",
        )
        index = await adapter.pick_index(
            candidates=[
                {"date_raw": "2020년2월1일", "snippet": "머리"},
                {"date_raw": "2020년3월15일", "snippet": "서명"},
            ][:candidate_count],
            period_end="2019-12-31",
            rcept_dt="2020-03-31",
        )
    return index, captured, adapter


async def test_llm_adapter_parses_index_json() -> None:
    """어댑터는 응답 JSON의 index만 읽어 정수로 돌려준다."""
    index, captured, adapter = await _parse_index('{"index": 1}')

    assert index == 1
    assert adapter.last_raw_response == '{"index": 1}'
    assert captured
    request = captured[0]
    assert "chat/completions" in str(request.url)
    payload = json.loads(request.content.decode("utf-8"))
    assert payload["model"] == "gpt-4o-mini"
    assert payload["temperature"] == 0
    assert request.headers["authorization"] == "Bearer sk-test"


async def test_llm_adapter_null_index_returns_none() -> None:
    """{"index": null}은 고를 수 없음이므로 None이다."""
    index, _captured, adapter = await _parse_index('{"index": null}')

    assert index is None
    assert adapter.last_raw_response == '{"index": null}'


@pytest.mark.parametrize(
    "content",
    [
        '{"index": 5}',
        '{"index": -1}',
        "not-json",
        '{"other": 0}',
        "",
    ],
)
async def test_llm_adapter_out_of_range_or_parse_failure_returns_none(
    content: str,
) -> None:
    """범위 밖 인덱스와 JSON 파싱 실패는 None이다."""
    index, _captured, adapter = await _parse_index(content)

    assert index is None
    assert adapter.last_raw_response == content


async def test_llm_adapter_posts_with_longer_timeout() -> None:
    """OpenAI POST는 공유 클라이언트 기본 5초가 아니라 명시 타임아웃을 쓴다."""
    from app.adapters.llm_date_resolver import LlmDateResolver

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _openai_response('{"index": 0}')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = LlmDateResolver(client, api_key="sk-test")
        await adapter.pick_index(
            candidates=[{"date_raw": "2020-03-15", "snippet": "서명"}],
            period_end="2019-12-31",
            rcept_dt="2020-03-31",
        )

    assert captured
    timeout = captured[0].extensions["timeout"]
    assert timeout["read"] == 30.0
    assert timeout["connect"] == 30.0


async def test_llm_adapter_http_error_returns_none() -> None:
    """HTTP 오류도 실제 LLM을 재시도하지 않고 None을 준다."""
    from app.adapters.llm_date_resolver import LlmDateResolver

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream error")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = LlmDateResolver(client, api_key="sk-test")
        index = await adapter.pick_index(
            candidates=[{"date_raw": "2020년2월1일", "snippet": "머리"}],
            period_end="2019-12-31",
            rcept_dt="2020-03-31",
        )

    assert index is None


class FakeDateResolverService:
    """라우트가 start·run을 호출하는지 기록한다."""

    def __init__(self) -> None:
        self.started = 0
        self.executed: list[str] = []

    async def start(self) -> str:
        self.started += 1
        return "job-dates-1"

    async def run(self, job_id: str) -> None:
        self.executed.append(job_id)


def _app_with_resolver(service: FakeDateResolverService, api_key: str = "sk-test"):
    from app.api.deps import get_date_resolver_service, get_settings_dep
    from app.config import Settings

    app = create_app()
    app.dependency_overrides[get_date_resolver_service] = lambda: service
    app.dependency_overrides[get_settings_dep] = lambda: Settings(
        date_resolver_api_key=api_key
    )
    return app


async def test_resolve_dates_requires_admin_token(client_factory) -> None:
    """날짜 해소 트리거도 Admin 토큰이 필요하다."""
    app = create_app()

    async with client_factory(app) as client:
        response = await client.post("/admin/extract/resolve-dates")

    assert response.status_code == 401
    assert "토큰" in response.json()["detail"]


async def test_resolve_dates_rejects_missing_api_key(client_factory) -> None:
    """API 키가 없으면 400과 친절한 한국어 안내를 준다."""
    service = FakeDateResolverService()

    async with client_factory(_app_with_resolver(service, "")) as client:
        response = await client.post(
            "/admin/extract/resolve-dates", headers=TOKEN_HEADER
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "키" in detail
    assert service.started == 0


async def test_resolve_dates_accepts_request_and_schedules_job(
    client_factory,
) -> None:
    """토큰과 API 키가 있으면 202과 job_id를 주고 run을 백그라운드로 돌린다."""
    service = FakeDateResolverService()

    async with client_factory(_app_with_resolver(service)) as client:
        response = await client.post(
            "/admin/extract/resolve-dates", headers=TOKEN_HEADER
        )

    assert response.status_code == 202
    assert response.json()["job_id"] == "job-dates-1"
    assert response.json()["status"] == "pending"
    assert service.started == 1
    assert service.executed == ["job-dates-1"]


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


async def test_resolve_dates_end_to_end_with_fake_resolver(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """주입한 fake resolver로 실제 서비스가 두 번째 ISO를 저장한다."""
    from app.api.deps import get_date_resolver_service, get_settings_dep
    from app.config import Settings
    from app.services.date_resolver_service import DateResolverService

    app, sessionmaker = memory_app
    await _seed(sessionmaker, entries=[_entry()], facts=[_ambiguous_fact()])
    resolver = FakeDateResolver(1)
    service = DateResolverService(
        sessionmaker, resolver, model="gpt-4o-mini", prompt_version="v1"
    )
    app.dependency_overrides[get_date_resolver_service] = lambda: service
    app.dependency_overrides[get_settings_dep] = lambda: Settings(
        date_resolver_api_key="sk-test"
    )

    async with client_factory(app) as client:
        response = await client.post(
            "/admin/extract/resolve-dates", headers=TOKEN_HEADER
        )

    assert response.status_code == 202
    async with sessionmaker() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.audit_report_date == "2020-03-15"
    assert fact.audit_report_date_source == "llm"
