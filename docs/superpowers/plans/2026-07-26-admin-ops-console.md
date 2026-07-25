# Admin Ops Console (좌우 분할 · 30년 완전성) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/admin`을 좌측 완전성 탐색(연도 요약 → 선택 연도 일별 히트맵 → 슬라이스 요약)과 우측 실행 모니터(Job 카드 · 접힌 수집 폼 · warn/error 로그) 2열 ops console로 재배치한다.

**Architecture:** `SliceQueryService`에 연도 요약·연도 창 히트맵을 추가하고, `JobRepository.latest()`로 최신 job을 읽어 상태/로그 HTML partial을 HTMX로 폴링한다. Jinja 템플릿만 2열 그리드로 재구성하며 수집 파이프라인·완전성 판정·색 의미는 변경하지 않는다.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy async, Jinja2, HTMX, pytest

## Global Constraints

- 모든 코드 주석, Docstring, 화면 문구, 로그와 예외 메시지는 한국어로 작성한다.
- I/O 함수는 `async`/`await`와 명확한 타입 힌트를 사용한다.
- 수집 파이프라인·재개 알고리즘·`SliceProgress.status` 판정 규칙을 바꾸지 않는다.
- 히트맵 색: 완료 `#2ea043`, 미완성 `#d1242f`, 미입수 `#ebedf0`(다크 `#30363d`), 미래 투명.
- 새 JS 차트 라이브러리를 추가하지 않는다. HTMX + 최소 인라인/템플릿 동작만 허용한다.
- `year=None`일 때 `heatmap()`은 기존 “최근 53주” 동작을 유지한다(회귀).
- 일시정지는 백엔드에 없으므로 Job 카드 제어는 **소프트스톱만** 노출한다.
- 현재 작업 트리의 미커밋 DB 스키마 보정(`ensure_schema` 등)은 이 계획 커밋에 섞지 않는다.

---

## File Map

- `packages/web-api/app/schemas/catalog.py` — `YearSummaryItem` / `YearSummaryResponse` 추가
- `packages/web-api/app/services/slice_query_service.py` — `year_summary`, `heatmap(year=…)` 확장
- `packages/web-api/app/repositories/job_repository.py` — `latest()`
- `packages/web-api/app/services/catalog_service.py` — `get_latest_status()` (없으면 idle)
- `packages/web-api/app/api/admin/ui.py` — year/heatmap/job/form partial 라우트, 대시보드 컨텍스트
- `packages/web-api/app/templates/admin/index.html` — 2열 ops console
- `packages/web-api/app/templates/admin/base.html` — 그리드·연도 바·카드 CSS
- `packages/web-api/app/templates/admin/partials/year_bar.html` — 연도 요약 바
- `packages/web-api/app/templates/admin/partials/heatmap.html` — 연도 쿼리·폼 프리필 링크 반영
- `packages/web-api/app/templates/admin/partials/slices_summary.html` — 선택 연도 문제 칩
- `packages/web-api/app/templates/admin/partials/job_card.html` — Job 상태 카드
- `packages/web-api/app/templates/admin/partials/collect_form.html` — 접힘 수집 폼
- `packages/web-api/app/templates/admin/partials/job_logs.html` — 로그
- `packages/web-api/tests/test_slice_query_service.py` — 연도 요약·연도 히트맵
- `packages/web-api/tests/test_job_repository.py` — `latest()`
- `packages/web-api/tests/test_admin_ui.py` — 2열·partial·인증 스모크
- `packages/web-api/README.md` — Ops Console 레이아웃 설명

---

### Task 1: 연도 요약 스키마 + `year_summary`

**Files:**
- Modify: `packages/web-api/app/schemas/catalog.py`
- Modify: `packages/web-api/app/services/slice_query_service.py`
- Test: `packages/web-api/tests/test_slice_query_service.py`

**Interfaces:**
- Consumes: `SliceRepository.list_slices_between(start_date: str, end_date: str) -> list[SliceProgress]`
- Produces:
  - `YearSummaryItem(year: int, level: Literal["complete","incomplete","missing"])`
  - `YearSummaryResponse(items: list[YearSummaryItem], selected_year: int)`
  - `SliceQueryService.year_summary(*, report_type: str | None = None, today: date | None = None) -> YearSummaryResponse`

- [ ] **Step 1: 실패 테스트 작성**

`test_slice_query_service.py`에 추가:

