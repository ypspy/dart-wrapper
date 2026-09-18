# 감사 추출 Admin 모니터 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/admin/extract`에서 연구 창 추출 완전성(왼쪽)과 `audit_opinion` 잡 진행(오른쪽)을 같은 Admin 토큰으로 본다.

**Architecture:** JSON 추출 API는 유지한다. HTML은 수집 `/admin`과 형제 페이지로, `CompletenessService.summarize`를 서버에서 유형 3회 호출하고, `ExtractionService`의 최신 잡·시작·중단을 폼 POST로 감싼다. 잡 `params`에 `target_count`/`processed_count`(방문 수, 스킵 포함)를 넣는다. 일별 히트맵·날짜 LLM은 없다.

**Tech Stack:** FastAPI, Jinja2, HTMX, SQLAlchemy 2 async, pytest

**Spec:** `docs/superpowers/specs/2026-09-11-extract-admin-monitor-design.md`

## Global Constraints

- 주석·Docstring·로그·예외·테스트 설명은 한국어. 함수 입출력 Type Hint 필수.
- 새 facts 컬럼·새 extractor_id·새 npm 패키지 없음. JSON `/admin/extract/status?job_id=` 필수는 유지.
- 완전성 HTML은 5초 폴링 금지(60초). 잡은 5초.
- 기본 기간 `20160101`–`20260909`, 유형 F001/F002/A001만. 수집 히트맵 유형(A002 등)을 추출 화면에 넣지 않음.
- DART 잠금은 기존 `assert_dart_idle`. 회사 업종과 공유하지 않음.
- 작업 디렉터리: `packages/web-api`. pytest: `.\.venv\Scripts\python.exe -m pytest …`
- git 커밋은 **사용자가 요청한 경우에만**. 아래 Commit 스텝은 메시지 초안이다.
- Windows PowerShell 커밋은 bash HEREDOC 대신 `git commit -m "한글 한 줄"`을 쓴다.

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `packages/web-api/app/services/extraction_service.py` | `get_latest_status`, 방문/대상 카운터 |
| `packages/web-api/app/api/admin/ui.py` | `/admin/extract` HTML·폼 POST·partial |
| `packages/web-api/app/templates/admin/base.html` | 수집 \| 추출 전환 링크 |
| `packages/web-api/app/templates/admin/index.html` | `ops_section=catalog` |
| `packages/web-api/app/templates/admin/extract.html` | 추출 ops-grid 페이지 |
| `packages/web-api/app/templates/admin/partials/extract_completeness.html` | 유형 3카드 + 목록 |
| `packages/web-api/app/templates/admin/partials/extract_job.html` | 잡 카드 |
| `packages/web-api/app/templates/admin/partials/extract_form.html` | 시작 폼 |
| `packages/web-api/app/templates/admin/partials/extract_logs.html` | 추출 잡 로그 (수집 `job_logs.html` 복제하지 말고 추출 전용) |
| `packages/web-api/README.md` | Admin 추출 화면 안내 |
| `packages/web-api/tests/test_extraction_service.py` | 최신 잡·방문 수 |
| `packages/web-api/tests/test_extract_admin_ui.py` | HTML 인증·숫자·폼·잠금 |
| `packages/web-api/tests/test_admin_ui.py` | `/admin`에 추출 링크 |

기존 패턴: 회사 업종은 JSON `/admin/corps/enrich`와 폼 `POST /admin/corps/start`를 가른다. 추출도 JSON `POST /admin/extract/audit-opinion`과 폼 `POST /admin/extract/start`를 가른다. 테스트 앱은 `tests/test_corps_admin_ui.py`의 `_app` + `client_factory`.

---

### Task 1: 최신 잡 조회와 방문 카운터

**Files:**
- Modify: `packages/web-api/app/services/extraction_service.py`
- Test: `packages/web-api/tests/test_extraction_service.py`

**Interfaces:**
- Consumes: `ExtractionJobRepository.find_latest`, `update_params`, `DART_EXTRACTOR_ID`, 기존 `run_job` 루프, `group_by_dcm`, `is_audit_document`
- Produces:
  - `async def get_latest_status(self) -> ExtractJobStatusResponse | None`
  - 잡 `params["target_count"]: int` — 시작 시 selector 대상 문서 수
  - 잡 `params["processed_count"]: int` — 이번 잡이 방문한 문서 수(스킵 포함)
  - 종료 로그 `문서 N건` — 기존처럼 `_process_document`가 `None`이 아닌 건만

