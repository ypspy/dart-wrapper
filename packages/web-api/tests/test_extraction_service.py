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
ACTIVITY_URL = "https://dart.fss.or.kr/report/viewer.do?rcpNo=1&eleId=activity"
BS_URL = "https://dart.fss.or.kr/report/viewer.do?rcpNo=1&eleId=bs"
IS_URL = "https://dart.fss.or.kr/report/viewer.do?rcpNo=1&eleId=is"
FS_PARENT_URL = "https://dart.fss.or.kr/report/viewer.do?rcpNo=1&eleId=fsparent"
ICFR_URL = "https://dart.fss.or.kr/report/viewer.do?rcpNo=1&eleId=icfr"
NOTES_URL = "https://dart.fss.or.kr/report/viewer.do?rcpNo=1&eleId=notes"
A001_OPINION_URL = "https://dart.fss.or.kr/report/viewer.do?rcpNo=2&eleId=opinion"

_FS_HTML = """
<html><body>
<p>재무상태표</p>
<p>(단위 : 원)</p>
<table>
<tr><td>과 목</td><td>주석</td><td>당기</td><td>전기</td></tr>
<tr><td>자 산 총 계</td><td></td><td>1000</td><td>900</td></tr>
<tr><td>자 본 총 계</td><td></td><td>400</td><td>350</td></tr>
</table>
</body></html>
"""

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

ACTIVITY_HTML = """
<html><body>
<table>
<tr>
  <td rowspan="2">구분</td>
  <td colspan="2">담당이사<br/>(업무수행이사)</td>
  <td colspan="2">합계</td>
</tr>
<tr><td>당기</td><td>전기</td><td>당기</td><td>전기</td></tr>
<tr><td>투입 인원수</td><td></td><td>1</td><td>1</td><td>2</td><td>2</td></tr>
<tr><td rowspan="3">투입시간</td><td>분·반기검토</td><td>10</td><td>-</td><td>10</td><td>-</td></tr>
<tr><td>감사</td><td>100</td><td>80</td><td>100</td><td>80</td></tr>
<tr><td>합계</td><td>110</td><td>80</td><td>110</td><td>80</td></tr>
</table>
</body></html>
"""

ICFR_REVIEW_HTML = """
<html><body>
<p>외부감사인의 내부회계관리제도 검토보고서</p>
<p>우리는 내부회계관리제도 검토기준에 따라 검토를 실시하였습니다.</p>
<p>중요한 취약점이 발견되지 아니하였습니다.</p>
</body></html>
"""

