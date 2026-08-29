"""DART 잡 잠금과 감사 추출 오케스트레이션 테스트."""

from __future__ import annotations

import httpx
import pytest

from app.adapters.dart_http import DartHttpClient
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import CatalogConflict
from app.models.audit_report_fact import AuditReportFact
from app.models.extraction_job import ExtractionJob
from app.repositories.entry_repository import EntryRepository
from app.repositories.extraction_job_repository import ExtractionJobRepository
from app.repositories.fact_repository import FactRepository
from app.repositories.job_repository import JobRepository
from app.schemas.entry import EntryRecord
from app.services.extraction_service import ExtractionService

COVER_URL = "https://dart.fss.or.kr/report/viewer.do?rcpNo=1&eleId=cover"
OPINION_URL = "https://dart.fss.or.kr/report/viewer.do?rcpNo=1&eleId=opinion"
A001_OPINION_URL = "https://dart.fss.or.kr/report/viewer.do?rcpNo=2&eleId=opinion"

COVER_HTML = """
<html><body>
<table>
<tr><td>감사보고서</td></tr>
</table>
<table>
<tr><td>제51기</td><td>2019.01.01부터 2019.12.31까지</td></tr>
</table>
<table>
<tr><td>삼일회계법인</td></tr>
</table>
</body></html>
"""

OPINION_HTML = """
<html><body>
<p>독립된 감사인의 감사보고서</p>
<p>감사의견</p>
<p>우리는 첨부된 재무제표를 감사하였습니다.</p>
<p>한국채택국제회계기준에따라 작성되었습니다.</p>
<p>2020년 2월 20일</p>
</body></html>
"""

QUALIFIED_OPINION_HTML = """
<html><body>
<p>독립된 감사인의 감사보고서</p>
<p>감사의견</p>
<p>한정의견근거단락에기술된사항이미치는영향을제외하고 적정합니다.</p>
<p>한국채택국제회계기준에따라 작성되었습니다.</p>
<p>2020년 2월 20일</p>
</body></html>
"""


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
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
        "viewer_url": COVER_URL,
    }
    values.update(overrides)
    return EntryRecord.model_validate(values)


def _f001_leaves() -> list[EntryRecord]:
    return [
        _entry(),
        _entry(
            entry_id="e-opinion",
            section_name="독립된 감사인의 감사보고서",
            path=["독립된 감사인의 감사보고서"],
            viewer_url=OPINION_URL,
        ),
    ]


def _html_handler(
    mapping: dict[str, tuple[int, str]],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        status, body = mapping.get(str(request.url), (404, "없음"))
        return httpx.Response(status, text=body)

    return httpx.MockTransport(handler)


def _service(
    sessionmaker,
    mapping: dict[str, tuple[int, str]] | None = None,
    **kwargs: object,
) -> tuple[ExtractionService, httpx.AsyncClient]:
    transport = _html_handler(
        mapping
        or {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
        }
    )
    client = httpx.AsyncClient(transport=transport)
    http = DartHttpClient(client, max_retries=0, retry_backoff_seconds=0.0)
    return ExtractionService(sessionmaker, http, **kwargs), client


async def _seed_entries(sessionmaker, records: list[EntryRecord]) -> None:
    async with sessionmaker() as session:
        await EntryRepository(session).upsert_many(records)
        await session.commit()


async def test_extract_f001_cover_and_opinion_saves_unqualified_fact(
    sessionmaker_fixture,
) -> None:
    """Mock HTTP로 F001 표지·의견 HTML을 주면 facts 1행과 적정 의견이 저장된다."""
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    service, client = _service(sessionmaker_fixture)
    async with client:
        job_id = await service.start(
            "20200301", "20200331", ["F001"], "extract"
        )
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        rows = await FactRepository(session).list_by_rcept_no("20200331000001")
        job = await session.get(ExtractionJob, job_id)

    assert job is not None and job.status == "succeeded"
    assert len(rows) == 1
    fact = rows[0]
    assert fact.dcm_no == "11111"
    assert fact.source_report_type == "F001"
    assert fact.fs_scope == "separate"
    assert fact.fetch_status == "ok"
    assert fact.opinion_code == "unqualified"
    assert fact.opinion_status == "ok"
    assert fact.extractor_version == "audit_opinion.v1"


async def test_start_raises_when_catalog_running(sessionmaker_fixture) -> None:
    """카탈로그 수집이 진행 중이면 추출 시작이 CatalogConflict를 낸다."""
    async with sessionmaker_fixture() as session:
        await JobRepository(session).create(
            "cat-1",
            {"report_type": "F001"},
            '{"report_type":"F001"}',
            mode="collect",
        )
        await session.commit()

    service, client = _service(sessionmaker_fixture)
    async with client:
        with pytest.raises(CatalogConflict, match="이미 진행 중"):
            await service.start("20200301", "20200331", ["F001"], "extract")


async def test_start_allows_when_only_resolve_dates_is_active(
    sessionmaker_fixture,
) -> None:
    """날짜 LLM 잡은 DART를 치지 않으므로 추출 시작을 막지 않는다."""
    async with sessionmaker_fixture() as session:
        await ExtractionJobRepository(session).create(
            "dates-1", "resolve_dates", {}, mode="extract"
        )
        await session.commit()

    service, client = _service(sessionmaker_fixture)
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")

    assert job_id


async def test_list_for_extraction_uses_dotted_rcept_dt(
    sessionmaker_fixture,
) -> None:
    """기간 필터는 YYYYMMDD 입력을 저장된 YYYY.MM.DD 접수일과 맞춘다."""
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f001_leaves(),
            _entry(
                entry_id="e-out",
                rcept_no="20200401000001",
                rcept_dt="2020.04.01",
                dcm_no="99999",
            ),
        ],
    )
    service, client = _service(sessionmaker_fixture)
    async with client:
        job_id = await service.start(
            "20200301", "20200331", ["F001"], "extract"
        )
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        in_range = await FactRepository(session).list_by_rcept_no("20200331000001")
        out_of_range = await FactRepository(session).list_by_rcept_no("20200401000001")

    assert len(in_range) == 1
    assert out_of_range == []


