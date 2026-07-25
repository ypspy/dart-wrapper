# Admin Ops Resume · Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin 수집을 날짜 슬라이스·공시 단위로 재개 가능하게 바꾸고, 내부 완전성 모니터와 Jinja/HTMX `/admin` UI를 제공한다.

**Architecture:** Python `CatalogService`가 오케스트레이터가 된다. Node는 `list_disclosures`(1일 목록+listed_count)와 `extract_disclosure`(단건 leaf)만 수행하고, 성공 공시는 즉시 entries/disclosures upsert + `disclosure_attempt`에 기록한다. `slice_progress`로 `listed_count == succeeded && failed==0`일 때만 `complete`다. Admin API/UI는 `X-Admin-Token`(헤더 또는 HttpOnly 쿠키)으로 보호한다.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, HTMX(CDN), Pydantic v2, SQLAlchemy 2.0 async, aiosqlite, Node entry-extractor, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-07-25-admin-ops-resume-design.md`

## Global Constraints

- Python 3.11+, 모든 함수 입·출력 타입 힌트
- 주석·Docstring·로그·예외/사용자 메시지는 **한국어**
- I/O는 `async`/`await`
- Black / Flake8 (line length 100)
- DB에는 메타만 저장. 원문·정제 텍스트·표 저장 금지
- 재개 기준에 **페이지 번호 사용 금지** (날짜 슬라이스 + `rcp_no`)
- 테스트는 실제 DART를 호출하지 않는다
- 작업 디렉터리: `packages/web-api` (Node CLI 작업은 `packages/entry-extractor`)
- URL/`rcp_no`와 DB/`rcept_no`는 같은 접수번호

## File Structure

| Path | Responsibility |
|------|----------------|
| `app/config.py` | `ADMIN_TOKEN`, 재시도·blocked 임계값 |
| `app/errors.py` | `Unauthorized` → 401 |
| `app/models/slice_progress.py` | `SliceProgress`, `DisclosureAttempt` ORM |
| `app/models/catalog_job.py` | `mode` 컬럼 추가 |
| `app/models/__init__.py` | 새 모델 export → `create_all` |
| `app/repositories/slice_repository.py` | 슬라이스/attempt CRUD·집계·완전성 |
| `app/ports/entry_collector.py` | `list_disclosures` / `extract_disclosure` 계약 |
| `app/adapters/node_entry_collector.py` | CLI 모드별 호출 |
| `packages/entry-extractor/bin/collect-entries.js` | `mode=list\|extract\|collect` |
| `app/services/catalog_service.py` | 오케스트레이터로 교체 (extract/resume/retry/soft-stop) |
| `app/schemas/catalog.py` | Resume·Slice 응답 스키마, job `mode` |
| `app/api/deps.py` | `require_admin`, 템플릿용 deps |
| `app/api/admin/catalog.py` | resume/slices/retry + auth |
| `app/api/admin/ui.py` | `/admin` HTML 라우트 |
| `app/templates/admin/*.html` | 수집 폼·대시보드·상세 |
| `app/main.py` | 정적파일·템플릿·UI 라우터 |
| `tests/test_*.py` | 각 단위 테스트 |
| `.env.example`, `README.md` | 토큰·Admin 문서 |

---

### Task 1: Admin 설정 · 401 Unauthorized

**Files:**
- Modify: `packages/web-api/app/config.py`
- Modify: `packages/web-api/app/errors.py`
- Modify: `packages/web-api/.env.example`
- Test: `packages/web-api/tests/test_errors.py`

**Interfaces:**
- Consumes: 기존 `Settings`, `DartWrapperError`, `register_exception_handlers`
- Produces: `Settings.admin_token: str`, `Settings.disclosure_max_retries: int = 3`, `Settings.block_streak_threshold: int = 5`, `Settings.block_wait_seconds: float = 60.0`, `Unauthorized` → HTTP 401

- [ ] **Step 1: Write the failing test**

`tests/test_errors.py`에 추가:

```python
async def test_unauthorized_returns_401(client_factory) -> None:
    from fastapi import FastAPI

    from app.errors import Unauthorized, register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/secret")
    async def secret() -> None:
        raise Unauthorized("Admin 토큰이 필요합니다.")

    async with client_factory(app) as client:
        response = await client.get("/secret")

    assert response.status_code == 401
    assert response.json()["detail"] == "Admin 토큰이 필요합니다."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_errors.py::test_unauthorized_returns_401 -v`  
Expected: FAIL (`Unauthorized` 없음)

- [ ] **Step 3: Implement**

`app/errors.py`:

```python
class Unauthorized(DartWrapperError):
    """Admin 인증이 없거나 토큰이 일치하지 않을 때 발생한다."""


_STATUS_BY_EXCEPTION: dict[type[DartWrapperError], int] = {
    CatalogNotFound: 404,
    BadRequest: 400,
    Unauthorized: 401,
    SourceFetchError: 502,
    ParseError: 502,
}
```

`app/config.py`의 `Settings`에:

```python
admin_token: str = "dev-admin-token"
disclosure_max_retries: int = 3
block_streak_threshold: int = 5
block_wait_seconds: float = 60.0
```

`.env.example`에 `ADMIN_TOKEN=dev-admin-token` 및 위 재시도 설정을 한국어 주석과 함께 추가.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_errors.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/errors.py packages/web-api/app/config.py packages/web-api/.env.example packages/web-api/tests/test_errors.py
git commit -m "feat(web-api): add Unauthorized 401 and admin token settings"
```

---

### Task 2: SliceProgress · DisclosureAttempt · Job mode 모델

**Files:**
- Create: `packages/web-api/app/models/slice_progress.py`
- Modify: `packages/web-api/app/models/catalog_job.py`
- Modify: `packages/web-api/app/models/__init__.py`
- Test: `packages/web-api/tests/test_slice_models.py`

**Interfaces:**
- Produces:
  - `SliceProgress(slice_id, report_type, slice_date, status, listed_count|None, attempted, succeeded, failed_count, last_job_id|None, attempt, …)` Unique `(report_type, slice_date)`
  - `DisclosureAttempt(rcept_no PK, slice_id FK, report_type, status, entry_count, attempt, last_error|None, updated_at)`
  - `CatalogJob.mode: str` (`collect` \| `resume` \| `rescan`, default `collect`)

- [ ] **Step 1: Write the failing test**

```python
"""슬라이스·공시 시도 ORM이 create_all에 포함되는지 검증한다."""

from __future__ import annotations

from sqlalchemy import select

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.models.slice_progress import DisclosureAttempt, SliceProgress


async def test_slice_and_attempt_roundtrip() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)

    async with sessionmaker() as session:
        slice_row = SliceProgress(
            slice_id="s1",
            report_type="F001",
            slice_date="20260724",
            status="pending",
            listed_count=None,
        )
        session.add(slice_row)
        session.add(
            DisclosureAttempt(
                rcept_no="20260724000650",
                slice_id="s1",
                report_type="F001",
                status="pending",
            )
        )
        await session.commit()

        loaded = (
            await session.execute(select(SliceProgress).where(SliceProgress.slice_id == "s1"))
        ).scalar_one()
        assert loaded.slice_date == "20260724"
        attempt = (
            await session.execute(
                select(DisclosureAttempt).where(DisclosureAttempt.rcept_no == "20260724000650")
            )
        ).scalar_one()
        assert attempt.status == "pending"

    await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_slice_models.py -v`  
Expected: FAIL (모듈/테이블 없음)

- [ ] **Step 3: Implement models**

`app/models/slice_progress.py` — UniqueConstraint `(report_type, slice_date)`, 스펙 4.1·4.2 컬럼, `_now()`는 `catalog_job`과 동일 패턴.

`CatalogJob`에:

```python
mode: Mapped[str] = mapped_column(String(16), default="collect", nullable=False)
```

`app/models/__init__.py`에서 `SliceProgress`, `DisclosureAttempt` import.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_slice_models.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/models packages/web-api/tests/test_slice_models.py
git commit -m "feat(web-api): add slice_progress and disclosure_attempt models"
```

---

### Task 3: SliceRepository

**Files:**
- Create: `packages/web-api/app/repositories/slice_repository.py`
- Test: `packages/web-api/tests/test_slice_repository.py`

**Interfaces:**
- Produces:
  - `async def get_or_create_slice(report_type: str, slice_date: str) -> SliceProgress`
  - `async def set_listed(slice_id: str, listed_count: int, job_id: str) -> None`
  - `async def upsert_attempt(...) -> DisclosureAttempt`
  - `async def get_attempt(rcept_no: str) -> DisclosureAttempt | None`
  - `async def list_attempts(slice_id: str) -> list[DisclosureAttempt]`
  - `async def recompute_counts(slice_id: str) -> SliceProgress` — attempted/succeeded/failed_count를 attempt 행에서 재계산
  - `async def evaluate_complete(slice_id: str) -> SliceProgress` — `listed_count is not None and succeeded == listed_count and failed_count == 0`이면 `complete`, 아니면 running/failed 유지 규칙에 맞게 설정
  - `async def list_slices(report_type: str | None, start: str | None, end: str | None) -> list[SliceProgress]`
  - `async def list_incomplete(...) -> list[SliceProgress]` — resume 대상
  - `async def mark_slice_status(slice_id: str, status: str) -> None`

**Complete 규칙:** `succeeded`에는 DB상 `status=succeeded`인 attempt 수(스킵 포함). 목록에 없는 옛 attempt는 complete 계산에 넣지 않는다 — `evaluate_complete`는 **이번 listed 집합**과 맞추려면 orchestrator가 listed `rcept_no`에 대해 succeeded 개수를 세도록 한다. Repository는 `count_succeeded_in(slice_id, rcept_nos: Sequence[str])` 헬퍼를 제공한다.

- [ ] **Step 1: Write failing tests**

핵심 케이스:

```python
async def test_evaluate_complete_when_all_succeeded(sessionmaker_fixture) -> None:
    # slice listed_count=2, two succeeded attempts → status complete

async def test_evaluate_not_complete_with_failure(sessionmaker_fixture) -> None:
    # 1 succeeded + 1 failed → not complete, failed_count=1

async def test_get_or_create_slice_is_idempotent(sessionmaker_fixture) -> None:
    # same report_type+date returns same slice_id
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement `SliceRepository`**

한국어 Docstring. `recompute_counts`는 `DisclosureAttempt`를 집계해 `SliceProgress` 갱신.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/repositories/slice_repository.py packages/web-api/tests/test_slice_repository.py
git commit -m "feat(web-api): add SliceRepository for completeness tracking"
```

---

### Task 4: EntryCollector 포트 확장

**Files:**
- Modify: `packages/web-api/app/ports/entry_collector.py`
- Test: `packages/web-api/tests/test_entry_collector_port.py` (타입/스키마 단위 — Pydantic 모델 검증)

**Interfaces:**
- Produces:

```python
class DisclosureListItem(BaseModel):
    """목록 한 건. Node 목록 JSON과 필드를 맞춘다."""

    rcept_no: str
    report_type: str
    corp_code: str | None = None
    corp_name: str | None = None
    report_nm: str | None = None
    rcept_dt: str | None = None
    url: str  # disclosure main.do URL
    # 기타 features는 extra 허용
    model_config = ConfigDict(extra="allow")


class DisclosureListResult(BaseModel):
    listed_count: int
    items: list[DisclosureListItem]


class EntryCollector(Protocol):
    async def collect(self, request: CollectRequest) -> list[EntryRecord]:
        """하위 호환용 일괄 수집(테스트·예제). Admin 경로는 사용하지 않는다."""
        ...

    async def list_disclosures(self, request: CollectRequest) -> DisclosureListResult:
        """기간(보통 1일) 공시 목록과 원천 총건수를 반환한다."""
        ...

    async def extract_disclosure(
        self,
        disclosure: DisclosureListItem,
        *,
        include_attachments: bool = True,
    ) -> list[EntryRecord]:
        """공시 1건의 leaf 엔트리를 반환한다."""
        ...
```

- [ ] **Step 1–5:** 스키마 roundtrip 테스트 → 구현 → 커밋

```bash
git commit -m "feat(web-api): extend EntryCollector with list and extract_disclosure"
```

---

### Task 5: Node CLI 모드 + NodeEntryCollector

**Files:**
- Modify: `packages/entry-extractor/bin/collect-entries.js`
- Modify: `packages/entry-extractor/src/index.js` (필요 시 `fetchDisclosureList`/`buildEntries` re-export 확인)
- Modify: `packages/web-api/app/adapters/node_entry_collector.py`
- Test: `packages/web-api/tests/test_node_entry_collector_modes.py` (subprocess를 모킹하거나, stdin/stdout 계약만 단위 테스트 가능한 헬퍼 분리)

**Interfaces:**
- CLI stdin JSON:
  - `{ "mode": "list", "report_type", "start_date", "end_date", "max_total"? }`
    → stdout: `{ "listed_count": N, "items": [ disclosure, ... ] }`
  - `{ "mode": "extract", "disclosure": {...}, "include_attachments": true }`
    → stdout: `Entry[]`
  - `{ "mode": "collect", ... }` 또는 mode 생략 → 기존 일괄 동작 유지
- `NodeEntryCollector.list_disclosures` / `extract_disclosure`는 기존 `_run_script(payload)` 헬퍼로 공통화

- [ ] **Step 1: Write failing adapter test with mocked subprocess**

`_run_json`이 `{"listed_count":2,"items":[...]}`를 파싱해 `DisclosureListResult`를 반환하는지 검증. `extract`는 entry 배열.

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement CLI branches**

`collect-entries.js`:

```javascript
const mode = params.mode || 'collect';
if (mode === 'list') {
  const { fetchDisclosureList } = require('../src');
  const items = await fetchDisclosureList({...});
  // listed_count: fetchDisclosureList가 total을 반환하지 않으므로
  // list.js를 확장해 { items, listed_count }를 반환하거나 onProgress total을 캡처한다.
  process.stdout.write(JSON.stringify({ listed_count, items }));
  return;
}
if (mode === 'extract') {
  const { parseDetail } = require('../src/documents'); // 실제 export 경로에 맞춤
  const { buildEntries } = require('../src');
  const detail = await parseDetail(params.disclosure.url, { disclosure: params.disclosure });
  const entries = buildEntries(params.disclosure, detail, {
    includeAttachments: params.include_attachments ?? true,
  });
  process.stdout.write(JSON.stringify(entries));
  return;
}
// collect: 기존
```

**중요:** `fetchDisclosureList`가 현재 `items`만 반환하므로, `listed_count`(pageInfo 총건수)를 함께 반환하도록 `list.js`를 최소 수정한다. 예: 반환을 `{ disclosures, listedCount }`로 바꾸거나 별도 함수 `fetchDisclosureListWithTotal` 추가. **기존 `collectEntries` 호출부는 깨지지 않게** 어댑트한다(배열만 쓰던 곳은 `.disclosures` 또는 하위 호환 래퍼).

권장: `fetchDisclosureList`는 배열 반환 유지, CLI list 모드에서 pageInfo를 읽는 얇은 래퍼 `fetchDisclosureListResult`를 `list.js`에 추가해 `{ listedCount, disclosures }` 반환.

- [ ] **Step 4: Adapter + 테스트 PASS**

- [ ] **Step 5: Commit**

```bash
git add packages/entry-extractor packages/web-api/app/adapters/node_entry_collector.py packages/web-api/tests/test_node_entry_collector_modes.py
git commit -m "feat: add list/extract CLI modes for resumable collection"
```

---

### Task 6: CatalogService 오케스트레이터 (collect + resume)

**Files:**
- Modify: `packages/web-api/app/services/catalog_service.py`
- Modify: `packages/web-api/app/repositories/job_repository.py` (`create`에 `mode` 전달)
- Modify: `packages/web-api/tests/test_catalog_service.py` (FakeCollector에 list/extract 추가, 기존 테스트 갱신)
- Create: `packages/web-api/tests/test_catalog_orchestrator.py`

**Interfaces:**
- Consumes: `EntryCollector.list_disclosures`, `extract_disclosure`, `SliceRepository`, `EntryRepository`, `DisclosureRepository`, `JobRepository`
- Produces:
  - `start_extract(request) -> ExtractResponse` (기존, `mode=collect` 또는 기간이 기본 7일 윈도우면 `rescan` — 단순화: 요청에 `mode` 필드 없으면 `collect`)
  - `start_resume(*, slice_id: str | None = None, report_type: str | None = None) -> ExtractResponse`
  - `run_job(job_id, request | ResumeSpec)` — 날짜 루프
  - `soft_stop(job_id) -> None` — 플래그 설정 (Task 7에서 완성해도 됨)
  - 헬퍼: `_iter_dates(start, end) -> list[str]` YYYYMMDD
  - 공시 성공 시: `upsert_many(entries)` + `disclosures_from_records`로 해당 rcp만 upsert + attempt succeeded
  - skip: attempt already succeeded → 파싱 호출 없이 succeeded 집계에 포함

- [ ] **Step 1: Write failing orchestrator tests**

```python
class ScriptedCollector:
    """list는 고정 3건, extract는 rcept_no=='fail'일 때 1회 실패 후 성공 등 스크립트."""

    async def list_disclosures(self, request): ...
    async def extract_disclosure(self, disclosure, *, include_attachments=True): ...
    async def collect(self, request):  # unused
        raise NotImplementedError


async def test_partial_failure_keeps_succeeded_and_resume_fills_gap(...):
    # day with 3 items; middle extract raises SourceFetchError once then succeeds on resume
    # after first run: 2 succeeded, 1 failed, slice not complete
    # resume: only failed extracted again → complete


async def test_skip_already_succeeded_on_rescan(...):
    # extract call count == 0 for already succeeded rcept_no
```

기존 `FakeCollector`는 Protocol을 만족하도록 `list_disclosures`/`extract_disclosure`를 추가하고, `test_run_job_saves_entries_and_marks_success`는 새 오케스트레이터 동작(공시 단위 저장)에 맞게 수정한다.

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement orchestrator**

의사코드:

```python
async def run_job(self, job_id: str, request: ExtractRequest) -> None:
    await mark_running(job_id)
    stop = False
    for day in _iter_dates(request.start_date, request.end_date):
        if await self._is_soft_stopped(job_id):
            break
        slice_row = await slices.get_or_create_slice(request.report_type, day)
        await slices.mark_slice_status(slice_row.slice_id, "running")
        day_req = request.model_copy(update={"start_date": day, "end_date": day})
        try:
            listed = await self._collector.list_disclosures(day_req)
        except Exception as exc:
            await slices.mark_slice_status(..., "failed")
            await jobs.add_log(..., f"목록 수집 실패 {day}: {exc}")
            continue
        await slices.set_listed(slice_id, listed.listed_count, job_id)
        for item in listed.items:
            attempt = await slices.get_attempt(item.rcept_no)
            if attempt and attempt.status == "succeeded":
                continue
            # extract + upsert + attempt (재시도는 Task 7)
            ...
        await slices.recompute_counts(...)
        await slices.evaluate_complete(...)
    # job succeeded if no unexpected abort; partial failures → job status succeeded with logs, or keep running policy: mark succeeded when loop ends
```

Job 종료 정책: 루프가 끝나면 `mark_succeeded` (저장된 entry 합계). 개별 공시 실패는 job 전체를 failed로 만들지 않는다. 목록 전패·예외로 job 자체가 죽으면 `mark_failed`.

`start_resume`: incomplete slices의 min/max date로 `ExtractRequest`를 만들거나 `ResumeSpec(slice_ids=...)`를 도입. 단순화: `ResumeRequest(slice_id: str | None, report_type: str | None)`이고 `run_resume_job`이 incomplete 슬라이스만 돌며 failed/blocked/pending attempt만 extract.

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(web-api): orchestrate catalog collect by day slice and rcp_no"
```

---

### Task 7: 공시 재시도 · blocked · soft-stop

**Files:**
- Modify: `packages/web-api/app/services/catalog_service.py`
- Modify: `packages/web-api/app/config.py` (이미 Task 1)
- Test: `packages/web-api/tests/test_catalog_orchestrator.py` 확장

**Interfaces:**
- `_extract_with_retries(item) -> list[EntryRecord] | None`
  - `disclosure_max_retries`회, 지수 백오프 `2**attempt` 초 (테스트에서는 monkeypatch sleep)
  - `SourceFetchError` 메시지에 `403`/`429`/`연결` 포함 또는 별도 `BlockingError` 플래그 → block streak++
  - streak >= `block_streak_threshold` → slice/job status `blocked`, `asyncio.sleep(block_wait_seconds)` 후 streak 리셋하고 재개(테스트에서는 wait=0)
- `request_soft_stop(job_id)` / in-memory `set[str]` 또는 DB job status `stopping` — 다음 공시 경계에서 break, succeeded 유지
- `POST` soft-stop은 Task 8 API에서 노출

- [ ] **Step 1: Failing tests**

```python
async def test_transient_failure_retries_then_succeeds(...)
async def test_block_streak_marks_slice_blocked(...)
async def test_soft_stop_keeps_succeeded(...)
```

- [ ] **Step 2–4:** 구현·PASS

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(web-api): add disclosure retries, blocked wait, and soft-stop"
```

---

### Task 8: Admin API (auth · resume · slices · retry)

**Files:**
- Modify: `packages/web-api/app/api/deps.py`
- Modify: `packages/web-api/app/api/admin/catalog.py`
- Modify: `packages/web-api/app/schemas/catalog.py`
- Modify: `packages/web-api/tests/test_catalog_api.py`
- Create: `packages/web-api/tests/test_admin_slices_api.py`

**Interfaces:**
- `async def require_admin(request: Request) -> None`:
  - 헤더 `X-Admin-Token` == `settings.admin_token` 또는 쿠키 `admin_token` == token
  - 아니면 `Unauthorized("Admin 토큰이 필요합니다.")`
- 모든 `/admin/catalog/*` 라우트에 `Depends(require_admin)`
- 스키마:
  - `ResumeRequest(slice_id: str | None = None, report_type: str | None = None)`
  - `SliceSummary`, `SliceDetailResponse`, `DisclosureAttemptItem`
- 엔드포인트:
  - `POST /admin/catalog/resume` → 202 + job_id
  - `GET /admin/catalog/slices`
  - `GET /admin/catalog/slices/{slice_id}`
  - `POST /admin/catalog/slices/{slice_id}/retry` → resume with that slice_id
  - `POST /admin/catalog/jobs/{job_id}/soft-stop` → 202

- [ ] **Step 1: Failing API tests**

```python
async def test_extract_requires_admin_token(client_factory):
    # no header → 401

async def test_extract_with_token_ok(...):
    # X-Admin-Token → 202

async def test_list_slices_and_retry(...):
```

기존 `test_catalog_api.py`의 클라이언트 호출에 토큰 헤더를 추가한다.

- [ ] **Step 2–4:** 구현·PASS

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(web-api): protect admin catalog API and add resume/slices endpoints"
```

---

### Task 9: Admin UI (Jinja + HTMX)

**Files:**
- Create: `packages/web-api/app/api/admin/ui.py`
- Create: `packages/web-api/app/templates/admin/base.html`
- Create: `packages/web-api/app/templates/admin/token.html` — 토큰 입력 → Set-Cookie
- Create: `packages/web-api/app/templates/admin/index.html` — 수집 폼 + 슬라이스 테이블
- Create: `packages/web-api/app/templates/admin/slice_detail.html`
- Create: `packages/web-api/app/templates/admin/partials/slices_table.html`
- Modify: `packages/web-api/app/main.py` — `Jinja2Templates`, `StaticFiles`(선택), UI 라우터
- Add dependency: `jinja2` in `pyproject.toml` if missing
- Test: `packages/web-api/tests/test_admin_ui.py`

**Interfaces:**
- `GET /admin/token` — 토큰 폼 (인증 불필요)
- `POST /admin/token` — 쿠키 설정 후 `/admin`으로 리다이렉트
- `GET /admin` — `require_admin`, 수집 폼 + slices partial
- `GET /admin/slices` — HTMX partial (테이블)
- `GET /admin/slices/{slice_id}` — 상세 + 재시도 버튼
- HTMX: extract/resume/retry는 `hx-post`로 JSON API 호출 시 `hx-headers='{"X-Admin-Token":"..."}'`보다 **쿠키 인증**을 쓰므로 API `require_admin`이 쿠키를 받는지 확인(Task 8)

UI는 최소 스타일(가독성만). Public 브랜드 디자인 규칙 비적용.

- [ ] **Step 1: Failing smoke tests**

```python
async def test_admin_index_requires_auth(...):
    # 401 or redirect to /admin/token

async def test_admin_index_with_cookie_contains_slice_markers(...):
    # response.text includes "슬라이스" and "수집" and retry affordance ("재시도" or hx-post retry)
```

- [ ] **Step 2–4:** 템플릿·라우트·PASS

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(web-api): add Jinja/HTMX admin UI for collect and completeness"
```

---

### Task 10: 문서 갱신

**Files:**
- Modify: `packages/web-api/README.md`
- Modify: `README.md` (루트 — Admin `/admin` 한 줄 + 토큰)

- [ ] **Step 1:** README에 Admin 오케스트레이션·슬라이스 API·`/admin`·`ADMIN_TOKEN`·재개 동작을 한국어로 문서화

- [ ] **Step 2:** 전체 테스트

Run: `.venv\Scripts\python.exe -m pytest -v`  
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git commit -m "docs: document admin resume collection and /admin UI"
```

---

## Spec coverage checklist

| Spec 요구 | Task |
|-----------|------|
| 날짜 슬라이스 + rcp_no 체크포인트 | 2, 3, 6 |
| Python 오케스트레이터 / Node list+extract | 4, 5, 6 |
| listed_count 완전성 (skip 포함 succeeded) | 3, 6 |
| 최근 7일 기본(UI) · 기간 변경 | 9 |
| 자동 재시도 + blocked + 수동 resume/retry | 7, 8 |
| Jinja/HTMX `/admin` | 9 |
| X-Admin-Token 헤더+쿠키 | 1, 8, 9 |
| soft-stop | 7, 8 |
| 기존 extract 스키마 유지·배치 교체 | 6, 8 |
| 테스트 픽스처·가짜 collector | 6, 7, 8 |
| 비범위(Public UI, cron, Alembic…) | 계획에 포함하지 않음 |

## Self-review notes

- Placeholder 없음: CLI list의 `listed_count`는 Task 5에서 `fetchDisclosureListResult`로 명시
- `collect()` Protocol 메서드는 하위 호환·테스트용으로 유지하되 Admin `run_job`은 사용하지 않음
- Job `mode`와 Resume 경로가 Task 6·8에서 일치
- UI 인증은 쿠키, API는 헤더 또는 쿠키 — Task 8 `require_admin`이 둘 다 검사