NOTES_HTML = """
<html><body>
<p>3. 종속기업</p>
<table>
<tr><td>회사명</td><td>소재지</td><td>지분율</td></tr>
<tr><td>갑주식회사</td><td>한국</td><td>100%</td></tr>
<tr><td>을주식회사</td><td>한국</td><td>80%</td></tr>
<tr><td>합계</td><td></td><td></td></tr>
</table>
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


def _icfr_leaf() -> EntryRecord:
    return _entry(
        entry_id="e-icfr",
        section_name="내부회계관리제도 검토의견",
        path=["내부회계관리제도 검토의견"],
        viewer_url=ICFR_URL,
    )


def _f002_leaves() -> list[EntryRecord]:
    return [
        _entry(
            report_type="F002",
            document_name="연결감사보고서",
        ),
        _entry(
            entry_id="e-opinion",
            report_type="F002",
            document_name="연결감사보고서",
            section_name="독립된 감사인의 감사보고서",
            path=["독립된 감사인의 감사보고서"],
            viewer_url=OPINION_URL,
        ),
    ]


def _notes_leaf() -> EntryRecord:
    return _entry(
        entry_id="e-notes",
        report_type="F002",
        document_name="연결감사보고서",
        section_name="주석",
        path=["주석"],
        viewer_url=NOTES_URL,
    )


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
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
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
    assert fact.extractor_version == "audit_opinion.v16"
    assert fact.hours_status == "skipped"
    assert fact.activities_status == "skipped"
    assert fact.communications_status == "skipped"
    assert fact.hours == []
    assert fact.activities == []
    assert fact.communications == {"has_audit_committee": False, "items": []}
    assert fact.accounts_status == "skipped"
    assert fact.accounts == []
    assert fact.icfr_status == "skipped"
    assert fact.icfr_entry_id is None
    assert fact.icfr_engagement is None
    assert fact.going_concern_status == "ok"
    assert fact.going_concern == 0  # fixture 의견서에 MU 없음
    assert fact.subsidiary_status == "not_applicable"
    assert fact.subsidiary_count is None


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
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
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
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
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
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.fetch_status == "blocked"


async def test_http_403_sets_blocked(sessionmaker_fixture) -> None:
    """HTTP 403은 fetch_failed가 아니라 blocked이다."""
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (403, "forbidden"),
            OPINION_URL: (200, OPINION_HTML),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.fetch_status == "blocked"


async def test_missing_optional_leaf_url_does_not_fail_document(
    sessionmaker_fixture,
) -> None:
    """실시내용처럼 선택 leaf의 viewer_url이 없어도 문서는 추출한다."""
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f001_leaves(),
            _entry(
                entry_id="e-activity",
                section_name="외부감사 실시내용",
                path=["외부감사 실시내용"],
                viewer_url=None,
            ),
        ],
    )
    service, client = _service(sessionmaker_fixture)
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.fetch_status == "ok"
    assert fact.opinion_code == "unqualified"
    assert fact.hours_status == "skipped"
    assert fact.activities_status == "skipped"
    assert fact.communications_status == "skipped"
    assert fact.accounts_status == "skipped"
    assert fact.accounts == []


async def test_extract_activity_hours_ok_without_section_four(
    sessionmaker_fixture,
) -> None:
    """실시내용 2절 표는 hours를 채우고, 4절이 없으면 communications는 not_found다."""
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f001_leaves(),
            _entry(
                entry_id="e-activity",
                section_name="외부감사 실시내용",
                path=["외부감사 실시내용"],
                viewer_url=ACTIVITY_URL,
            ),
        ],
    )
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            ACTIVITY_URL: (200, ACTIVITY_HTML),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.fetch_status == "ok"
    assert fact.hours_status == "ok"
    assert fact.hours
    assert fact.communications_status == "not_found"


async def test_accounts_parser_exception_sets_not_found_without_failing_job(
    sessionmaker_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """제표계정 파서 예외는 accounts_status=not_found이고 잡은 성공한다."""

    def boom(*, bs_html: str | None, is_html: str | None) -> tuple[list[dict], str]:
        raise RuntimeError("의도한 계정 파서 예외")

    monkeypatch.setattr("app.services.extraction_service.extract_accounts", boom)
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f001_leaves(),
            _entry(
                entry_id="e-bs",
                section_name="재무상태표",
                path=["재무상태표"],
                viewer_url=BS_URL,
            ),
        ],
    )
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            BS_URL: (200, _FS_HTML),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")
        job = await session.get(ExtractionJob, job_id)

    assert fact is not None
    assert fact.fetch_status == "ok"
    assert fact.accounts_status == "not_found"
    assert fact.accounts == []
    assert job is not None
    assert job.status == "succeeded"


async def test_hours_parser_exception_does_not_mark_fetch_failed(
    sessionmaker_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2절 파서가 예외여도 문서는 fetch_failed가 아니고 의견 필드는 남는다."""

    def boom(_html: str) -> tuple[list[dict[str, object]], str]:
        raise RuntimeError("의도한 시간 파서 예외")

    monkeypatch.setattr("app.services.extraction_service.extract_hours", boom)
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f001_leaves(),
            _entry(
                entry_id="e-activity",
                section_name="외부감사 실시내용",
                path=["외부감사 실시내용"],
                viewer_url=ACTIVITY_URL,
            ),
        ],
    )
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            ACTIVITY_URL: (200, ACTIVITY_HTML),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")
        job = await session.get(ExtractionJob, job_id)

    assert fact is not None
    assert fact.fetch_status == "ok"
    assert fact.opinion_code == "unqualified"
    assert fact.opinion_status == "ok"
    assert fact.hours_status == "not_found"
    assert fact.hours == []
    assert job is not None
    assert job.status == "succeeded"