async def test_fetch_error_sets_fetch_failed(sessionmaker_fixture) -> None:
    """원문 fetch가 SourceFetchError이면 fetch_status는 fetch_failed이다."""
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (500, "error"),
            OPINION_URL: (500, "error"),
        },
    )
    async with client:
        job_id = await service.start(
            "20200301", "20200331", ["F001"], "extract"
        )
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.fetch_status == "fetch_failed"


async def test_block_page_sets_blocked(sessionmaker_fixture) -> None:
    """차단·캡차 페이지로 보이는 HTML이면 fetch_status는 blocked이다."""
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    block_html = "<html><body>비정상적인 접근이 감지되었습니다. captcha</body></html>"
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, block_html),
            OPINION_URL: (200, OPINION_HTML),
        },
    )
    async with client:
        job_id = await service.start(
            "20200301", "20200331", ["F001"], "extract"
        )
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.fetch_status == "blocked"


async def test_section_missing_when_cover_and_opinion_leaves_absent(
    sessionmaker_fixture,
) -> None:
    """표지·의견 leaf가 둘 다 없으면 fetch_status는 section_missing이다."""
    await _seed_entries(
        sessionmaker_fixture,
        [
            _entry(
                entry_id="e-notes",
                section_name="주석",
                path=["주석"],
                viewer_url=COVER_URL,
            )
        ],
    )
    service, client = _service(sessionmaker_fixture)
    async with client:
        job_id = await service.start(
            "20200301", "20200331", ["F001"], "extract"
        )
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.fetch_status == "section_missing"


async def test_resume_skips_ok_facts(sessionmaker_fixture) -> None:
    """fetch_status가 ok인 행은 resume에서 다시 fetch하지 않는다."""
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    async with sessionmaker_fixture() as session:
        await FactRepository(session).upsert(
            AuditReportFact(
                rcept_no="20200331000001",
                dcm_no="11111",
                source_report_type="F001",
                fs_scope="separate",
                fetch_status="ok",
                opinion_code="unqualified",
                opinion_status="ok",
                conflicts=[],
                audit_report_date_candidates=[],
            )
        )
        await session.commit()

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=OPINION_HTML)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        http = DartHttpClient(client, max_retries=0, retry_backoff_seconds=0.0)
        service = ExtractionService(sessionmaker_fixture, http)
        job_id = await service.start(
            "20200301", "20200331", ["F001"], "resume"
        )
        await service.run_job(job_id)

    assert calls == []


