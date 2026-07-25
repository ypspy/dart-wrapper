# Admin 완전성 히트맵 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin 대시보드에 보고서 타입별 최근 53주 수집 완전성을 GitHub contribution 그래프 형태로 표시한다.

**Architecture:** `SliceRepository`가 기간 내 모든 슬라이스를 조회하고, `SliceQueryService`가 고정 보고서 타입과 DB 발견 타입을 합쳐 53주×7일 셀 모델을 만든다. Jinja partial이 이 모델을 CSS Grid로 서버 렌더링하며 HTMX가 30초마다 부분 갱신한다.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy async, Jinja2, HTMX, pytest, Black, Flake8

## Global Constraints

- 모든 코드 주석, Docstring, 화면 문구, 로그와 예외 메시지는 한국어로 작성한다.
- I/O 함수는 `async`/`await`와 명확한 타입 힌트를 사용한다.
- 새 JavaScript 차트 라이브러리나 프런트엔드 의존성을 추가하지 않는다.
- 기간은 오늘 포함 최근 53주이며, 주는 일요일부터 토요일까지다.
- 타입 순서는 설정 고정 목록 뒤에 DB에서만 발견된 타입을 코드 오름차순으로 붙인다.
- 셀 상태는 `complete`, `incomplete`, `missing`, `future` 네 값만 사용한다.
- 완료는 초록 `#2ea043`, 미완성은 빨강 `#d1242f`, 미입수는 라이트 `#ebedf0`/다크 `#30363d`, 미래는 투명으로 표시한다.
- 셀 클릭 시 슬라이스가 있으면 상세로, 없으면 해당 타입·날짜가 채워진 수집 폼으로 이동한다.
- 현재 작업 트리의 `app/db/session.py`, `app/main.py`, `tests/test_ensure_schema.py` 변경은 별도 DB 보정 작업이다. 히트맵 커밋에 섞지 않는다.

---

## File Map

- `packages/web-api/app/repositories/slice_repository.py`: 기간 내 모든 타입의 슬라이스를 제한 없이 조회한다.
- `packages/web-api/app/schemas/catalog.py`: 히트맵 셀·행·월 라벨·응답 스키마를 정의한다.
- `packages/web-api/app/config.py`: 항상 표시할 보고서 타입 문자열을 설정하고 정규화한다.
- `packages/web-api/.env.example`: `HEATMAP_REPORT_TYPES` 예시를 문서화한다.
- `packages/web-api/app/services/slice_query_service.py`: 최근 53주 날짜 격자와 상태를 계산한다.
- `packages/web-api/app/api/deps.py`: 설정된 보고서 타입을 조회 서비스에 주입한다.
- `packages/web-api/app/api/admin/ui.py`: 대시보드 데이터와 HTMX partial 라우트를 제공하고 미입수 셀 링크의 폼 프리필을 받는다.
- `packages/web-api/app/templates/admin/partials/heatmap.html`: 타입별 월·요일·셀 격자와 범례를 렌더링한다.
- `packages/web-api/app/templates/admin/index.html`: 히트맵 섹션과 30초 HTMX 갱신을 배치한다.
- `packages/web-api/app/templates/admin/base.html`: 히트맵 CSS와 다크 모드 색을 정의한다.
- `packages/web-api/tests/test_slice_repository.py`: 기간 조회의 경계·무제한 반환을 검증한다.
- `packages/web-api/tests/test_slice_query_service.py`: 날짜 계산, 타입 순서, 네 상태 매핑을 검증한다.
- `packages/web-api/tests/test_admin_ui.py`: 전체 페이지·partial·링크·인증을 검증한다.
- `packages/web-api/README.md`: 연간 완전성 히트맵과 설정을 설명한다.

---

### Task 1: 기간 내 슬라이스 조회

**Files:**
- Modify: `packages/web-api/app/repositories/slice_repository.py`
- Test: `packages/web-api/tests/test_slice_repository.py`

**Interfaces:**
- Consumes: `SliceProgress.slice_date: str`, `SliceProgress.report_type: str`
- Produces: `SliceRepository.list_slices_between(start_date: str, end_date: str) -> list[SliceProgress]`