async def test_reparse_refetches_when_hours_status_is_not_found(
    sessionmaker_fixture,
) -> None:
    """reparse는 hours_status가 not_found여도 실시내용 HTML을 다시 가져온다."""
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f001_leaves(),
            _entry(
                entry_id="e-activity",
                section_name="외부감사 실시내용",
                path=["외부감사 실시내용"],
                viewer_url=ACTIVITY_URL,
            ),
        ],
    )
    async with sessionmaker_fixture() as session:
        await FactRepository(session).upsert(
            AuditReportFact(
                rcept_no="20200331000001",
                dcm_no="11111",
                source_report_type="F001",
                fs_scope="separate",
                fetch_status="ok",
                hours_status="not_found",
                extractor_version="audit_opinion.v15",
                conflicts=[],
                audit_report_date_candidates=[],
            )
        )
        await session.commit()

    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            ACTIVITY_URL: (200, ACTIVITY_HTML),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "reparse")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.hours_status == "ok"
    assert fact.hours


async def test_extract_job_parses_statement_accounts(sessionmaker_fixture) -> None:
    """재무상태표 leaf HTML을 가져와 accounts에 자산총계를 저장한다."""
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f001_leaves(),
            _entry(
                entry_id="e-bs",
                section_name="재무상태표",
                path=["재무상태표"],
                viewer_url=BS_URL,
            ),
        ],
    )
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            BS_URL: (200, _FS_HTML),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.accounts_status == "ok"
    assert fact.bs_entry_id == "e-bs"
    assert fact.fs_parent_entry_id is None
    total = next(
        a
        for a in fact.accounts
        if a.get("account") == "total_asset" and a.get("period") == "current"
    )
    assert total["value"] == 1000


async def test_extract_job_uses_parent_when_no_statement_leaves(
    sessionmaker_fixture,
) -> None:
    """본표 leaf가 없으면 부모 제표 HTML을 주석 앞에서 잘라 계정을 읽는다."""
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f001_leaves(),
            _entry(
                entry_id="e-fs-parent",
                section_name="(첨부)재무제표",
                path=["(첨부)재무제표"],
                viewer_url=FS_PARENT_URL,
            ),
            _entry(
                entry_id="e-notes",
                section_name="주석",
                path=["(첨부)재무제표", "주석"],
                viewer_url=None,
            ),
        ],
    )
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            FS_PARENT_URL: (200, _FS_HTML + "주석 1. 자세한"),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.accounts_status == "ok"
    assert fact.fs_parent_entry_id == "e-fs-parent"
    assert fact.bs_entry_id is None
    total = next(
        a
        for a in fact.accounts
        if a.get("account") == "total_asset" and a.get("period") == "current"
    )
    assert total["value"] == 1000


async def test_reparse_refetches_when_accounts_status_is_not_found(
    sessionmaker_fixture,
) -> None:
    """reparse는 accounts_status가 not_found여도 제표 HTML을 다시 가져온다."""
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f001_leaves(),
            _entry(
                entry_id="e-bs",
                section_name="재무상태표",
                path=["재무상태표"],
                viewer_url=BS_URL,
            ),
        ],
    )
    async with sessionmaker_fixture() as session:
        await FactRepository(session).upsert(
            AuditReportFact(
                rcept_no="20200331000001",
                dcm_no="11111",
                source_report_type="F001",
                fs_scope="separate",
                fetch_status="ok",
                accounts_status="not_found",
                extractor_version="audit_opinion.v15",
                conflicts=[],
                audit_report_date_candidates=[],
            )
        )
        await session.commit()

    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            BS_URL: (200, _FS_HTML),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "reparse")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.accounts_status == "ok"
    total = next(
        a
        for a in fact.accounts
        if a.get("account") == "total_asset" and a.get("period") == "current"
    )
    assert total["value"] == 1000