async def test_reparse_refetches_when_field_is_not_found(
    sessionmaker_fixture,
) -> None:
    """reparse는 fetch_status가 ok여도 not_found 필드가 있으면 다시 가져온다."""
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    async with sessionmaker_fixture() as session:
        await FactRepository(session).upsert(
            AuditReportFact(
                rcept_no="20200331000001",
                dcm_no="11111",
                source_report_type="F001",
                fs_scope="separate",
                fetch_status="ok",
                opinion_status="not_found",
                conflicts=[],
                audit_report_date_candidates=[],
            )
        )
        await session.commit()

    service, client = _service(sessionmaker_fixture)
    async with client:
        job_id = await service.start(
            "20200301", "20200331", ["F001"], "reparse"
        )
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.opinion_code == "unqualified"
    assert fact.opinion_status == "ok"


async def test_start_raises_when_audit_extraction_running(
    sessionmaker_fixture,
) -> None:
    """감사 추출이 이미 진행 중이면 새 추출 시작이 CatalogConflict를 낸다."""
    service, client = _service(sessionmaker_fixture)
    async with client:
        await service.start("20200301", "20200331", ["F001"], "extract")
        with pytest.raises(CatalogConflict, match="이미 진행 중"):
            await service.start("20200301", "20200331", ["F001"], "extract")


async def test_sibling_opinion_conflict_on_both_rows(sessionmaker_fixture) -> None:
    """같은 기업·결산월·범위에서 F001과 A001 의견이 다르면 양쪽에 sibling_opinion."""
    a001_cover = "https://dart.fss.or.kr/report/viewer.do?rcpNo=2&eleId=cover"
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f001_leaves(),
            _entry(
                entry_id="a-cover",
                rcept_no="20200331000002",
                report_type="A001",
                source="attachment",
                dcm_no="22222",
                document_name="감사보고서",
                section_name="감사보고서",
                viewer_url=a001_cover,
            ),
            _entry(
                entry_id="a-opinion",
                rcept_no="20200331000002",
                report_type="A001",
                source="attachment",
                dcm_no="22222",
                document_name="감사보고서",
                section_name="독립된 감사인의 감사보고서",
                viewer_url=A001_OPINION_URL,
            ),
        ],
    )
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            a001_cover: (200, COVER_HTML),
            A001_OPINION_URL: (200, QUALIFIED_OPINION_HTML),
        },
    )
    async with client:
        job_id = await service.start(
            "20200301", "20200331", ["F001", "A001"], "extract"
        )
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        f001 = await FactRepository(session).get("20200331000001", "11111")
        a001 = await FactRepository(session).get("20200331000002", "22222")

    assert f001 is not None and a001 is not None
    assert f001.opinion_code == "unqualified"
    assert a001.opinion_code == "qualified"
    assert any(c.get("field") == "sibling_opinion" for c in f001.conflicts)
    assert any(c.get("field") == "sibling_opinion" for c in a001.conflicts)


async def test_reparse_preserves_override_and_resolver_columns(
    sessionmaker_fixture,
) -> None:
    """reparse upsert는 override·LLM 컬럼과 override 보고일을 유지한다."""
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    async with sessionmaker_fixture() as session:
        await FactRepository(session).upsert(
            AuditReportFact(
                rcept_no="20200331000001",
                dcm_no="11111",
                source_report_type="F001",
                fs_scope="separate",
                fetch_status="ok",
                opinion_status="not_found",
                audit_report_date_override="2020-02-21",
                audit_report_date="2020-02-21",
                audit_report_date_status="ok",
                audit_report_date_source="override",
                date_resolver_model="gpt-test",
                date_resolver_prompt_version="prompt.v1",
                date_resolver_raw_response='{"index":0}',
                conflicts=[],
                audit_report_date_candidates=[],
            )
        )
        await session.commit()

    service, client = _service(sessionmaker_fixture)
    async with client:
        job_id = await service.start(
            "20200301", "20200331", ["F001"], "reparse"
        )
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.audit_report_date_override == "2020-02-21"
    assert fact.date_resolver_model == "gpt-test"
    assert fact.date_resolver_prompt_version == "prompt.v1"
    assert fact.date_resolver_raw_response == '{"index":0}'
    assert fact.audit_report_date == "2020-02-21"
    assert fact.audit_report_date_status == "ok"
    assert fact.audit_report_date_source == "override"
    assert fact.opinion_code == "unqualified"