- [ ] **Step 1: Write the failing tests**

`packages/web-api/tests/test_extraction_service.py` 하단에 추가한다. `_seed_entries`, `_f001_leaves`, `sessionmaker_fixture`는 이 파일에 이미 있다.

```python
async def test_get_latest_status_returns_none_when_empty(
    sessionmaker_fixture,
) -> None:
    """추출 잡이 없으면 None이다. JSON get_status의 job_id 필수와 별개다."""
    http = DartHttpClient(
        httpx.AsyncClient(),
        max_retries=0,
        retry_backoff_seconds=0.0,
    )
    service = ExtractionService(sessionmaker_fixture, http)
    assert await service.get_latest_status() is None


async def test_get_latest_status_returns_latest_job(
    sessionmaker_fixture,
) -> None:
    """같은 추출기의 가장 최근 잡을 돌려준다."""
    http = DartHttpClient(
        httpx.AsyncClient(),
        max_retries=0,
        retry_backoff_seconds=0.0,
    )
    service = ExtractionService(sessionmaker_fixture, http)
    first = await service.start("20200301", "20200331", ["F001"], "extract")
    second = await service.start("20200401", "20200430", ["F002"], "resume")
    latest = await service.get_latest_status()
    assert latest is not None
    assert latest.job_id == second
    assert latest.job_id != first
    assert latest.params["report_types"] == ["F002"]
    assert latest.mode == "resume"


async def test_run_job_counts_visits_including_skips(
    sessionmaker_fixture,
) -> None:
    """대상 1건을 스킵해도 processed_count는 1이고 종료 로그는 문서 0건이다."""
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

    http = DartHttpClient(
        httpx.AsyncClient(),
        max_retries=0,
        retry_backoff_seconds=0.0,
    )
    service = ExtractionService(sessionmaker_fixture, http)
    job_id = await service.start("20200301", "20200331", ["F001"], "resume")
    await service.run_job(job_id)

    async with sessionmaker_fixture() as session:
        job = await session.get(ExtractionJob, job_id)
        logs = await ExtractionJobRepository(session).recent_logs(job_id)
    assert job is not None
    assert job.params["target_count"] == 1
    assert job.params["processed_count"] == 1
    assert any("문서 0건" in log.message for log in logs)
```

`test_get_latest_status_returns_latest_job`에서 두 번째 `start`는 첫 잡이 `pending`이면 `assert_dart_idle`에 걸린다. 첫 잡을 `succeeded`로 바꾼 뒤 두 번째를 시작한다.

```python
    first = await service.start("20200301", "20200331", ["F001"], "extract")
    async with sessionmaker_fixture() as session:
        await ExtractionJobRepository(session).set_status(first, "succeeded")
        await session.commit()
    second = await service.start("20200401", "20200430", ["F002"], "resume")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py::test_get_latest_status_returns_none_when_empty tests/test_extraction_service.py::test_get_latest_status_returns_latest_job tests/test_extraction_service.py::test_run_job_counts_visits_including_skips -v`

Expected: FAIL (`get_latest_status` 없음 또는 `target_count` 없음)

- [ ] **Step 3: Implement**

`ExtractionService`에 추가:

```python
    async def get_latest_status(self) -> ExtractJobStatusResponse | None:
        """가장 최근 audit_opinion 잡. 없으면 None. JSON status의 job_id 필수와 별개다."""
        async with self._sessionmaker() as session:
            jobs = ExtractionJobRepository(session)
            job = await jobs.find_latest(DART_EXTRACTOR_ID)
            if job is None:
                return None
            logs = await jobs.recent_logs(job.job_id)
        return ExtractJobStatusResponse(
            job_id=job.job_id,
            status=job.status,
            mode=job.mode,
            params=dict(job.params or {}),
            error_message=job.error_message,
            started_at=job.started_at,
            finished_at=job.finished_at,
            logs=[JobLogItem.model_validate(log) for log in logs],
        )
```

`get_status`는 그대로 `job_id: str`만 받는다.

`run_job`에서 `rcept_nos`를 받은 직후 대상 수를 세고 params를 쓴다. 문서 루프에서 `_process_document`를 호출한 뒤 **항상** `visited += 1`하고 params를 갱신한다. 기존 `processed`(로그용)는 `fetch_status is not None`일 때만 올린다.