async def test_extract_job_parses_icfr_review_opinion(sessionmaker_fixture) -> None:
    """내부회계 검토의견 leaf HTML을 가져와 검토·적정을 저장한다."""
    await _seed_entries(sessionmaker_fixture, [*_f001_leaves(), _icfr_leaf()])
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            ICFR_URL: (200, ICFR_REVIEW_HTML),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.icfr_status == "ok"
    assert fact.icfr_entry_id == "e-icfr"
    assert fact.icfr_engagement == "review"
    assert fact.icfr_opinion_code == "unqualified"


async def test_icfr_fetch_failure_sets_not_found_without_failing_job(
    sessionmaker_fixture,
) -> None:
    """내부회계 leaf는 있으나 HTML fetch가 실패하면 icfr_status=not_found이고 잡은 성공한다."""
    await _seed_entries(sessionmaker_fixture, [*_f001_leaves(), _icfr_leaf()])
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            ICFR_URL: (500, "error"),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")
        job = await session.get(ExtractionJob, job_id)

    assert fact is not None
    assert fact.fetch_status == "ok"
    assert fact.icfr_entry_id == "e-icfr"
    assert fact.icfr_status == "not_found"
    assert fact.icfr_engagement is None
    assert fact.icfr_opinion_code is None
    assert fact.icfr_opinion_raw is None
    assert job is not None
    assert job.status == "succeeded"


async def test_icfr_parser_exception_sets_not_found_without_failing_job(
    sessionmaker_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """내부회계 파서 예외는 icfr_status=not_found이고 잡은 성공한다."""

    def boom(
        *,
        opinion_html: str | None,
        icfr_html: str | None,
        fs_scope: str,
    ) -> object:
        raise RuntimeError("의도한 내부회계 파서 예외")

    monkeypatch.setattr("app.services.extraction_service.extract_icfr", boom)
    await _seed_entries(sessionmaker_fixture, [*_f001_leaves(), _icfr_leaf()])
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            ICFR_URL: (200, ICFR_REVIEW_HTML),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")
        job = await session.get(ExtractionJob, job_id)

    assert fact is not None
    assert fact.fetch_status == "ok"
    assert fact.icfr_status == "not_found"
    assert fact.icfr_engagement is None
    assert fact.icfr_opinion_code is None
    assert job is not None
    assert job.status == "succeeded"


async def test_reparse_refetches_when_icfr_status_is_not_found(
    sessionmaker_fixture,
) -> None:
    """reparse는 icfr_status가 not_found여도 내부회계 HTML을 다시 가져온다."""
    await _seed_entries(sessionmaker_fixture, [*_f001_leaves(), _icfr_leaf()])
    async with sessionmaker_fixture() as session:
        await FactRepository(session).upsert(
            AuditReportFact(
                rcept_no="20200331000001",
                dcm_no="11111",
                source_report_type="F001",
                fs_scope="separate",
                fetch_status="ok",
                icfr_status="not_found",
                extractor_version="audit_opinion.v15",
                conflicts=[],
                audit_report_date_candidates=[],
            )
        )
        await session.commit()

    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            ICFR_URL: (200, ICFR_REVIEW_HTML),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "reparse")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.icfr_status == "ok"
    assert fact.icfr_engagement == "review"
    assert fact.icfr_opinion_code == "unqualified"


async def test_extract_job_counts_notes_subsidiaries(sessionmaker_fixture) -> None:
    """연결 주석 표를 세어 subsidiary_count를 넣는다."""
    await _seed_entries(sessionmaker_fixture, [*_f002_leaves(), _notes_leaf()])
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            NOTES_URL: (200, NOTES_HTML),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F002"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.fs_scope == "consolidated"
    assert fact.subsidiary_status == "ok"
    assert fact.subsidiary_count == 2
    assert fact.subsidiary_source == "notes"
    assert fact.notes_entry_id == "e-notes"


async def test_notes_fetch_failure_sets_not_found_without_failing_job(
    sessionmaker_fixture,
) -> None:
    """주석 leaf는 있으나 HTML fetch가 실패하면 subsidiary_status=not_found이고 잡은 성공한다."""
    await _seed_entries(sessionmaker_fixture, [*_f002_leaves(), _notes_leaf()])
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            NOTES_URL: (500, "error"),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F002"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")
        job = await session.get(ExtractionJob, job_id)

    assert fact is not None
    assert fact.fetch_status == "ok"
    assert fact.notes_entry_id == "e-notes"
    assert fact.subsidiary_status == "not_found"
    assert fact.subsidiary_count is None
    assert job is not None
    assert job.status == "succeeded"