async def test_document_exception_continues_remaining(
    sessionmaker_fixture,
) -> None:
    """한 문서 예외는 fetch_failed로 남기고 다음 문서는 추출·성공으로 끝낸다."""
    cover2 = "https://dart.fss.or.kr/report/viewer.do?rcpNo=2&eleId=cover"
    opinion2 = "https://dart.fss.or.kr/report/viewer.do?rcpNo=2&eleId=opinion"
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f001_leaves(),
            _entry(
                entry_id="e2-cover",
                rcept_no="20200331000002",
                dcm_no="22222",
                viewer_url=cover2,
            ),
            _entry(
                entry_id="e2-opinion",
                rcept_no="20200331000002",
                dcm_no="22222",
                section_name="독립된 감사인의 감사보고서",
                path=["독립된 감사인의 감사보고서"],
                viewer_url=opinion2,
            ),
        ],
    )

    class _BoomHttp:
        """첫 문서 leaf만 예상 밖 예외를 내고 나머지는 위임한다."""

        def __init__(self, inner: DartHttpClient) -> None:
            self._inner = inner

        async def fetch_html(self, url: str) -> str:
            if url in {COVER_URL, OPINION_URL}:
                raise RuntimeError("의도한 문서 예외")
            return await self._inner.fetch_html(url)

    inner, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            cover2: (200, COVER_HTML),
            opinion2: (200, OPINION_HTML),
        },
    )
    service = ExtractionService(sessionmaker_fixture, _BoomHttp(inner._http))
    async with client:
        job_id = await service.start(
            "20200301", "20200331", ["F001"], "extract"
        )
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        first = await FactRepository(session).get("20200331000001", "11111")
        second = await FactRepository(session).get("20200331000002", "22222")
        job = await session.get(ExtractionJob, job_id)

    assert first is not None
    assert first.fetch_status == "fetch_failed"
    assert second is not None
    assert second.fetch_status == "ok"
    assert second.opinion_code == "unqualified"
    assert job is not None
    assert job.status == "succeeded"


async def test_block_streak_stops_job_after_threshold(sessionmaker_fixture) -> None:
    """연속 blocked가 임계치에 이르면 남은 문서는 건드리지 않고 잡을 실패로 멈춘다."""
    cover2 = "https://dart.fss.or.kr/report/viewer.do?rcpNo=2&eleId=cover"
    opinion2 = "https://dart.fss.or.kr/report/viewer.do?rcpNo=2&eleId=opinion"
    cover3 = "https://dart.fss.or.kr/report/viewer.do?rcpNo=3&eleId=cover"
    opinion3 = "https://dart.fss.or.kr/report/viewer.do?rcpNo=3&eleId=opinion"
    block_html = "<html><body>비정상적인 접근이 감지되었습니다. captcha</body></html>"
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f001_leaves(),
            _entry(
                entry_id="e2-cover",
                rcept_no="20200331000002",
                dcm_no="22222",
                viewer_url=cover2,
            ),
            _entry(
                entry_id="e2-opinion",
                rcept_no="20200331000002",
                dcm_no="22222",
                section_name="독립된 감사인의 감사보고서",
                path=["독립된 감사인의 감사보고서"],
                viewer_url=opinion2,
            ),
            _entry(
                entry_id="e3-cover",
                rcept_no="20200331000003",
                dcm_no="33333",
                viewer_url=cover3,
            ),
            _entry(
                entry_id="e3-opinion",
                rcept_no="20200331000003",
                dcm_no="33333",
                section_name="독립된 감사인의 감사보고서",
                path=["독립된 감사인의 감사보고서"],
                viewer_url=opinion3,
            ),
        ],
    )
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, block_html),
            OPINION_URL: (200, block_html),
            cover2: (200, block_html),
            opinion2: (200, block_html),
            cover3: (200, COVER_HTML),
            opinion3: (200, OPINION_HTML),
        },
        block_streak_threshold=2,
        block_wait_seconds=0.0,
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        first = await FactRepository(session).get("20200331000001", "11111")
        second = await FactRepository(session).get("20200331000002", "22222")
        third = await FactRepository(session).get("20200331000003", "33333")
        job = await session.get(ExtractionJob, job_id)

    assert first is not None and first.fetch_status == "blocked"
    assert second is not None and second.fetch_status == "blocked"
    assert third is None
    assert job is not None
    assert job.status == "failed"
    assert job.error_message is not None
    assert "차단" in job.error_message