```python
            target_count = 0
            for rcept_no in rcept_nos:
                async with self._sessionmaker() as session:
                    filing = await EntryRepository(session).list_by_rcept_no(rcept_no)
                audit_selectors = [
                    selector
                    for entry in filing
                    if (selector := _to_selector(entry)) is not None
                    and is_audit_document(
                        selector.report_type, selector.source, selector.document_name
                    )
                ]
                target_count += len(group_by_dcm(audit_selectors))

            visited = 0
            processed = 0
            async with self._sessionmaker() as session:
                job_row = await session.get(ExtractionJob, job_id)
                params = dict(job_row.params or {}) if job_row is not None else dict(params)
                params["target_count"] = target_count
                params["processed_count"] = 0
                await ExtractionJobRepository(session).update_params(job_id, params)
                await session.commit()
```

내부 루프 (`for dcm_no in group_by_dcm(...)`) 끝:

```python
                    visited += 1
                    if fetch_status is not None:
                        processed += 1
                    async with self._sessionmaker() as session:
                        job_row = await session.get(ExtractionJob, job_id)
                        current = dict(job_row.params or {}) if job_row is not None else {}
                        current["target_count"] = target_count
                        current["processed_count"] = visited
                        await ExtractionJobRepository(session).update_params(job_id, current)
                        await session.commit()
```

기존 `if fetch_status is not None: processed += 1`와 중복되지 않게 한 곳으로 모은다. `group_by_dcm`은 `app.extracting.selector`에서 이미 import되어 있다.