async def test_notes_403_sets_not_found_without_blocking_document(
    sessionmaker_fixture,
) -> None:
    """연결 주석 URL이 403이어도 문서를 blocked로 만들지 않고 필드만 not_found다."""
    await _seed_entries(sessionmaker_fixture, [*_f002_leaves(), _notes_leaf()])
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            NOTES_URL: (403, "forbidden"),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F002"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")
        job = await session.get(ExtractionJob, job_id)

    assert fact is not None
    assert fact.fetch_status == "ok"
    assert fact.notes_entry_id == "e-notes"
    assert fact.subsidiary_status == "not_found"
    assert fact.subsidiary_count is None
    assert job is not None
    assert job.status == "succeeded"


async def test_consolidated_parent_notes_fallback_403_does_not_block_document(
    sessionmaker_fixture,
) -> None:
    """연결 F002에 BS/IS leaf가 있고 주석 leaf가 없을 때 부모 403은 subsidiary만 not_found다."""
    await _seed_entries(
        sessionmaker_fixture,
        [
            *_f002_leaves(),
            _entry(
                entry_id="e-bs",
                report_type="F002",
                document_name="연결감사보고서",
                section_name="연결재무상태표",
                path=["연결재무상태표"],
                viewer_url=BS_URL,
            ),
            _entry(
                entry_id="e-is",
                report_type="F002",
                document_name="연결감사보고서",
                section_name="연결손익계산서",
                path=["연결손익계산서"],
                viewer_url=IS_URL,
            ),
            _entry(
                entry_id="e-fs-parent",
                report_type="F002",
                document_name="연결감사보고서",
                section_name="(첨부)연결재무제표",
                path=["(첨부)연결재무제표"],
                viewer_url=FS_PARENT_URL,
            ),
        ],
    )
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            BS_URL: (200, _FS_HTML),
            IS_URL: (200, _FS_HTML),
            FS_PARENT_URL: (403, "forbidden"),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F002"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")
        job = await session.get(ExtractionJob, job_id)

    assert fact is not None
    assert fact.fetch_status == "ok"
    assert fact.opinion_status == "ok"
    assert fact.accounts_status == "ok"
    assert fact.subsidiary_status == "not_found"
    assert fact.subsidiary_count is None
    assert fact.fs_parent_entry_id == "e-fs-parent"
    assert fact.notes_entry_id is None
    assert job is not None
    assert job.status == "succeeded"