```python
from app.schemas.catalog import YearSummaryResponse


async def test_year_summary_marks_levels_and_selects_latest_incomplete() -> None:
    rows = [
        _slice("F001", "20240115", "complete", succeeded=1, listed_count=1),
        _slice("F001", "20250110", "blocked", succeeded=0, listed_count=2),
        _slice("F001", "20250301", "complete", succeeded=1, listed_count=1),
        _slice("A001", "20260101", "complete", succeeded=1, listed_count=1),
    ]
    service = SliceQueryService(FakeSliceRepository(rows), report_types=("F001",))
    result = await service.year_summary(report_type="F001", today=date(2026, 7, 26))

    assert isinstance(result, YearSummaryResponse)
    by_year = {item.year: item.level for item in result.items}
    assert by_year[2024] == "complete"
    assert by_year[2025] == "incomplete"
    assert by_year[2026] == "missing"  # F001만 필터 → 2026에 F001 없음
    assert result.selected_year == 2025
    assert result.items[0].year <= result.items[-1].year


async def test_year_summary_empty_uses_fallback_range() -> None:
    service = SliceQueryService(FakeSliceRepository([]), report_types=("F001",))
    result = await service.year_summary(today=date(2026, 7, 26))

    assert result.items[0].year == 1999
    assert result.items[-1].year == 2026
    assert all(item.level == "missing" for item in result.items)
    assert result.selected_year == 2026
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```powershell
cd packages/web-api
.venv\Scripts\python.exe -m pytest tests/test_slice_query_service.py::test_year_summary_marks_levels_and_selects_latest_incomplete tests/test_slice_query_service.py::test_year_summary_empty_uses_fallback_range -q
```

Expected: `ImportError` 또는 `AttributeError: year_summary`

- [ ] **Step 3: 스키마 추가**

`catalog.py`의 `HeatmapResponse` 아래에:

```python
class YearSummaryItem(BaseModel):
    """연도 하나의 완전성 요약."""

    year: int
    level: Literal["complete", "incomplete", "missing"]


class YearSummaryResponse(BaseModel):
    """연도 요약 바와 기본 선택 연도."""

    items: list[YearSummaryItem] = Field(default_factory=list)
    selected_year: int
```

- [ ] **Step 4: `year_summary` 구현**

`slice_query_service.py`에 상수와 메서드 추가:

```python
FALLBACK_START_YEAR = 1999


async def year_summary(
    self,
    *,
    report_type: str | None = None,
    today: date | None = None,
) -> YearSummaryResponse:
    """연도별 완전성 요약과 기본 선택 연도를 만든다."""
    end = today or date.today()
    start_bound = f"{FALLBACK_START_YEAR}0101"
    end_bound = end.strftime("%Y%m%d")
    rows = await self._slices.list_slices_between(start_bound, end_bound)
    if report_type:
        key = report_type.strip().upper()
        rows = [row for row in rows if row.report_type.strip().upper() == key]

    by_year: dict[int, list[str]] = {}
    for row in rows:
        year = int(row.slice_date[:4])
        by_year.setdefault(year, []).append(row.status)

    if by_year:
        first_year = min(by_year)
    else:
        first_year = FALLBACK_START_YEAR
    items: list[YearSummaryItem] = []
    for year in range(first_year, end.year + 1):
        statuses = by_year.get(year, [])
        if not statuses:
            level = "missing"
        elif any(status != "complete" for status in statuses):
            level = "incomplete"
        else:
            level = "complete"
        items.append(YearSummaryItem(year=year, level=level))

    selected = end.year
    for item in reversed(items):
        if item.level == "incomplete":
            selected = item.year
            break
    return YearSummaryResponse(items=items, selected_year=selected)
```

`YearSummaryItem`, `YearSummaryResponse` import 추가.

- [ ] **Step 5: 테스트 통과 확인**

Run: 위와 동일 pytest 명령  
Expected: PASS

- [ ] **Step 6: Commit**

```powershell
git add packages/web-api/app/schemas/catalog.py packages/web-api/app/services/slice_query_service.py packages/web-api/tests/test_slice_query_service.py
git commit -m "feat(web-api): 연도별 완전성 요약 year_summary 추가"
```

---

### Task 2: `heatmap(year=…)` 연도 창 확장

**Files:**
- Modify: `packages/web-api/app/services/slice_query_service.py`
- Test: `packages/web-api/tests/test_slice_query_service.py`

**Interfaces:**
- Consumes: 기존 `_cell`, `_month_labels`
- Produces: `SliceQueryService.heatmap(*, year: int | None = None, report_type: str | None = None, today: date | None = None) -> HeatmapResponse`
  - `year=None`: 기존 최근 53주
  - `year=int`: 그 해 1/1이 속한 주 일요일 ~ min(12/31, today) ; 주 수는 가변

- [ ] **Step 1: 실패 테스트 작성**

```python
async def test_heatmap_year_window_starts_on_sunday_of_jan1_week() -> None:
    # 2018-01-01은 월요일 → 주 시작은 2017-12-31(일)
    rows = [
        _slice("F001", "20180102", "complete", succeeded=1, listed_count=1),
        _slice("F001", "20180615", "blocked", succeeded=0, listed_count=1),
    ]
    repo = FakeSliceRepository(rows)
    service = SliceQueryService(repo, report_types=("F001",))
    result = await service.heatmap(year=2018, today=date(2026, 7, 26))

    assert result.start_date == "20171231"
    assert result.end_date == "20181231"
    assert repo.range == ("20171231", "20181231")
    assert len(result.rows) == 1
    week_count = len(result.rows[0].weeks)
    assert 52 <= week_count <= 54
    # 2018-06-15는 incomplete
    june = next(
        cell
        for week in result.rows[0].weeks
        for cell in week
        if cell.slice_date == "20180615"
    )
    assert june.level == "incomplete"