async def test_reparse_preserves_llm_resolved_date(sessionmaker_fixture) -> None:
    """reparse는 override가 없어도 LLM 해소 날짜·상태·출처를 유지한다."""
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    async with sessionmaker_fixture() as session:
        await FactRepository(session).upsert(
            AuditReportFact(
                rcept_no="20200331000001",
                dcm_no="11111",
                source_report_type="F001",
                fs_scope="separate",
                fetch_status="ok",
                opinion_status="not_found",
                audit_report_date="2020-02-21",
                audit_report_date_status="ok",
                audit_report_date_source="llm",
                date_resolver_model="gpt-test",
                date_resolver_prompt_version="prompt.v1",
                date_resolver_raw_response='{"index":0}',
                conflicts=[],
                audit_report_date_candidates=[],
            )
        )
        await session.commit()

    service, client = _service(sessionmaker_fixture)
    async with client:
        job_id = await service.start(
            "20200301", "20200331", ["F001"], "reparse"
        )
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.audit_report_date == "2020-02-21"
    assert fact.audit_report_date_status == "ok"
    assert fact.audit_report_date_source == "llm"
    assert fact.date_resolver_model == "gpt-test"
    assert fact.opinion_code == "unqualified"


A001_COVER_HTML = """
<html><body>
<table>
<tr><td>회사명</td><td>현대자동차주식회사</td></tr>
<tr><td>제51기</td><td>2019.01.01부터 2019.12.31까지</td></tr>
</table>
</body></html>
"""


async def test_a001_cover_company_name_feeds_corp_name_conflicts(
    sessionmaker_fixture,
) -> None:
    """같은 접수의 A001 표지 회사명이 목록명과 다르면 corp_name conflict를 남긴다."""
    a001_cover = "https://dart.fss.or.kr/report/viewer.do?rcpNo=1&eleId=a001cover"
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f001_leaves(),
            _entry(
                entry_id="a001-cover",
                report_type="A001",
                source="body",
                dcm_no="99999",
                document_name="사업보고서",
                section_name="사업보고서",
                viewer_url=a001_cover,
            ),
        ],
    )
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            a001_cover: (200, A001_COVER_HTML),
        },
    )
    async with client:
        job_id = await service.start(
            "20200301", "20200331", ["F001", "A001"], "extract"
        )
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    matches = [c for c in fact.conflicts if c.get("field") == "corp_name"]
    assert matches
    assert any(c.get("right_source") == "a001_cover" for c in matches)
    assert any("현대자동차" in (c.get("right") or "") for c in matches)


async def test_run_job_extracts_two_filings_without_loading_all_leaves_at_once(
    sessionmaker_fixture,
) -> None:
    """접수번호 목록만 먼저 읽고 접수마다 leaf를 가져와 두 문서를 모두 추출한다."""
    cover2 = "https://dart.fss.or.kr/report/viewer.do?rcpNo=2&eleId=cover"
    opinion2 = "https://dart.fss.or.kr/report/viewer.do?rcpNo=2&eleId=opinion"
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f001_leaves(),
            _entry(
                entry_id="e2-cover",
                rcept_no="20200331000002",
                dcm_no="22222",
                viewer_url=cover2,
            ),
            _entry(
                entry_id="e2-opinion",
                rcept_no="20200331000002",
                dcm_no="22222",
                section_name="독립된 감사인의 감사보고서",
                path=["독립된 감사인의 감사보고서"],
                viewer_url=opinion2,
            ),
        ],
    )
    async with sessionmaker_fixture() as session:
        rcept_nos = await EntryRepository(session).list_rcept_nos_for_extraction(
            "20200301", "20200331", ["F001"]
        )
    assert rcept_nos == ["20200331000001", "20200331000002"]

    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            cover2: (200, COVER_HTML),
            opinion2: (200, OPINION_HTML),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        first = await FactRepository(session).get("20200331000001", "11111")
        second = await FactRepository(session).get("20200331000002", "22222")

    assert first is not None and first.fetch_status == "ok"
    assert second is not None and second.fetch_status == "ok"


async def test_soft_stop_before_run_saves_nothing_and_marks_partial(
    sessionmaker_fixture,
) -> None:
    """run_job 전에 중단을 요청하면 문서를 추출하지 않고 partial로 끝낸다."""
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    service, client = _service(sessionmaker_fixture)
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.request_soft_stop(job_id)
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        rows = await FactRepository(session).list_by_rcept_no("20200331000001")
        job = await session.get(ExtractionJob, job_id)

    assert rows == []
    assert job is not None
    assert job.status == "partial"


async def test_force_finish_unlocks_pending_extraction(sessionmaker_fixture) -> None:
    """강제 종료한 pending 추출 잡이 있으면 새 추출을 시작할 수 있다."""
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    service, client = _service(sessionmaker_fixture)
    async with client:
        first = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.force_finish(first)
        second = await service.start("20200301", "20200331", ["F001"], "extract")

    assert first != second
    async with sessionmaker_fixture() as session:
        job = await session.get(ExtractionJob, first)
    assert job is not None
    assert job.status == "partial"