async def test_going_concern_parser_exception_sets_not_found_without_failing_job(
    sessionmaker_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """계속기업 파서 예외는 going_concern_status=not_found이고 잡은 성공한다."""

    def boom(opinion_html: str | None) -> object:
        raise RuntimeError("의도한 계속기업 파서 예외")

    monkeypatch.setattr("app.services.extraction_service.extract_going_concern", boom)
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    service, client = _service(sessionmaker_fixture)
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")
        job = await session.get(ExtractionJob, job_id)

    assert fact is not None
    assert fact.fetch_status == "ok"
    assert fact.going_concern_status == "not_found"
    assert fact.going_concern is None
    assert job is not None
    assert job.status == "succeeded"


async def test_subsidiary_parser_exception_sets_not_found_without_failing_job(
    sessionmaker_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """종속기업 파서 예외는 subsidiary_status=not_found이고 잡은 성공한다."""

    def boom(*, fs_scope: str, notes_html: str | None, a001_html: str | None) -> object:
        raise RuntimeError("의도한 종속기업 파서 예외")

    monkeypatch.setattr("app.services.extraction_service.extract_subsidiaries", boom)
    await _seed_entries(sessionmaker_fixture, [*_f002_leaves(), _notes_leaf()])
    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            NOTES_URL: (200, NOTES_HTML),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F002"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")
        job = await session.get(ExtractionJob, job_id)

    assert fact is not None
    assert fact.fetch_status == "ok"
    assert fact.subsidiary_status == "not_found"
    assert fact.subsidiary_count is None
    assert job is not None
    assert job.status == "succeeded"


async def test_separate_subsidiary_parser_exception_sets_not_found_without_failing_job(
    sessionmaker_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """별도 경로의 종속기업 파서 예외도 subsidiary_status=not_found이고 잡은 성공한다."""

    def boom(*, fs_scope: str, notes_html: str | None, a001_html: str | None) -> object:
        raise RuntimeError("의도한 별도 종속기업 파서 예외")

    monkeypatch.setattr("app.services.extraction_service.extract_subsidiaries", boom)
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    service, client = _service(sessionmaker_fixture)
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")
        job = await session.get(ExtractionJob, job_id)

    assert fact is not None
    assert fact.fetch_status == "ok"
    assert fact.subsidiary_status == "not_found"
    assert fact.subsidiary_count is None
    assert job is not None
    assert job.status == "succeeded"


async def test_reparse_refetches_when_subsidiary_status_is_not_found(
    sessionmaker_fixture,
) -> None:
    """reparse는 subsidiary_status가 not_found여도 주석 HTML을 다시 가져온다."""
    await _seed_entries(sessionmaker_fixture, [*_f002_leaves(), _notes_leaf()])
    async with sessionmaker_fixture() as session:
        await FactRepository(session).upsert(
            AuditReportFact(
                rcept_no="20200331000001",
                dcm_no="11111",
                source_report_type="F002",
                fs_scope="consolidated",
                fetch_status="ok",
                subsidiary_status="not_found",
                extractor_version="audit_opinion.v15",
                conflicts=[],
                audit_report_date_candidates=[],
            )
        )
        await session.commit()

    service, client = _service(
        sessionmaker_fixture,
        {
            COVER_URL: (200, COVER_HTML),
            OPINION_URL: (200, OPINION_HTML),
            NOTES_URL: (200, NOTES_HTML),
        },
    )
    async with client:
        job_id = await service.start("20200301", "20200331", ["F002"], "reparse")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.subsidiary_status == "ok"
    assert fact.subsidiary_count == 2
    assert fact.subsidiary_source == "notes"


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
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.fetch_status == "section_missing"


async def test_resume_skips_ok_facts(sessionmaker_fixture) -> None:
    """같은 버전의 ok 행은 resume에서 다시 fetch하지 않는다."""
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
        job_id = await service.start("20200301", "20200331", ["F001"], "resume")
        await service.run_job(job_id)

    assert calls == []
    async with sessionmaker_fixture() as session:
        job = await session.get(ExtractionJob, job_id)
        logs = await ExtractionJobRepository(session).recent_logs(job_id)
    assert job is not None and job.status == "succeeded"
    assert any("문서 0건" in log.message for log in logs)


async def test_extract_refetches_when_extractor_version_differs(
    sessionmaker_fixture,
) -> None:
    """fetch_status가 ok여도 추출기 버전이 다르면 extract가 다시 가져온다."""
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    async with sessionmaker_fixture() as session:
        await FactRepository(session).upsert(
            AuditReportFact(
                rcept_no="20200331000001",
                dcm_no="11111",
                source_report_type="F001",
                fs_scope="separate",
                fetch_status="ok",
                opinion_code="disclaimer",
                opinion_status="ok",
                extractor_version="audit_opinion.v2",
                conflicts=[],
                audit_report_date_candidates=[],
            )
        )
        await session.commit()

    service, client = _service(sessionmaker_fixture)
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.opinion_code == "unqualified"
    assert fact.extractor_version == "audit_opinion.v16"


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
        job_id = await service.start("20200301", "20200331", ["F001"], "reparse")
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
        job_id = await service.start("20200301", "20200331", ["F001", "A001"], "extract")
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
        job_id = await service.start("20200301", "20200331", ["F001"], "reparse")
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
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
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
        job_id = await service.start("20200301", "20200331", ["F001"], "reparse")
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
        job_id = await service.start("20200301", "20200331", ["F001", "A001"], "extract")
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