async def test_heatmap_year_none_keeps_rolling_53_weeks() -> None:
    service = SliceQueryService(FakeSliceRepository([]), report_types=("F001",))
    result = await service.heatmap(today=date(2026, 7, 22))
    assert len(result.rows[0].weeks) == 53
    assert result.end_date == "20260722"
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```powershell
cd packages/web-api
.venv\Scripts\python.exe -m pytest tests/test_slice_query_service.py::test_heatmap_year_window_starts_on_sunday_of_jan1_week -q
```

Expected: FAIL (`heatmap()` unexpected keyword `year`)

- [ ] **Step 3: `heatmap` 시그니처·연도 창 구현**

기존 `heatmap`을 다음처럼 교체/확장한다.

```python
async def heatmap(
    self,
    *,
    year: int | None = None,
    report_type: str | None = None,
    today: date | None = None,
) -> HeatmapResponse:
    """완전성 격자를 만든다. year가 없으면 최근 53주, 있으면 해당 연도 창."""
    end_today = today or date.today()
    if year is None:
        end = end_today
        anchor = end - timedelta(weeks=WEEK_COUNT - 1)
        days_since_sunday = (anchor.weekday() + 1) % DAY_COUNT
        start = anchor - timedelta(days=days_since_sunday)
        week_count = WEEK_COUNT
    else:
        jan1 = date(year, 1, 1)
        year_end = date(year, 12, 31)
        days_since_sunday = (jan1.weekday() + 1) % DAY_COUNT
        start = jan1 - timedelta(days=days_since_sunday)
        end = min(year_end, end_today)
        # 연말(12/31)이 속한 주까지 열을 확보. 주 수는 보통 53, 최대 54.
        week_count = ((year_end - start).days // DAY_COUNT) + 1

    rows = await self._slices.list_slices_between(
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
    )
    if report_type:
        key = report_type.strip().upper()
        rows = [row for row in rows if row.report_type.strip().upper() == key]

    by_key = {(row.report_type.strip().upper(), row.slice_date): row for row in rows}
    discovered = sorted(
        {row.report_type.strip().upper() for row in rows} - set(self._report_types)
    )
    report_types = [*self._report_types, *discovered]
    if report_type:
        report_types = [report_type.strip().upper()]

    heatmap_rows = [
        HeatmapRow(
            report_type=rt,
            weeks=[
                [
                    self._cell(
                        rt,
                        start + timedelta(days=week * DAY_COUNT + weekday),
                        end_today,
                        by_key,
                    )
                    for weekday in range(DAY_COUNT)
                ]
                for week in range(week_count)
            ],
        )
        for rt in report_types
    ]
    return HeatmapResponse(
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        month_labels=self._month_labels(start, week_count),
        rows=heatmap_rows,
    )
```

`_month_labels`를 `week_count` 인자를 받도록 바꾼다:

```python
@staticmethod
def _month_labels(start: date, week_count: int = WEEK_COUNT) -> list[HeatmapMonthLabel]:
    labels: list[HeatmapMonthLabel] = []
    previous_month: int | None = None
    for week_index in range(week_count):
        week_start = start + timedelta(weeks=week_index)
        month = week_start.month
        if month != previous_month:
            labels.append(
                HeatmapMonthLabel(week_index=week_index, label=MONTH_LABELS[month - 1])
            )
            previous_month = month
    return labels
```

기존 `test_heatmap_*`가 `_month_labels(start)` 호출을 깨지 않도록 기본값 `WEEK_COUNT`를 유지한다.

- [ ] **Step 4: 테스트 통과 + 기존 히트맵 회귀**