- [ ] **Step 1: 기간 경계와 100건 제한 제거를 검증하는 실패 테스트 작성**

`tests/test_slice_repository.py`에 다음 테스트를 추가한다.

```python
async def test_list_slices_between_returns_all_types_without_limit(
    sessionmaker_fixture,
) -> None:
    async with sessionmaker_fixture() as session:
        repository = SliceRepository(session)
        for index in range(105):
            day = f"2026{(index // 28) + 1:02d}{(index % 28) + 1:02d}"
            await repository.get_or_create_slice(
                "A001" if index % 2 == 0 else "F001",
                day,
            )
        await repository.get_or_create_slice("X001", "20250101")
        await session.commit()

        rows = await repository.list_slices_between("20260101", "20261231")

    assert len(rows) == 105
    assert {row.report_type for row in rows} == {"A001", "F001"}
    assert rows[0].slice_date <= rows[-1].slice_date
```

- [ ] **Step 2: 테스트가 메서드 부재로 실패하는지 확인**

Run:

```powershell
cd packages/web-api
.venv\Scripts\python.exe -m pytest tests/test_slice_repository.py::test_list_slices_between_returns_all_types_without_limit -q
```

Expected: `AttributeError: 'SliceRepository' object has no attribute 'list_slices_between'`

- [ ] **Step 3: 제한 없는 기간 조회 구현**

`SliceRepository.list_slices` 아래에 추가한다.

```python
async def list_slices_between(
    self,
    start_date: str,
    end_date: str,
) -> list[SliceProgress]:
    """기간 내 모든 보고서 타입의 슬라이스를 날짜·유형 순으로 반환한다."""
    statement = (
        select(SliceProgress)
        .where(SliceProgress.slice_date >= start_date)
        .where(SliceProgress.slice_date <= end_date)
        .order_by(SliceProgress.slice_date, SliceProgress.report_type)
    )
    return list((await self._session.execute(statement)).scalars().all())
```