첫 잡이 pending인 채 두 번째 start를 하면 잠금에 걸리므로 테스트는 Step 1의 `set_status(..., "succeeded")`를 쓴다.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py::test_get_latest_status_returns_none_when_empty tests/test_extraction_service.py::test_get_latest_status_returns_latest_job tests/test_extraction_service.py::test_run_job_counts_visits_including_skips tests/test_extraction_service.py::test_resume_skips_ok_facts tests/test_extract_admin_api.py -q`

Expected: PASS (기존 JSON status 테스트도 통과)

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```powershell
git add packages/web-api/app/services/extraction_service.py packages/web-api/tests/test_extraction_service.py
git commit -m "추출 잡에 방문 수와 최신 상태 조회를 넣는다"
```

---

### Task 2: `/admin/extract` 껍데기 · 전환 링크 · 잡 카드

**Files:**
- Modify: `packages/web-api/app/api/admin/ui.py`
- Modify: `packages/web-api/app/templates/admin/base.html`
- Modify: `packages/web-api/app/templates/admin/index.html`
- Create: `packages/web-api/app/templates/admin/extract.html`
- Create: `packages/web-api/app/templates/admin/partials/extract_job.html`
- Create: `packages/web-api/app/templates/admin/partials/extract_form.html`
- Create: `packages/web-api/app/templates/admin/partials/extract_logs.html`
- Test: `packages/web-api/tests/test_extract_admin_ui.py`
- Test: `packages/web-api/tests/test_admin_ui.py` (수집 페이지에 추출 링크)

**Interfaces:**
- Consumes: `ExtractionService.get_latest_status`, `CatalogService.get_latest_status`, `CompletenessService` (이 Task에서는 Fake만, 숫자는 Task 3)
- Produces:
  - 상수 `RESEARCH_EXTRACT_START_DATE = "20160101"`, `RESEARCH_EXTRACT_END_DATE = "20260909"`, `RESEARCH_EXTRACT_REPORT_TYPES = ("F001", "F002", "A001")` (`ui.py` 모듈 상단)
  - `GET /admin/extract`
  - `GET /admin/extract/job-status`, `/admin/extract/form`, `/admin/extract/logs` (5초 HTMX)
  - 템플릿 컨텍스트 `ops_section`: `"catalog"` | `"extract"`

- [ ] **Step 1: Write the failing tests**

Create `packages/web-api/tests/test_extract_admin_ui.py`:

```python
"""감사 추출 Admin HTML 모니터 테스트."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI

from app.api.deps import (
    get_catalog_service,
    get_completeness_service,
    get_corp_industry_service,
    get_extraction_service,
    get_slice_query_service,
)
from app.main import create_app
from app.schemas.catalog import JobLogItem
from app.schemas.extract import CompletenessResponse, ExtractJobStatusResponse
from tests.test_admin_ui import FakeCatalogService, FakeSliceQueryService
from tests.test_corps_admin_ui import FakeCorpIndustryService

ClientFactory = Callable[[FastAPI], httpx.AsyncClient]


class FakeCompletenessService:
    """유형별 고정 집계를 돌려준다."""

    async def summarize(self, **kwargs) -> CompletenessResponse:
        """테스트용 완전성 숫자."""
        return CompletenessResponse(
            target=10,
            ok=7,
            fetch_failed=1,
            blocked=0,
            section_missing=0,
            unextracted=2,
            ambiguous_dates=1,
            field_partial=3,
        )


class FakeExtractionService:
    """최근 추출 잡만 돌려준다."""

    def __init__(self, job: ExtractJobStatusResponse | None = None) -> None:
        self.job = job
        self.started: list[tuple[str, str, list[str], str]] = []
        self.executed: list[str] = []
        self.stopped: list[str] = []
        self.finished: list[str] = []

    async def get_latest_status(self) -> ExtractJobStatusResponse | None:
        """HTML이 쓰는 최신 잡."""
        return self.job

    async def start(
        self,
        start_date: str,
        end_date: str,
        report_types: list[str],
        mode: str,
    ) -> str:
        """폼 시작을 기록한다."""
        self.started.append((start_date, end_date, report_types, mode))
        return "extract-job-1"

    async def run_job(self, job_id: str) -> None:
        """백그라운드 실행 요청을 기록한다."""
        self.executed.append(job_id)

    async def request_soft_stop(self, job_id: str) -> None:
        """소프트 스톱을 기록한다."""
        self.stopped.append(job_id)

    async def force_finish(self, job_id: str) -> None:
        """강제 종료를 기록한다."""
        self.finished.append(job_id)


RUNNING_EXTRACT = ExtractJobStatusResponse(
    job_id="abcdef12deadbeef",
    status="running",
    mode="extract",
    params={
        "start_date": "20160101",
        "end_date": "20260909",
        "report_types": ["F001", "F002"],
        "processed_count": 4,
        "target_count": 10,
    },
    started_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
    logs=[
        JobLogItem(
            level="info",
            message="20200331000001/11111 추출 완료(ok).",
            created_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
        )
    ],
)


def _app(
    extraction: FakeExtractionService | None = None,
    catalog: FakeCatalogService | None = None,
) -> FastAPI:
    """추출 Admin 화면용 의존성을 대역으로 바꾼다."""
    app = create_app()
    app.dependency_overrides[get_slice_query_service] = lambda: FakeSliceQueryService()
    app.dependency_overrides[get_catalog_service] = lambda: catalog or FakeCatalogService(
        job=None
    )
    app.dependency_overrides[get_corp_industry_service] = lambda: FakeCorpIndustryService()
    app.dependency_overrides[get_extraction_service] = lambda: extraction or FakeExtractionService()
    app.dependency_overrides[get_completeness_service] = lambda: FakeCompletenessService()
    return app


async def test_extract_page_redirects_without_token(client_factory: ClientFactory) -> None:
    """토큰 없이 추출 화면은 토큰 페이지로 보낸다."""
    async with client_factory(_app()) as client:
        response = await client.get("/admin/extract")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/admin/token")


async def test_extract_page_defaults_research_window(
    client_factory: ClientFactory,
) -> None:
    """기본 기간은 잠긴 연구 창이다."""
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/extract")
    assert response.status_code == 200
    assert "20160101" in response.text
    assert "20260909" in response.text
    assert "추출 · 완전성" in response.text
    assert 'href="/admin/extract"' in response.text
    assert ">추출</a>" in response.text or "추출</a>" in response.text


async def test_extract_job_card_shows_progress(
    client_factory: ClientFactory,
) -> None:
    """잡 카드는 처리/대상과 최근 로그를 보여 준다."""
    extraction = FakeExtractionService(RUNNING_EXTRACT)
    async with client_factory(_app(extraction)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/extract/job-status")
    assert response.status_code == 200
    assert "처리 4 / 대상 10" in response.text or "4 / 10" in response.text
    assert "추출 완료(ok)" in response.text
```

`tests/test_admin_ui.py`의 `test_admin_index_renders_two_column_ops_console`에 한 줄 추가하거나 새 테스트:

```python
async def test_admin_index_has_extract_nav(client_factory) -> None:
    """수집 화면에 추출 화면 링크가 있다."""
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin")
    assert response.status_code == 200
    assert 'href="/admin/extract"' in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_ui.py tests/test_admin_ui.py::test_admin_index_has_extract_nav -v`

Expected: FAIL (404 또는 링크 없음)

- [ ] **Step 3: Implement shell**

`ui.py` 상수:

```python
RESEARCH_EXTRACT_START_DATE = "20160101"
RESEARCH_EXTRACT_END_DATE = "20260909"
RESEARCH_EXTRACT_REPORT_TYPES = ("F001", "F002", "A001")
```

카탈로그 `dashboard` 컨텍스트에 `"ops_section": "catalog"`를 넣는다. `base.html` `h1` 아래에:

```html
<nav class="ops-switch" aria-label="운영 화면">
  <a href="/admin" class="{% if ops_section == 'catalog' %}is-selected{% endif %}">수집</a>
  <a href="/admin/extract" class="{% if ops_section == 'extract' %}is-selected{% endif %}">추출</a>
</nav>
```

`ops_section`이 없는 템플릿(슬라이스 상세)은 둘 다 선택되지 않아도 된다. 링크는 있어야 한다. 슬라이스 상세 컨텍스트에도 `ops_section="catalog"`를 넣거나, `{% if ops_section is not defined %}`일 때 수집만 기본 선택.

`base.html`에 `.ops-switch` 스타일: 수집 유형 칩과 비슷하게 `display:flex; gap; border`. `.is-selected`는 기존 `.report-type-chip.is-selected`와 같은 accent.

`GET /admin/extract`: 토큰 검사 후 `extract.html`. 기본 날짜 상수. `extract_job = await extraction.get_latest_status()`. `catalog_job = await catalog.get_latest_status()`. `extract_busy` / `catalog_busy`는 `pending`/`running`. 왼쪽은 Task 3에서 채울 자리 — 이 Task에서는 빈 `<div id="extract-completeness">`와 기간 GET 폼만 둔다(기본 날짜 input).

`extract.html` 오른쪽: 수집 `index.html`처럼

```html
<div hx-get="/admin/extract/job-status" hx-trigger="every 5s" hx-swap="innerHTML">
  {% include "admin/partials/extract_job.html" %}
</div>
...
<div hx-get="/admin/extract/form" ... hx-include="find form">
  {% include "admin/partials/extract_form.html" %}
</div>
<div hx-get="/admin/extract/logs" hx-trigger="every 5s">
  {% include "admin/partials/extract_logs.html" %}
</div>
```

`extract_job.html`: `corps_panel.html` 진행 문구를 추출 용어로. idle이면 「아직 추출 작업 이력이 없습니다.」 실행 중이면 소프트 스톱 폼 `action="/admin/extract/jobs/{{ job.job_id }}/soft-stop"` (POST 라우트는 Task 4에서 연결, 이 Task에서 버튼 HTML만 넣어도 됨 — 클릭 테스트는 Task 4).

`extract_form.html`: 기간, 유형 체크 3개(기본 체크), 모드 select. 버튼은 Task 4에서 활성화. 이 Task에서는 `action="/admin/extract/start"`와 disabled 조건을 `catalog_busy or extract_busy`로 렌더. POST 핸들러는 Task 4.

Job/form/logs partial GET 라우트는 토큰 검사 + 같은 컨텍스트.

`extract_logs.html`: `job_logs.html`과 동일 구조, `job`/`logs`는 추출 잡. `_filter_logs`를 ExtractJobStatusResponse에도 쓰려면 `status`와 `logs` 속성만 있으면 된다. 기존 `_filter_logs`가 `JobStatusResponse` 전용이면 로그 리스트와 status 문자열을 받게 두거나, 추출용으로 같은 레벨 규칙을 복제한다 (`IDLE_LOG_LEVELS` / `ACTIVE_LOG_LEVELS`).

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_ui.py tests/test_admin_ui.py::test_admin_index_has_extract_nav tests/test_admin_ui.py::test_admin_index_renders_two_column_ops_console tests/test_corps_admin_ui.py -q`

Expected: PASS. Task 3 전에는 완전성 숫자 테스트가 아직 없을 수 있다. `test_extract_page_defaults_research_window`만 통과하면 된다.

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```powershell
git add packages/web-api/app/api/admin/ui.py packages/web-api/app/templates/admin packages/web-api/tests/test_extract_admin_ui.py packages/web-api/tests/test_admin_ui.py
git commit -m "추출 Admin 화면 껍데기와 수집·추출 전환을 넣는다"
```

---

### Task 3: 왼쪽 완전성 카드와 문서 목록

**Files:**
- Modify: `packages/web-api/app/api/admin/ui.py`
- Create: `packages/web-api/app/templates/admin/partials/extract_completeness.html`
- Modify: `packages/web-api/app/templates/admin/extract.html`
- Test: `packages/web-api/tests/test_extract_admin_ui.py`

**Interfaces:**
- Consumes: `CompletenessService.summarize(start_date, end_date, report_type, status=None, cursor=None, limit=50)`
- Produces:
  - `GET /admin/extract/completeness-cards?start_date=&end_date=` (60초 HTMX)
  - `GET /admin/extract/completeness-items?start_date=&end_date=&report_type=&status=&cursor=`
  - 서버가 `RESEARCH_EXTRACT_REPORT_TYPES` 각각 `summarize` 1회 (브라우저가 JSON 3회 호출하지 않음)

- [ ] **Step 1: Write the failing tests**

`test_extract_admin_ui.py`에 추가. Fake가 호출 인자를 기록하게 바꾼다.

```python
class FakeCompletenessService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def summarize(self, **kwargs) -> CompletenessResponse:
        self.calls.append(kwargs)
        status = kwargs.get("status")
        items = []
        if status == "unextracted":
            items = [CompletenessItem(rcept_no="20200331000001", dcm_no="11111")]
        return CompletenessResponse(
            target=10,
            ok=7,
            fetch_failed=1,
            blocked=0,
            section_missing=0,
            unextracted=2,
            ambiguous_dates=1,
            field_partial=3,
            items=items,
        )
```

`CompletenessItem`은 `app.schemas.extract`에서 import.

```python
async def test_extract_page_renders_three_type_cards(
    client_factory: ClientFactory,
) -> None:
    """세 유형 카드에 같은 Fake 숫자가 보인다."""
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/extract")
    body = response.text
    assert response.status_code == 200
    assert "F001" in body and "F002" in body and "A001" in body
    assert "대상 10" in body
    assert "미추출 2" in body
    assert "ok 중 구멍" in body or "부분실패 3" in body


async def test_completeness_cards_query_uses_requested_dates(
    client_factory: ClientFactory,
) -> None:
    """카드 partial은 쿼리 기간으로 세 유형을 집계한다."""
    completeness = FakeCompletenessService()
    app = _app()
    app.dependency_overrides[get_completeness_service] = lambda: completeness
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get(
            "/admin/extract/completeness-cards?start_date=20200101&end_date=20201231"
        )
    assert response.status_code == 200
    types = [call["report_type"] for call in completeness.calls]
    assert types == ["F001", "F002", "A001"]
    assert all(call["start_date"] == "20200101" for call in completeness.calls)


async def test_completeness_items_lists_documents(
    client_factory: ClientFactory,
) -> None:
    """상태 숫자를 누르면 문서 식별자가 나온다."""
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get(
            "/admin/extract/completeness-items"
            "?start_date=20160101&end_date=20260909"
            "&report_type=F001&status=unextracted"
        )
    assert response.status_code == 200
    assert "20200331000001" in response.text
    assert "11111" in response.text
```

`_app()`이 매번 새 `FakeCompletenessService()`를 만들면 `completeness_cards` 테스트의 인스턴스가 갈라진다. `_app`에 `completeness=` 인자를 추가한다.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_ui.py::test_extract_page_renders_three_type_cards tests/test_extract_admin_ui.py::test_completeness_cards_query_uses_requested_dates tests/test_extract_admin_ui.py::test_completeness_items_lists_documents -v`

Expected: FAIL (카드 문구 없음)

- [ ] **Step 3: Implement cards**

헬퍼:

```python
async def _extract_completeness_rows(
    service: CompletenessService,
    start_date: str,
    end_date: str,
) -> list[tuple[str, CompletenessResponse]]:
    rows: list[tuple[str, CompletenessResponse]] = []
    for report_type in RESEARCH_EXTRACT_REPORT_TYPES:
        summary = await service.summarize(
            start_date=start_date,
            end_date=end_date,
            report_type=report_type,
        )
        rows.append((report_type, summary))
    return rows
```

날짜는 쿼리가 없으면 연구 창 상수. `YYYYMMDD`가 아니면 `BadRequest` 메시지를 페이지 `notice`로 (폼을 상수로 리셋하지 않음).

카드 문구 (테스트와 맞출 것):

- `대상 {{ summary.target }}`
- `추출 ok {{ summary.ok }}`
- `미추출 {{ summary.unextracted }}`
- `실패 {{ summary.fetch_failed + summary.blocked + summary.section_missing }}` 아래에 `fetch_failed` / `blocked` / `section_missing` 각각 링크
- `부분실패 {{ summary.field_partial }}` + 문구 `ok 중 구멍`
- `날짜 모호 {{ summary.ambiguous_dates }}`

각 숫자는 `hx-get="/admin/extract/completeness-items?...&status=unextracted"` `hx-target` 카드 아래 `#extract-items-{{ report_type }}`. `ok`는 목록 status가 아니므로 링크하지 않는다.

`extract.html` 왼쪽:

```html
<form method="get" action="/admin/extract">
  <input name="start_date" value="{{ start_date }}">
  <input name="end_date" value="{{ end_date }}">
  <button type="submit">기간 적용</button>
</form>
<div hx-get="/admin/extract/completeness-cards?start_date={{ start_date }}&amp;end_date={{ end_date }}"
     hx-trigger="every 60s" hx-swap="innerHTML">
  {% include "admin/partials/extract_completeness.html" %}
</div>
```

`completeness-items` 응답은 작은 목록 partial (`rcept_no / dcm_no`). `next_cursor`가 있으면 「더 보기」가 같은 경로에 cursor를 붙인다.

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_ui.py tests/test_extract_admin_api.py::test_completeness_counts_unextracted_and_lists_remaining -q`

Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```powershell
git add packages/web-api/app/api/admin/ui.py packages/web-api/app/templates/admin packages/web-api/tests/test_extract_admin_ui.py
git commit -m "추출 화면에 유형별 완전성 카드와 문서 목록을 넣는다"
```

---

### Task 4: 시작·중단 폼, 잠금 배너, README

**Files:**
- Modify: `packages/web-api/app/api/admin/ui.py`
- Modify: `packages/web-api/app/templates/admin/extract.html`
- Modify: `packages/web-api/app/templates/admin/partials/extract_form.html`
- Modify: `packages/web-api/app/templates/admin/index.html` (추출 실행 중 배너는 기존 수집 `job_busy`만으로 충분하면 생략. 추출 페이지 상단에만 수집/추출 배너)
- Modify: `packages/web-api/README.md`
- Test: `packages/web-api/tests/test_extract_admin_ui.py`

**Interfaces:**
- Consumes: `ExtractionService.start/run_job/request_soft_stop/force_finish`, `CatalogConflict`
- Produces:
  - `POST /admin/extract/start` → 303 `/admin/extract`
  - `POST /admin/extract/jobs/{job_id}/soft-stop`
  - `POST /admin/extract/jobs/{job_id}/force-finish`
  - JSON 경로와 폼 경로 분리

- [ ] **Step 1: Write the failing tests**

```python
from app.errors import CatalogConflict


class ConflictExtractionService(FakeExtractionService):
    async def start(self, start_date, end_date, report_types, mode) -> str:
        self.started.append((start_date, end_date, report_types, mode))
        raise CatalogConflict("감사 추출 작업이 이미 진행 중입니다.")


async def test_start_extract_form_runs_job(
    client_factory: ClientFactory,
) -> None:
    """폼 POST는 서비스를 호출하고 추출 화면으로 돌아온다."""
    extraction = FakeExtractionService()
    async with client_factory(_app(extraction)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post(
            "/admin/extract/start",
            data={
                "start_date": "20160101",
                "end_date": "20260909",
                "report_types": ["F001", "F002"],
                "mode": "resume",
            },
        )
    assert response.status_code == 303
    assert response.headers["location"].endswith("/admin/extract")
    assert extraction.started == [
        ("20160101", "20260909", ["F001", "F002"], "resume")
    ]
    assert extraction.executed == ["extract-job-1"]


async def test_start_extract_conflict_sets_notice(
    client_factory: ClientFactory,
) -> None:
    """잠금이면 JSON 대신 notice와 함께 추출 화면으로 돌아온다."""
    extraction = ConflictExtractionService()
    async with client_factory(_app(extraction)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post(
            "/admin/extract/start",
            data={
                "start_date": "20160101",
                "end_date": "20260909",
                "report_types": ["F001"],
                "mode": "extract",
            },
            follow_redirects=True,
        )
    assert "진행 중" in response.text
    assert extraction.executed == []


async def test_extract_form_disabled_when_catalog_busy(
    client_factory: ClientFactory,
) -> None:
    """수집이 돌면 추출 시작 버튼이 비활성이다."""
    from tests.test_admin_ui import JOB_STATUS

    async with client_factory(_app(catalog=FakeCatalogService(job=JOB_STATUS))) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/extract")
    assert "수집 중이니 추출을 시작할 수 없습니다" in response.text
    assert "disabled" in response.text


async def test_extract_soft_stop_and_force_finish(
    client_factory: ClientFactory,
) -> None:
    """중단·강제 종료 폼이 추출 화면으로 돌아온다."""
    extraction = FakeExtractionService(RUNNING_EXTRACT)
    async with client_factory(_app(extraction)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        stop = await client.post("/admin/extract/jobs/abcdef12deadbeef/soft-stop")
        finish = await client.post("/admin/extract/jobs/abcdef12deadbeef/force-finish")
    assert stop.status_code == 303
    assert finish.status_code == 303
    assert extraction.stopped == ["abcdef12deadbeef"]
    assert extraction.finished == ["abcdef12deadbeef"]
```

유형이 하나도 없으면 `BadRequest` → notice 「유형을 하나 이상 선택해 주세요.」

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_ui.py::test_start_extract_form_runs_job tests/test_extract_admin_ui.py::test_start_extract_conflict_sets_notice tests/test_extract_admin_ui.py::test_extract_form_disabled_when_catalog_busy tests/test_extract_admin_ui.py::test_extract_soft_stop_and_force_finish -v`

Expected: FAIL (POST 404)

- [ ] **Step 3: Implement POSTs and copy**

`start_extract` 폼 핸들러는 `start_collect`와 같은 토큰·303 패턴. `report_types: list[str] = Form()` (FastAPI는 같은 name의 여러 checkbox를 리스트로 받는다). `background_tasks.add_task(service.run_job, job_id)`. 충돌 시

```python
return RedirectResponse(
    f"/admin/extract?notice={quote(str(exc))}",
    status_code=303,
)
```

상단 배너:

- `catalog_busy`: 「수집 중이니 추출을 시작할 수 없습니다.」
- `extract_busy`: 「추출 작업이 진행 중입니다.」
- `notice` 쿼리

추출 실행 중 수집 `/admin`은 기존 `assert_dart_idle`로 이미 막힌다. 수집 배너 문구를 바꾸지 않아도 된다.

README `packages/web-api/README.md` Admin 추출 절에 한 블록:

```text
운영 화면 `/admin/extract`에서 연구 창 완전성(F001/F002/A001)과 추출 잡을 봅니다.
JSON 트리거(`POST /admin/extract/audit-opinion`)는 그대로입니다.
```

- [ ] **Step 4: Run the full related suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_ui.py tests/test_extract_admin_api.py tests/test_extraction_service.py::test_get_latest_status_returns_none_when_empty tests/test_extraction_service.py::test_get_latest_status_returns_latest_job tests/test_extraction_service.py::test_run_job_counts_visits_including_skips tests/test_admin_ui.py tests/test_corps_admin_ui.py -q`

Expected: PASS

브라우저가 있으면 `/admin/extract`를 토큰 후 연다: 세 카드, 기간 기본값, 잡 idle, 수집 링크. 없으면 테스트로 대체하고 README에 적지 않은 미검증을 구현 요약에만 남긴다.

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```powershell
git add packages/web-api/app/api/admin/ui.py packages/web-api/app/templates/admin packages/web-api/tests/test_extract_admin_ui.py packages/web-api/README.md
git commit -m "추출 Admin에서 잡을 시작하고 잠금을 화면에 보여 준다"
```

---

## Spec coverage

| Spec | Task |
|------|------|
| `/admin/extract` 형제, 수집\|추출 | 2 |
| 왼쪽 완전성 3유형, 히트맵 없음 | 3 |
| 연구 창 기본 기간 | 2·3 |
| 숫자 → 문서 목록, ok 비링크, 부분실패는 ok 부분집합 | 3 |
| 오른쪽 잡·처리/대상·로그·중단 | 1(카운터)·2(카드)·4(POST) |
| 방문 수 vs 종료 로그 문서 N건 | 1 |
| JSON status job_id 필수 유지, HTML find_latest | 1 |
| 폼 vs JSON 경로 분리 | 4 |
| 폴링 5s / 60s | 2·3 |
| DART 잠금 배너 | 4 |
| 날짜 LLM·PATCH·히트맵 없음 | 전 태스크 비포함 |
| 테스트 목록 §7 | 2·3·4 + Task 1 카운터 |

## Type consistency

- `get_latest_status() -> ExtractJobStatusResponse | None` (카탈로그의 `JobStatusResponse | None`과 이름만 다름)
- 폼 `start(start_date, end_date, report_types, mode) -> str`는 기존 `ExtractionService.start`와 동일
- completeness 키는 `CompletenessResponse` 필드명 그대로