```powershell
cd packages/web-api
.venv\Scripts\python.exe -m pytest tests/test_slice_query_service.py -q
```

Expected: PASS (전부)

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api/app/services/slice_query_service.py packages/web-api/tests/test_slice_query_service.py
git commit -m "feat(web-api): 히트맵에 선택 연도 창 지원"
```

---

### Task 3: `JobRepository.latest` + `CatalogService.get_latest_status`

**Files:**
- Modify: `packages/web-api/app/repositories/job_repository.py`
- Modify: `packages/web-api/app/services/catalog_service.py`
- Test: `packages/web-api/tests/test_job_repository.py`
- Test: `packages/web-api/tests/test_catalog_service.py` (기존 패턴에 맞춰 1건 추가; 파일에 유사 fixture가 없으면 job_repository 테스트만으로도 충분하고, 서비스는 Task 4에서 라우트로 검증)

**Interfaces:**
- Produces:
  - `JobRepository.latest() -> CatalogJob | None` (`created_at` 내림차순 1건)
  - `CatalogService.get_latest_status() -> JobStatusResponse | None`

- [ ] **Step 1: 실패 테스트**

`test_job_repository.py`에:

```python
async def test_latest_returns_most_recent_job(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        await repository.create("job-old", {"report_type": "F001"}, "k-old")
        await repository.create("job-new", {"report_type": "A001"}, "k-new")
        await session.commit()

    async with sessionmaker_fixture() as session:
        latest = await JobRepository(session).latest()

    assert latest is not None
    assert latest.job_id == "job-new"


async def test_latest_returns_none_when_empty(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        latest = await JobRepository(session).latest()
    assert latest is None
```

- [ ] **Step 2: 실패 확인**

```powershell
cd packages/web-api
.venv\Scripts\python.exe -m pytest tests/test_job_repository.py::test_latest_returns_most_recent_job -q
```

Expected: `AttributeError: latest`

- [ ] **Step 3: 구현**

`job_repository.py`:

```python
async def latest(self) -> CatalogJob | None:
    """가장 최근에 만든 작업을 1건 반환한다."""
    statement = select(CatalogJob).order_by(CatalogJob.created_at.desc()).limit(1)
    return (await self._session.execute(statement)).scalars().first()
```

`catalog_service.py`:

```python
async def get_latest_status(self) -> JobStatusResponse | None:
    """최신 작업 현황을 반환한다. 작업이 없으면 None."""
    async with self._sessionmaker() as session:
        jobs = JobRepository(session)
        job = await jobs.latest()
        if job is None:
            return None
        job_id = job.job_id
    return await self.get_status(job_id)
```

- [ ] **Step 4: 테스트 통과**

```powershell
cd packages/web-api
.venv\Scripts\python.exe -m pytest tests/test_job_repository.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api/app/repositories/job_repository.py packages/web-api/app/services/catalog_service.py packages/web-api/tests/test_job_repository.py
git commit -m "feat(web-api): 최신 수집 job 조회 latest/get_latest_status"
```

---

### Task 4: Job 카드 · 로그 partial 라우트

**Files:**
- Create: `packages/web-api/app/templates/admin/partials/job_card.html`
- Create: `packages/web-api/app/templates/admin/partials/job_logs.html`
- Modify: `packages/web-api/app/api/admin/ui.py`
- Modify: `packages/web-api/tests/test_admin_ui.py`

**Interfaces:**
- Consumes: `CatalogService.get_latest_status()`, `get_status(job_id)`, `request_soft_stop`
- Produces:
  - `GET /admin/job-status` → `job_card.html`
  - `GET /admin/job-logs?levels=warn,error` → `job_logs.html`
  - (선택) `POST /admin/jobs/{job_id}/soft-stop` HTML 폼용 래퍼 → 기존 JSON API를 폼에서 쓰려면 `action="/admin/catalog/jobs/{id}/soft-stop"` 대신 UI 라우트에서 303 리다이렉트

- [ ] **Step 1: partial 템플릿 작성**

`job_card.html`:

```html
{% if job %}
<section class="job-card" data-status="{{ job.status }}">
  <div class="job-card-head">
    <strong>Job {{ job.job_id[:8] }} · {{ job.mode }}</strong>
    <span class="job-chip job-chip-{{ job.status }}">{{ job.status }}</span>
  </div>
  {% set total = job.total_entries or 0 %}
  {% set saved = job.saved_entries or 0 %}
  {% set pct = (saved * 100 // total) if total else 0 %}
  <div class="job-progress"><i style="width: {{ pct }}%"></i></div>
  <dl class="job-meta">
    <div><dt>범위</dt><dd>{{ job.params.get('start_date', '—') }} ~ {{ job.params.get('end_date', '—') }}</dd></div>
    <div><dt>유형</dt><dd>{{ job.params.get('report_type', '—') }}</dd></div>
    <div><dt>저장</dt><dd>{{ saved }} / {{ total }}</dd></div>
  </dl>
  {% if job.status in ('pending', 'running') %}
  <form method="post" action="/admin/jobs/{{ job.job_id }}/soft-stop">
    <button type="submit">소프트 스톱</button>
  </form>
  {% endif %}
  {% if job.error_message %}
  <p class="error">{{ job.error_message }}</p>
  {% endif %}
</section>
{% else %}
<section class="job-card job-card-idle">
  <strong>대기(idle)</strong>
  <p class="muted">아직 수집 작업이 없습니다.</p>
</section>
{% endif %}
```

`job_logs.html`:

```html
<section class="job-logs">
  <div class="job-logs-head">
    <strong>로그</strong>
    <span class="muted">기본: warn / error</span>
  </div>
  {% if logs %}
  <ul class="job-log-list">
    {% for log in logs %}
    <li class="job-log-{{ log.level }}"><span>{{ log.level|upper }}</span> {{ log.message }}</li>
    {% endfor %}
  </ul>
  {% else %}
  <p class="muted">표시할 로그가 없습니다.</p>
  {% endif %}
</section>
```

- [ ] **Step 2: UI 라우트 추가**

`ui.py`에 `get_catalog_service` import 후:

```python
@router.get("/job-status", response_class=HTMLResponse, summary="최신 Job 상태 카드")
async def job_status_partial(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    service: CatalogService = Depends(get_catalog_service),
) -> HTMLResponse:
    if not _has_valid_token(request, settings):
        return _to_token_page()
    job = await service.get_latest_status()
    return templates.TemplateResponse(
        request, "admin/partials/job_card.html", {"job": job}
    )


@router.get("/job-logs", response_class=HTMLResponse, summary="최신 Job 로그")
async def job_logs_partial(
    request: Request,
    levels: str = "warn,error",
    settings: Settings = Depends(get_settings_dep),
    service: CatalogService = Depends(get_catalog_service),
) -> HTMLResponse:
    if not _has_valid_token(request, settings):
        return _to_token_page()
    allowed = {level.strip().lower() for level in levels.split(",") if level.strip()}
    job = await service.get_latest_status()
    logs = []
    if job is not None:
        logs = [log for log in job.logs if log.level.lower() in allowed]
    return templates.TemplateResponse(
        request, "admin/partials/job_logs.html", {"job": job, "logs": logs}
    )


@router.post("/jobs/{job_id}/soft-stop", summary="소프트 스톱(폼)")
async def soft_stop_from_ui(
    request: Request,
    job_id: str,
    settings: Settings = Depends(get_settings_dep),
    service: CatalogService = Depends(get_catalog_service),
) -> RedirectResponse:
    if not _has_valid_token(request, settings):
        return _to_token_page()
    await service.request_soft_stop(job_id)
    return RedirectResponse("/admin", status_code=303)
```

- [ ] **Step 3: Admin UI 테스트에 FakeCatalogService 확장**

`test_admin_ui.py`의 fake에 `get_latest_status` / `request_soft_stop`를 넣고(기존 구조에 맞게), override `get_catalog_service`. 최소 스모크:

```python
async def test_job_status_partial_requires_token(client_factory) -> None:
    async with client_factory() as client:
        response = await client.get("/admin/job-status")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/admin/token")


async def test_job_status_and_logs_render_when_authenticated(client_factory) -> None:
    async with client_factory() as client:
        await client.post("/admin/token", data={"token": "dev-admin-token"})
        status = await client.get("/admin/job-status")
        logs = await client.get("/admin/job-logs")
    assert status.status_code == 200
    assert "대기(idle)" in status.text or "Job" in status.text
    assert logs.status_code == 200
```

Fake가 job을 반환하도록 구성하면 `"running"`/`소프트 스톱` 문자열도 assert 한다.

- [ ] **Step 4: 테스트 실행**

```powershell
cd packages/web-api
.venv\Scripts\python.exe -m pytest tests/test_admin_ui.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api/app/api/admin/ui.py packages/web-api/app/templates/admin/partials/job_card.html packages/web-api/app/templates/admin/partials/job_logs.html packages/web-api/tests/test_admin_ui.py
git commit -m "feat(web-api): Admin Job 상태·로그 HTMX partial"
```

---

### Task 5: 좌측 패널 — 연도 바 · 연도 히트맵 · 슬라이스 요약

**Files:**
- Create: `packages/web-api/app/templates/admin/partials/year_bar.html`
- Create: `packages/web-api/app/templates/admin/partials/slices_summary.html`
- Modify: `packages/web-api/app/templates/admin/partials/heatmap.html`
- Modify: `packages/web-api/app/api/admin/ui.py`
- Modify: `packages/web-api/tests/test_admin_ui.py`

**Interfaces:**
- Consumes: `year_summary`, `heatmap(year=…)`, `list_slices(start_date, end_date)`
- Produces:
  - `GET /admin/year-bar?report_type=`
  - `GET /admin/heatmap?year=&report_type=` (기존 확장)
  - `GET /admin/slices-summary?year=&report_type=`

- [ ] **Step 1: `year_bar.html`**

```html
<div class="year-bar" role="list">
  {% for item in year_summary.items %}
  <a role="listitem"
     class="year-bar-item year-bar-{{ item.level }}{% if item.year == selected_year %} is-selected{% endif %}"
     href="/admin?report_type={{ report_type }}&amp;year={{ item.year }}"
     title="{{ item.year }} · {{ item.level }}">
    <span class="year-bar-fill" style="height: {% if item.level == 'complete' %}90{% elif item.level == 'incomplete' %}55{% else %}25{% endif %}%"></span>
    <span class="year-bar-label">{{ item.year }}</span>
  </a>
  {% endfor %}
</div>
{% if not year_summary.items or year_summary.items|selectattr('level', 'ne', 'missing')|list|length == 0 %}
<p class="muted">아직 수집 이력이 없습니다.</p>
{% endif %}
```

- [ ] **Step 2: `slices_summary.html`**

```html
<div class="slices-summary">
  {% if problem_slices %}
  <ul class="slice-chips">
    {% for s in problem_slices %}
    <li class="slice-chip slice-chip-{{ s.status }}">
      <a href="/admin/slices/{{ s.slice_id }}">{{ s.slice_date[4:6] }}-{{ s.slice_date[6:8] }} · {{ s.status }}</a>
    </li>
    {% endfor %}
  </ul>
  {% else %}
  <p class="muted">선택 연도에 미완료 슬라이스가 없습니다.</p>
  {% endif %}
  <details class="slices-full">
    <summary>전체 보기</summary>
    {% include "admin/partials/slices_table.html" %}
  </details>
</div>
```

- [ ] **Step 3: `heatmap.html` 링크 조정**

- 미입수·미완성 셀: 우측 폼을 열도록  
  `href="/admin?report_type=…&year=…&start_date=…&end_date=…&expand_form=1"`
- 완료 셀: 기존 `/admin/slices/{id}` 유지
- HTMX 갱신 URL에 `year`/`report_type` 쿼리가 유지되도록 `index`에서 `hx-get`에 붙인다.

미완성(slice_id 있음)도 스펙대로 폼 프리필 링크로 바꾼다. 상세는 슬라이스 요약 칩으로 간다.

```html
{% elif cell.level == "complete" and cell.slice_id %}
<a class="heatmap-cell heatmap-complete" href="/admin/slices/{{ cell.slice_id }}" …></a>
{% else %}
<a class="heatmap-cell heatmap-{{ cell.level }}"
   href="/admin?report_type={{ row.report_type }}&amp;year={{ selected_year }}&amp;start_date={{ cell.slice_date }}&amp;end_date={{ cell.slice_date }}&amp;expand_form=1"
   title="…"></a>
{% endif %}
```

- [ ] **Step 4: 라우트**

`dashboard`와 partial에 `year: int | None = None` 추가. 잘못된 year는 `year_summary.selected_year`로 폴백.

```python
years = await slices.year_summary(report_type=report_type or None)
selected_year = year if year in {i.year for i in years.items} else years.selected_year
heatmap = await slices.heatmap(year=selected_year, report_type=report_type or None)
year_start = f"{selected_year}0101"
year_end = f"{selected_year}1231"
listing = await slices.list_slices(
    report_type=report_type or None,
    start_date=year_start,
    end_date=year_end,
    limit=500,
)
problem = [s for s in listing.items if s.status != "complete"]
```

`heatmap_partial`도 `year`, `report_type` 쿼리를 받는다.

```python
@router.get("/year-bar", …)
@router.get("/slices-summary", …)
```

각각 해당 partial 반환.

- [ ] **Step 5: FakeSliceQueryService에 `year_summary` / `heatmap(year=)` 추가 후 테스트**

기존 `FakeSliceQueryService.heatmap` 시그니처를 `**kwargs` 또는 `year=None`으로 맞춘다.  
`test_admin_index_renders_heatmap_links_and_legend`의 기대 href를 새 프리필 URL에 맞게 수정.

- [ ] **Step 6: 테스트 · Commit**

```powershell
cd packages/web-api
.venv\Scripts\python.exe -m pytest tests/test_admin_ui.py tests/test_slice_query_service.py -q
```

```powershell
git add packages/web-api/app/api/admin/ui.py packages/web-api/app/templates/admin/partials packages/web-api/tests/test_admin_ui.py
git commit -m "feat(web-api): Admin 좌측 연도 바·연도 히트맵·슬라이스 요약"
```

---

### Task 6: 접힘 수집 폼 + 대시보드 2열 조립

**Files:**
- Create: `packages/web-api/app/templates/admin/partials/collect_form.html`
- Modify: `packages/web-api/app/templates/admin/index.html`
- Modify: `packages/web-api/app/templates/admin/base.html`
- Modify: `packages/web-api/app/api/admin/ui.py` (`expand_form` 쿼리)
- Modify: `packages/web-api/README.md`
- Modify: `packages/web-api/tests/test_admin_ui.py`

**Interfaces:**
- Consumes: Task 4–5 partials
- Produces: `/admin` 2열 레이아웃; `expand_form=1`이면 폼 `<details open>`

- [ ] **Step 1: `collect_form.html`**

```html
<details class="collect-form" {% if expand_form %}open{% endif %}>
  <summary>수집 시작</summary>
  <p class="muted">기간은 하루 단위 슬라이스로 나눕니다. 기본은 최근 7일 겹침 수집입니다.</p>
  <form class="inline" method="post" action="/admin/collect">
    <label>공시 유형
      <input type="text" name="report_type" value="{{ report_type }}" required>
    </label>
    <label>시작일
      <input type="text" name="start_date" value="{{ start_date }}" pattern="\d{8}" required>
    </label>
    <label>종료일
      <input type="text" name="end_date" value="{{ end_date }}" pattern="\d{8}" required>
    </label>
    <label>첨부 포함
      <input type="checkbox" name="include_attachments" value="true" checked>
    </label>
    <button type="submit">수집 시작</button>
  </form>
  <form class="inline" method="post" action="/admin/resume" style="margin-top:8px">
    <input type="hidden" name="report_type" value="{{ report_type }}">
    <button type="submit">미완료 이어하기</button>
  </form>
</details>
```

- [ ] **Step 2: `index.html` 2열 재작성**

```html
{% extends "admin/base.html" %}
{% block title %}수집 대시보드{% endblock %}
{% block content %}
<header class="ops-topbar">
  <div>
    <h2>수집 · 완전성</h2>
    <p class="muted">왼쪽에서 빈 구간을 찾고, 오른쪽에서 작업을 모니터링합니다.</p>
  </div>
  <div id="ops-job-chip"
       hx-get="/admin/job-status"
       hx-trigger="load, every 5s"
       hx-select=".job-chip, .job-card-idle strong"
       hx-swap="innerHTML">
    <span class="job-chip">…</span>
  </div>
</header>

<div class="ops-grid">
  <section class="ops-left" aria-label="완전성 탐색">
    <h3>연도 요약</h3>
    {% include "admin/partials/year_bar.html" %}

    <h3>{{ selected_year }} · 일별 완전성</h3>
    <div class="heatmap-scroll"
         hx-get="/admin/heatmap?year={{ selected_year }}&report_type={{ report_type }}"
         hx-trigger="every 30s"
         hx-swap="innerHTML">
      {% include "admin/partials/heatmap.html" %}
    </div>

    <h3>선택 연도 슬라이스</h3>
    <div hx-get="/admin/slices-summary?year={{ selected_year }}&report_type={{ report_type }}"
         hx-trigger="every 5s"
         hx-swap="innerHTML">
      {% include "admin/partials/slices_summary.html" %}
    </div>
  </section>

  <aside class="ops-right" aria-label="실행 컨트롤">
    <h3>Job</h3>
    <div hx-get="/admin/job-status" hx-trigger="load, every 5s" hx-swap="innerHTML">
      {% include "admin/partials/job_card.html" %}
    </div>

    <h3>수집</h3>
    {% include "admin/partials/collect_form.html" %}

    <h3>로그</h3>
    <div hx-get="/admin/job-logs?levels=warn,error" hx-trigger="load, every 5s" hx-swap="innerHTML">
      {% include "admin/partials/job_logs.html" %}
    </div>
  </aside>
</div>
{% endblock %}
```

대시보드 컨텍스트에 `year_summary`, `selected_year`, `problem_slices`, `expand_form`, `job`, `logs`를 넣는다. 초기 `job`/`logs`는 `get_latest_status()`로 채운다.

- [ ] **Step 3: `base.html` CSS**

추가 예:

```css
.ops-topbar { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:16px; }
.ops-grid { display:grid; grid-template-columns:1.4fr 1fr; gap:20px; align-items:start; }
@media (max-width:900px) { .ops-grid { grid-template-columns:1fr; } }
.year-bar { display:flex; gap:3px; align-items:flex-end; min-height:56px; overflow-x:auto; }
.year-bar-item { flex:1; min-width:14px; text-align:center; text-decoration:none; color:inherit; }
.year-bar-fill { display:block; width:100%; border-radius:2px; background:#ebedf0; }
.year-bar-complete .year-bar-fill { background:#2ea043; }
.year-bar-incomplete .year-bar-fill { background:#d1242f; }
.year-bar-item.is-selected { outline:2px solid #0969da; outline-offset:1px; }
.job-card { border:1px solid #d0d7de; border-radius:8px; padding:12px; }
.job-progress { height:6px; background:#eaeef2; border-radius:999px; overflow:hidden; }
.job-progress i { display:block; height:100%; background:#0969da; }
.job-chip { display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; background:#eaeef2; }
.job-chip-running { background:#dafbe1; }
.slice-chips { display:flex; flex-wrap:wrap; gap:6px; list-style:none; padding:0; }
.slice-chip { border-left:3px solid #d1242f; background:#f6f8fa; padding:4px 8px; border-radius:4px; }
.collect-form summary { cursor:pointer; font-weight:600; }
```

다크 모드에서 `.year-bar-missing`/미입수 회색을 `#30363d`로 맞춘다.

- [ ] **Step 4: 테스트 기대값 갱신**

- `test_admin_index_renders_collect_form_and_slices`: `<details class="collect-form"` / `ops-grid` / `연도 요약` 존재 assert
- `test_admin_query_prefills_collect_form`: `expand_form=1`일 때 `<details … open` assert
- 히트맵 링크 assert를 새 URL 패턴에 맞게 수정

- [ ] **Step 5: README**

`packages/web-api/README.md` Admin 섹션에 Ops Console(좌: 연도→일별, 우: Job/폼/로그)과 `?year=` / `expand_form=1` 쿼리를 한 단락으로 적는다.

- [ ] **Step 6: 전체 회귀 · Commit**

```powershell
cd packages/web-api
.venv\Scripts\python.exe -m pytest -q
```

Expected: 기존 통과 수 이상, 신규 테스트 전부

```powershell
git add packages/web-api/app/templates/admin packages/web-api/app/api/admin/ui.py packages/web-api/tests/test_admin_ui.py packages/web-api/README.md
git commit -m "feat(web-api): Admin Ops Console 좌우 2열 레이아웃"
```

---

## Spec Coverage Checklist

| Spec 항목 | Task |
|-----------|------|
| 좌우 2열 · 상단 바 | Task 6 |
| 연도 요약 바 · 색 · 기본 선택 | Task 1, 5 |
| 선택 연도 일별 히트맵 · 가변 주 수 | Task 2, 5 |
| 셀→폼 프리필 / 완료→상세 | Task 5, 6 |
| 슬라이스 요약 칩 + 전체 보기 | Task 5 |
| Job 카드 상시 · soft-stop · 폴링 | Task 3, 4, 6 |
| 폼 기본 접힘 · expand_form | Task 6 |
| 로그 warn/error 기본 | Task 4, 6 |
| year_summary / heatmap(year) / latest | Task 1–3 |
| 빈 데이터·잘못된 year·인증 | Task 1, 5–6 |
| 파이프라인/판정 불변 · 차트 라이브러리 금지 | Global Constraints |
| 좁은 화면 세로 스택 | Task 6 CSS |
| 일시정지 | **비구현**(백엔드 없음) — soft-stop만 |

## Self-Review Notes

- Placeholder/`TBD` 없음.
- `heatmap`/`_month_labels` 시그니처는 Task 2에서 통일; 기존 테스트는 `today=` 키워드만 사용하므로 호환.
- Fake 서비스 시그니처는 Task 5에서 `year`/`year_summary`를 반드시 맞출 것(테스트 깨짐 예방).
- Job 카드의 체크포인트 `rcp_no`는 params에 없을 수 있음 → 범위·유형·저장 수치만 표시(스펙의 “가능하면” 수준). 오케스트레이터가 params에 넣기 시작하면 같은 카드에 필드 추가.