- [ ] **Step 4: 저장소 테스트 실행**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_slice_repository.py -q
```

Expected: 모든 `test_slice_repository.py` 테스트 PASS

- [ ] **Step 5: Task 1 커밋**

```powershell
git add packages/web-api/app/repositories/slice_repository.py packages/web-api/tests/test_slice_repository.py
git commit -m "feat(web-api): query complete slice range for heatmap"
```

---

### Task 2: 히트맵 스키마·설정·서비스 계산

**Files:**
- Modify: `packages/web-api/app/schemas/catalog.py`
- Modify: `packages/web-api/app/config.py`
- Modify: `packages/web-api/.env.example`
- Modify: `packages/web-api/app/services/slice_query_service.py`
- Modify: `packages/web-api/app/api/deps.py`
- Create: `packages/web-api/tests/test_slice_query_service.py`

**Interfaces:**
- Consumes: `SliceRepository.list_slices_between(start_date, end_date)`
- Produces:
  - `HeatmapCell(slice_date, level, slice_id, status, succeeded, listed_count)`
  - `HeatmapMonthLabel(week_index, label)`
  - `HeatmapRow(report_type, weeks)`
  - `HeatmapResponse(start_date, end_date, month_labels, rows)`
  - `SliceQueryService.heatmap(today: date | None = None) -> HeatmapResponse`

- [ ] **Step 1: 히트맵 서비스 실패 테스트 작성**

`tests/test_slice_query_service.py`를 생성한다.

```python
"""연간 완전성 히트맵 계산 테스트."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.services.slice_query_service import SliceQueryService


class FakeSliceRepository:
    """기간 조회 결과를 고정으로 반환한다."""

    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.range: tuple[str, str] | None = None

    async def list_slices_between(self, start_date: str, end_date: str) -> list[object]:
        self.range = (start_date, end_date)
        return self.rows


def _slice(
    report_type: str,
    slice_date: str,
    status: str,
    *,
    succeeded: int,
    listed_count: int | None,
) -> object:
    return SimpleNamespace(
        slice_id=f"{report_type}-{slice_date}",
        report_type=report_type,
        slice_date=slice_date,
        status=status,
        succeeded=succeeded,
        listed_count=listed_count,
    )


async def test_heatmap_builds_53_weeks_and_orders_report_types() -> None:
    repository = FakeSliceRepository(
        [
            _slice("A001", "20260721", "complete", succeeded=3, listed_count=3),
            _slice("X001", "20260720", "blocked", succeeded=1, listed_count=2),
        ]
    )
    service = SliceQueryService(repository, ("A001", "F001"))

    result = await service.heatmap(today=date(2026, 7, 22))

    assert repository.range == ("20250720", "20260722")
    assert [row.report_type for row in result.rows] == ["A001", "F001", "X001"]
    assert all(len(row.weeks) == 53 for row in result.rows)
    assert all(len(week) == 7 for row in result.rows for week in row.weeks)

    cells = {
        (row.report_type, cell.slice_date): cell
        for row in result.rows
        for week in row.weeks
        for cell in week
    }
    assert cells[("A001", "20260721")].level == "complete"
    assert cells[("X001", "20260720")].level == "incomplete"
    assert cells[("F001", "20260721")].level == "missing"
    assert cells[("A001", "20260723")].level == "future"


async def test_heatmap_month_labels_use_first_week_of_month() -> None:
    service = SliceQueryService(FakeSliceRepository([]), ("A001",))

    result = await service.heatmap(today=date(2026, 7, 25))

    labels = {item.week_index: item.label for item in result.month_labels}
    assert "Aug" in labels.values()
    assert "Jan" in labels.values()
    assert "Jul" in labels.values()
```

- [ ] **Step 2: 테스트가 스키마와 시그니처 부재로 실패하는지 확인**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_slice_query_service.py -q
```

Expected: `TypeError` 또는 `AttributeError`로 FAIL

- [ ] **Step 3: Pydantic 응답 스키마 추가**

`app/schemas/catalog.py`의 import에 `from typing import Any, Literal`을 사용하고,
`SliceDetailResponse` 앞에 추가한다.

```python
class HeatmapCell(BaseModel):
    """보고서 타입·날짜 한 칸의 완전성."""

    slice_date: str
    level: Literal["complete", "incomplete", "missing", "future"]
    slice_id: str | None = None
    status: str | None = None
    succeeded: int = 0
    listed_count: int | None = None


class HeatmapMonthLabel(BaseModel):
    """월 이름을 표시할 주 인덱스."""

    week_index: int
    label: str


class HeatmapRow(BaseModel):
    """보고서 타입 하나의 53주 격자."""

    report_type: str
    weeks: list[list[HeatmapCell]]


class HeatmapResponse(BaseModel):
    """연간 완전성 히트맵 응답."""

    start_date: str
    end_date: str
    month_labels: list[HeatmapMonthLabel] = Field(default_factory=list)
    rows: list[HeatmapRow] = Field(default_factory=list)
```

- [ ] **Step 4: 보고서 타입 설정과 정규화 속성 추가**

`Settings`에 문자열 설정을 추가한다. Pydantic Settings의 `list[str]` 환경변수는 JSON만 허용해
운영자가 쓰기 불편하므로, 환경변수는 쉼표 문자열로 받고 속성에서 정규화한다.

```python
heatmap_report_types: str = "A001,F001"

@property
def heatmap_report_type_list(self) -> tuple[str, ...]:
    """히트맵 고정 보고서 타입을 중복 없이 정규화한다."""
    return tuple(
        dict.fromkeys(
            item.strip().upper()
            for item in self.heatmap_report_types.split(",")
            if item.strip()
        )
    )
```

`.env.example`에 추가한다.

```dotenv
# 히트맵에 항상 표시할 보고서 타입(쉼표 구분)
HEATMAP_REPORT_TYPES=A001,F001
```

- [ ] **Step 5: 날짜 격자와 상태 매핑 구현**

`SliceQueryService` 생성자와 `heatmap`을 다음 계약으로 구현한다.

```python
from datetime import date, timedelta

from app.schemas.catalog import (
    HeatmapCell,
    HeatmapMonthLabel,
    HeatmapResponse,
    HeatmapRow,
    # 기존 import 유지
)

WEEK_COUNT = 53
DAY_COUNT = 7
MONTH_LABELS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class SliceQueryService:
    def __init__(
        self,
        slices: SliceRepository,
        report_types: tuple[str, ...] = (),
    ) -> None:
        self._slices = slices
        self._report_types = report_types

    async def heatmap(self, today: date | None = None) -> HeatmapResponse:
        """오늘 기준 최근 53주 완전성 격자를 만든다."""
        end = today or date.today()
        anchor = end - timedelta(weeks=WEEK_COUNT - 1)
        days_since_sunday = (anchor.weekday() + 1) % DAY_COUNT
        start = anchor - timedelta(days=days_since_sunday)

        rows = await self._slices.list_slices_between(
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
        )
        by_key = {(row.report_type, row.slice_date): row for row in rows}
        discovered = sorted({row.report_type for row in rows} - set(self._report_types))
        report_types = [*self._report_types, *discovered]

        heatmap_rows = [
            HeatmapRow(
                report_type=report_type,
                weeks=[
                    [
                        self._cell(
                            report_type,
                            start + timedelta(days=week * DAY_COUNT + weekday),
                            end,
                            by_key,
                        )
                        for weekday in range(DAY_COUNT)
                    ]
                    for week in range(WEEK_COUNT)
                ],
            )
            for report_type in report_types
        ]
        return HeatmapResponse(
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            month_labels=self._month_labels(start),
            rows=heatmap_rows,
        )
```

같은 클래스에 보조 메서드를 추가한다.

```python
@staticmethod
def _cell(
    report_type: str,
    cell_date: date,
    today: date,
    by_key: dict[tuple[str, str], object],
) -> HeatmapCell:
    """한 날짜의 표시 단계와 링크 데이터를 만든다."""
    key = cell_date.strftime("%Y%m%d")
    row = by_key.get((report_type, key))
    if cell_date > today:
        return HeatmapCell(slice_date=key, level="future")
    if row is None:
        return HeatmapCell(slice_date=key, level="missing")
    return HeatmapCell(
        slice_date=key,
        level="complete" if row.status == "complete" else "incomplete",
        slice_id=row.slice_id,
        status=row.status,
        succeeded=row.succeeded,
        listed_count=row.listed_count,
    )

@staticmethod
def _month_labels(start: date) -> list[HeatmapMonthLabel]:
    """월이 처음 바뀌는 주에 GitHub식 영문 월 라벨을 둔다."""
    labels: list[HeatmapMonthLabel] = []
    previous_month: int | None = None
    for week_index in range(WEEK_COUNT):
        week_start = start + timedelta(weeks=week_index)
        month = week_start.month
        if month != previous_month:
            labels.append(
                HeatmapMonthLabel(
                    week_index=week_index,
                    label=MONTH_LABELS[month - 1],
                )
            )
            previous_month = month
    return labels
```

- [ ] **Step 6: 설정을 조회 서비스에 주입**

`app/api/deps.py`의 함수를 수정한다.

```python
def get_slice_query_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
) -> SliceQueryService:
    """슬라이스 완전성 조회 서비스를 제공한다."""
    return SliceQueryService(
        SliceRepository(session),
        settings.heatmap_report_type_list,
    )
```

- [ ] **Step 7: 서비스·설정 테스트 실행**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_slice_query_service.py tests/test_slice_repository.py -q
```

Expected: 모두 PASS

- [ ] **Step 8: Task 2 커밋**

```powershell
git add packages/web-api/app/schemas/catalog.py packages/web-api/app/config.py packages/web-api/.env.example packages/web-api/app/services/slice_query_service.py packages/web-api/app/api/deps.py packages/web-api/tests/test_slice_query_service.py
git commit -m "feat(web-api): build annual completeness heatmap model"
```

---

### Task 3: Jinja/HTMX 히트맵 UI와 셀 링크

**Files:**
- Modify: `packages/web-api/app/api/admin/ui.py`
- Create: `packages/web-api/app/templates/admin/partials/heatmap.html`
- Modify: `packages/web-api/app/templates/admin/index.html`
- Modify: `packages/web-api/app/templates/admin/base.html`
- Modify: `packages/web-api/tests/test_admin_ui.py`

**Interfaces:**
- Consumes: `SliceQueryService.heatmap() -> HeatmapResponse`
- Produces:
  - `GET /admin/heatmap` HTML partial
  - `GET /admin?report_type=A001&start_date=YYYYMMDD&end_date=YYYYMMDD` 수집 폼 프리필

- [ ] **Step 1: Fake 서비스와 UI 실패 테스트 확장**

`tests/test_admin_ui.py`의 import와 Fake에 추가한다.

```python
from app.schemas.catalog import (
    HeatmapCell,
    HeatmapMonthLabel,
    HeatmapResponse,
    HeatmapRow,
    # 기존 import 유지
)

HEATMAP = HeatmapResponse(
    start_date="20250720",
    end_date="20260725",
    month_labels=[HeatmapMonthLabel(week_index=0, label="Jul")],
    rows=[
        HeatmapRow(
            report_type="F001",
            weeks=[
                [
                    HeatmapCell(
                        slice_date="20260724",
                        level="complete",
                        slice_id="s1",
                        status="complete",
                        succeeded=3,
                        listed_count=3,
                    ),
                    HeatmapCell(slice_date="20260725", level="missing"),
                    *[
                        HeatmapCell(slice_date=f"future-{index}", level="future")
                        for index in range(5)
                    ],
                ],
                *[
                    [HeatmapCell(slice_date=f"future-{week}-{day}", level="future")
                     for day in range(7)]
                    for week in range(52)
                ],
            ],
        )
    ],
)

class FakeSliceQueryService:
    async def heatmap(self) -> HeatmapResponse:
        return HEATMAP
```

다음 테스트를 추가한다.

```python
async def test_admin_index_renders_heatmap_links_and_legend(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin")

    assert response.status_code == 200
    assert "연간 수집 완전성" in response.text
    assert "F001" in response.text
    assert 'href="/admin/slices/s1"' in response.text
    assert (
        'href="/admin?report_type=F001&amp;start_date=20260725'
        '&amp;end_date=20260725"' in response.text
    )
    assert "미입수" in response.text
    assert "미완성" in response.text
    assert "완료" in response.text


async def test_heatmap_partial_requires_cookie_token(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/admin/heatmap")

    assert response.status_code == 307
    assert response.headers["location"].endswith("/admin/token")


async def test_admin_query_prefills_collect_form(client_factory) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get(
            "/admin",
            params={
                "report_type": "A001",
                "start_date": "20260102",
                "end_date": "20260102",
            },
        )

    assert 'name="report_type" value="A001"' in response.text
    assert 'name="start_date" value="20260102"' in response.text
    assert 'name="end_date" value="20260102"' in response.text
```

- [ ] **Step 2: UI 테스트가 히트맵 부재로 실패하는지 확인**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_admin_ui.py -q
```

Expected: 히트맵 텍스트·partial 라우트·프리필 검증 FAIL

- [ ] **Step 3: 대시보드와 partial 라우트 구현**

`dashboard`에 `start_date: str | None = None`, `end_date: str | None = None` 쿼리를 추가하고,
기본값은 쿼리가 없을 때만 `_default_range()`를 사용한다.

```python
default_start, default_end = _default_range()
form_start = start_date or default_start
form_end = end_date or default_end
heatmap = await slices.heatmap()
```

템플릿 컨텍스트에는 다음 값을 넘긴다.

```python
{
    "report_type": report_type,
    "start_date": form_start,
    "end_date": form_end,
    "slices": listing.items,
    "heatmap": heatmap,
}
```

새 라우트를 `slices_partial` 앞에 추가한다.

```python
@router.get("/heatmap", response_class=HTMLResponse, summary="연간 완전성 히트맵 갱신")
async def heatmap_partial(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    slices: SliceQueryService = Depends(get_slice_query_service),
) -> HTMLResponse:
    """HTMX 요청에 보고서 타입별 최근 53주 히트맵을 반환한다."""
    if not _has_valid_token(request, settings):
        return _to_token_page()
    heatmap = await slices.heatmap()
    return templates.TemplateResponse(
        request,
        "admin/partials/heatmap.html",
        {"heatmap": heatmap},
    )
```

- [ ] **Step 4: 히트맵 partial 템플릿 생성**

`templates/admin/partials/heatmap.html`을 생성한다.

```html
<div class="heatmap-months" aria-hidden="true">
  {% for label in heatmap.month_labels %}
  <span style="grid-column: {{ label.week_index + 2 }}">{{ label.label }}</span>
  {% endfor %}
</div>

{% for row in heatmap.rows %}
<section class="heatmap-row" aria-label="{{ row.report_type }} 연간 수집 완전성">
  <strong class="heatmap-type">{{ row.report_type }}</strong>
  <div class="heatmap-days" aria-hidden="true">
    <span>월</span><span>수</span><span>금</span>
  </div>
  <div class="heatmap-grid">
    {% for week in row.weeks %}
      {% for cell in week %}
        {% if cell.level == "future" %}
        <span class="heatmap-cell heatmap-future"></span>
        {% elif cell.slice_id %}
        <a class="heatmap-cell heatmap-{{ cell.level }}"
           href="/admin/slices/{{ cell.slice_id }}"
           title="{{ cell.slice_date }} · {{ cell.status }} · 성공 {{ cell.succeeded }}/{{ cell.listed_count if cell.listed_count is not none else '?' }}"></a>
        {% else %}
        <a class="heatmap-cell heatmap-missing"
           href="/admin?report_type={{ row.report_type }}&amp;start_date={{ cell.slice_date }}&amp;end_date={{ cell.slice_date }}"
           title="{{ cell.slice_date }} · 미입수"></a>
        {% endif %}
      {% endfor %}
    {% endfor %}
  </div>
</section>
{% endfor %}

<div class="heatmap-legend">
  <span><i class="heatmap-cell heatmap-missing"></i> 미입수</span>
  <span><i class="heatmap-cell heatmap-incomplete"></i> 미완성</span>
  <span><i class="heatmap-cell heatmap-complete"></i> 완료</span>
</div>
```

- [ ] **Step 5: 대시보드에 히트맵 섹션 배치**

`index.html`에서 수집 폼 뒤, 날짜 슬라이스 표 앞에 추가한다.

```html
<h2>연간 수집 완전성</h2>
<p class="muted">
  보고서 타입별 최근 53주 상태입니다. 회색 칸은 미입수, 빨간 칸은 미완성,
  초록 칸은 완전 수집입니다. 칸을 선택하면 상세 또는 해당 날짜 수집으로 이동합니다.
</p>
<div class="heatmap-scroll"
     hx-get="/admin/heatmap"
     hx-trigger="every 30s"
     hx-swap="innerHTML">
  {% include "admin/partials/heatmap.html" %}
</div>
```

- [ ] **Step 6: GitHub 스타일 CSS 추가**

`base.html`의 `<style>` 끝에 추가한다.

```css
.heatmap-scroll { overflow-x: auto; padding-bottom: 8px; }
.heatmap-months {
  display: grid;
  grid-template-columns: 44px repeat(53, 11px);
  column-gap: 2px;
  min-width: 760px;
  height: 20px;
  font-size: 0.72rem;
  color: #656d76;
}
.heatmap-row {
  display: grid;
  grid-template-columns: 38px 18px auto;
  align-items: start;
  min-width: 760px;
  margin-bottom: 14px;
}
.heatmap-type { font-size: 0.75rem; padding-top: 2px; }
.heatmap-days {
  display: grid;
  grid-template-rows: repeat(7, 11px);
  row-gap: 2px;
  font-size: 0.62rem;
  color: #656d76;
}
.heatmap-days span:nth-child(1) { grid-row: 2; }
.heatmap-days span:nth-child(2) { grid-row: 4; }
.heatmap-days span:nth-child(3) { grid-row: 6; }
.heatmap-grid {
  display: grid;
  grid-template-rows: repeat(7, 11px);
  grid-auto-flow: column;
  grid-auto-columns: 11px;
  gap: 2px;
}
.heatmap-cell {
  display: inline-block;
  width: 11px;
  height: 11px;
  border-radius: 2px;
  box-sizing: border-box;
}
.heatmap-cell:hover { outline: 1px solid #1f2328; outline-offset: 1px; }
.heatmap-complete { background: #2ea043; }
.heatmap-incomplete { background: #d1242f; }
.heatmap-missing { background: #ebedf0; }
.heatmap-future { background: transparent; }
.heatmap-legend {
  display: flex;
  justify-content: flex-end;
  gap: 14px;
  min-width: 760px;
  font-size: 0.75rem;
  color: #656d76;
}
.heatmap-legend span { display: inline-flex; align-items: center; gap: 5px; }
.heatmap-legend .heatmap-cell:hover { outline: none; }
@media (prefers-color-scheme: dark) {
  .heatmap-missing { background: #30363d; }
  .heatmap-cell:hover { outline-color: #f0f6fc; }
}
```

- [ ] **Step 7: UI 테스트 실행**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_admin_ui.py -q
```

Expected: 모든 UI 테스트 PASS

- [ ] **Step 8: Task 3 커밋**

```powershell
git add packages/web-api/app/api/admin/ui.py packages/web-api/app/templates/admin/base.html packages/web-api/app/templates/admin/index.html packages/web-api/app/templates/admin/partials/heatmap.html packages/web-api/tests/test_admin_ui.py
git commit -m "feat(web-api): render GitHub-style completeness heatmap"
```

---

### Task 4: 문서와 전체 검증

**Files:**
- Modify: `packages/web-api/README.md`

**Interfaces:**
- Consumes: `HEATMAP_REPORT_TYPES`, `/admin/heatmap`
- Produces: 운영자가 히트맵 색과 설정을 이해할 수 있는 문서

- [ ] **Step 1: 운영 문서에 히트맵 설명 추가**

`packages/web-api/README.md`의 Admin 화면 단락에 추가한다.

```markdown
### 연간 완전성 히트맵

대시보드는 GitHub contribution 그래프처럼 최근 53주 수집 상태를 보고서 타입별로 보여줍니다.

- 초록: 목록 건수와 성공 건수가 일치하고 실패가 없는 `complete`
- 빨강: 슬라이스는 있으나 아직 미완성
- 회색: 슬라이스가 없어 아직 입수하지 않은 날짜

회색 칸을 선택하면 해당 타입·날짜가 수집 폼에 채워지고, 색이 있는 칸을 선택하면
슬라이스 상세로 이동합니다. 항상 표시할 타입은 `.env`의
`HEATMAP_REPORT_TYPES=A001,F001`로 지정합니다.
```

- [ ] **Step 2: 전체 테스트 실행**

Run:

```powershell
cd packages/web-api
.venv\Scripts\python.exe -m pytest -q
```

Expected: 0 failures

- [ ] **Step 3: 포맷·린트 실행**

Run:

```powershell
.venv\Scripts\python.exe -m black --check app tests
.venv\Scripts\python.exe -m flake8 --max-line-length 100 app tests
```

Expected: Black 변경 대상 없음, Flake8 출력 없음

- [ ] **Step 4: 실제 앱 스모크 확인**

서버가 실행 중이면 재시작한 뒤 다음을 확인한다.

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8123
```

브라우저에서 `http://127.0.0.1:8123/admin`을 열고 확인한다.

1. 타입마다 53주 격자가 세로로 표시된다.
2. 월 라벨과 월·수·금 요일 라벨이 맞는다.
3. 미입수 칸을 누르면 수집 폼 타입·시작일·종료일이 해당 값으로 채워진다.
4. 완료/미완성 칸을 누르면 슬라이스 상세로 이동한다.
5. 창 폭이 좁으면 히트맵 영역만 가로 스크롤된다.

- [ ] **Step 5: Task 4 커밋**

```powershell
git add packages/web-api/README.md
git commit -m "docs: explain annual completeness heatmap"
```

---

## Final Verification

- [ ] `git status --short`에서 히트맵 관련 변경이 남지 않았는지 확인한다.
- [ ] 현재 별도 DB 스키마 보정 변경이 남아 있다면 히트맵 커밋과 분리되어 있는지 확인한다.
- [ ] `git log --oneline -5`에서 저장소·서비스·UI·문서 커밋이 독립적으로 보이는지 확인한다.
