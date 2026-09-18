# 추출 12묶음 모니터 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/admin/extract`에서 문서 fetch 카드와 별도로, 현재 추출기 facts의 필드 묶음 12개 성공·해당없음·제도상없음·실패를 연구 창과 실행 중 잡에서 보고, 실패 목록을 TSV로 받는다.

**Architecture:** 분류 규칙은 `app/extracting/field_bundles.py` 한곳. 창 집계는 `CompletenessService`가 `disclosures` 기간 조인 + facts `SUM(CASE)` 한 쿼리. 잡 카운터는 `run_job`이 `fetch_status=ok`로 쓴 행만 `params.field_bundles`에 같은 규칙으로 가산. HTML은 기존 `completeness-cards` partial에 12줄 표를 붙인다.

**Tech Stack:** FastAPI, SQLAlchemy 2 asyncio, Pydantic v2, Jinja2, HTMX, pytest. 주석·Docstring·로그·사용자 메시지는 한국어.

## Global Constraints

- 패키지: `packages/web-api`만. 새 npm 패키지 없음. 새 facts 컬럼·추출기 버전 올리기 없음.
- 창 모집단: `fetch_status=ok` 그리고 `extractor_version == EXTRACTOR_VERSION`. 유형 합산은 F001+F002+A001.
- 성공 = 묶음 `*_status == "ok"`. 해당없음 = 종속기업이고 `fs_scope != "consolidated"` 이며 상태가 `not_applicable`. 제도상없음 = 커뮤니케이션이 `not_found`이고 `hours_status==ok`이며 `activities_status==ok`. 그 외 실패.
- 실패 반출: 화면 목록 + TSV + viewer URL. HTML 본문 저장 없음. export 한 응답 최대 5,000행, 이어서 `X-Next-Cursor`.
- 기간은 YYYYMMDD, `to_dotted_rcept_dt`로 `disclosures.rcept_dt` 조인.
- 테스트는 `packages/web-api`에서 `.\.venv\Scripts\python.exe -m pytest …` (작업 디렉터리 `packages/web-api`).
- TDD: 실패하는 테스트 → 구현 → 통과 → 커밋. Live DART 호출 테스트 없음.

## File map

| 파일 | 책임 |
|------|------|
| `packages/web-api/app/extracting/field_bundles.py` | 12키·라벨·`classify_outcome`·빈 카운터·facts 가산 |
| `packages/web-api/app/schemas/extract.py` | field-bundles JSON 모델 |
| `packages/web-api/app/services/completeness_service.py` | 창 SQL 집계·실패 목록·TSV 행·viewer_url |
| `packages/web-api/app/api/admin/extract.py` | JSON GET 3개 |
| `packages/web-api/app/api/admin/ui.py` | cards 컨텍스트·field-bundle-items HTML |
| `packages/web-api/app/templates/admin/partials/extract_completeness.html` | 12줄 표 |
| `packages/web-api/app/templates/admin/partials/extract_field_bundle_items.html` | 실패 목록 |
| `packages/web-api/app/templates/admin/partials/extract_job.html` | 이번 잡 12묶음 |
| `packages/web-api/app/services/extraction_service.py` | `params.field_bundles` 초기화·가산 |
| `packages/web-api/README.md` | Admin 추출 한 절 |
| `packages/web-api/tests/test_field_bundles.py` | 분류 단위 테스트 |
| `packages/web-api/tests/test_extract_admin_api.py` | JSON 집계·목록·export |
| `packages/web-api/tests/test_extract_admin_ui.py` | 12줄·실패 링크·잡 카드 |
| `packages/web-api/tests/test_extraction_service.py` | 잡 가산 1건 |

---

### Task 1: 분류 규칙 모듈

**Files:**
- Create: `packages/web-api/app/extracting/field_bundles.py`
- Test: `packages/web-api/tests/test_field_bundles.py`

**Interfaces:**
- Produces: `BUNDLE_KEYS`, `BUNDLE_LABELS`, `status_attr(bundle)`, `classify_outcome`, `empty_field_bundle_counts`, `add_fact_outcomes`, `FieldBundleOutcome`

- [ ] **Step 1: Write the failing tests**

`packages/web-api/tests/test_field_bundles.py`:

```python
"""필드 묶음 12개 성공·해당없음·제도상없음·실패 분류."""

from app.extracting.field_bundles import (
    BUNDLE_KEYS,
    add_fact_outcomes,
    classify_outcome,
    empty_field_bundle_counts,
)
from app.models.audit_report_fact import AuditReportFact
from app.extracting.constants import EXTRACTOR_VERSION


def test_twelve_bundle_keys_in_spec_order() -> None:
    assert BUNDLE_KEYS == (
        "auditor",
        "opinion",
        "gaap",
        "audit_report_date",
        "current_period",
        "hours",
        "activities",
        "communications",
        "accounts",
        "icfr",
        "going_concern",
        "subsidiary",
    )


def test_separate_subsidiary_not_applicable_is_not_ok() -> None:
    assert (
        classify_outcome(
            "subsidiary",
            fs_scope="separate",
            status="not_applicable",
        )
        == "not_applicable"
    )


def test_unknown_scope_subsidiary_not_applicable() -> None:
    assert (
        classify_outcome(
            "subsidiary",
            fs_scope="unknown",
            status="not_applicable",
        )
        == "not_applicable"
    )


def test_communications_expected_missing_when_hours_and_activities_ok() -> None:
    assert (
        classify_outcome(
            "communications",
            fs_scope="separate",
            status="not_found",
            hours_status="ok",
            activities_status="ok",
        )
        == "expected_missing"
    )


def test_communications_not_found_is_fail_if_hours_skipped() -> None:
    assert (
        classify_outcome(
            "communications",
            fs_scope="separate",
            status="not_found",
            hours_status="skipped",
            activities_status="ok",
        )
        == "fail"
    )


def test_consolidated_subsidiary_not_found_is_fail() -> None:
    assert (
        classify_outcome(
            "subsidiary",
            fs_scope="consolidated",
            status="not_found",
        )
        == "fail"
    )


def test_ok_status_is_ok() -> None:
    assert classify_outcome("opinion", fs_scope="separate", status="ok") == "ok"


def test_add_fact_outcomes_skips_non_ok_fetch() -> None:
    counts = empty_field_bundle_counts()
    fact = AuditReportFact(
        rcept_no="1",
        dcm_no="1",
        source_report_type="F001",
        fs_scope="separate",
        fetch_status="fetch_failed",
        extractor_version=EXTRACTOR_VERSION,
        subsidiary_status="not_applicable",
        opinion_status="skipped",
    )
    add_fact_outcomes(counts, fact)
    assert counts["opinion"]["fail"] == 0
    assert counts["subsidiary"]["not_applicable"] == 0


def test_add_fact_outcomes_counts_ok_fetch() -> None:
    counts = empty_field_bundle_counts()
    fact = AuditReportFact(
        rcept_no="1",
        dcm_no="1",
        source_report_type="F001",
        fs_scope="separate",
        fetch_status="ok",
        extractor_version=EXTRACTOR_VERSION,
        opinion_status="ok",
        subsidiary_status="not_applicable",
        hours_status="ok",
        activities_status="ok",
        communications_status="not_found",
    )
    add_fact_outcomes(counts, fact)
    assert counts["opinion"]["ok"] == 1
    assert counts["subsidiary"]["not_applicable"] == 1
    assert counts["communications"]["expected_missing"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run (cwd `packages/web-api`):

```text
.\.venv\Scripts\python.exe -m pytest tests/test_field_bundles.py -q
```

Expected: FAIL (`ModuleNotFoundError: app.extracting.field_bundles`)

- [ ] **Step 3: Write minimal implementation**

`packages/web-api/app/extracting/field_bundles.py`:

```python
"""감사 facts 필드 묶음 12개의 성공·실패 분류."""

from __future__ import annotations

from typing import Literal

from app.models.audit_report_fact import AuditReportFact

FieldBundleOutcome = Literal["ok", "not_applicable", "expected_missing", "fail"]

_BUNDLE_ROWS: tuple[tuple[str, str, str], ...] = (
    ("auditor", "auditor_status", "감사인"),
    ("opinion", "opinion_status", "감사의견"),
    ("gaap", "gaap_status", "GAAP"),
    ("audit_report_date", "audit_report_date_status", "감사보고서일"),
    ("current_period", "current_period_status", "당기"),
    ("hours", "hours_status", "감사시간"),
    ("activities", "activities_status", "실시항목"),
    ("communications", "communications_status", "커뮤니케이션"),
    ("accounts", "accounts_status", "계정"),
    ("icfr", "icfr_status", "내부회계"),
    ("going_concern", "going_concern_status", "계속기업"),
    ("subsidiary", "subsidiary_status", "종속기업"),
)

BUNDLE_KEYS: tuple[str, ...] = tuple(row[0] for row in _BUNDLE_ROWS)
BUNDLE_LABELS: dict[str, str] = {row[0]: row[2] for row in _BUNDLE_ROWS}
FIELD_BUNDLE_REPORT_TYPES: tuple[str, ...] = ("F001", "F002", "A001")
EXPORT_PAGE_SIZE = 5000
DART_DISCLOSURE_VIEW = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def status_attr(bundle: str) -> str:
    """bundle 키에 대응하는 facts 컬럼 이름."""
    for key, attr, _label in _BUNDLE_ROWS:
        if key == bundle:
            return attr
    raise KeyError(bundle)


def classify_outcome(
    bundle: str,
    *,
    fs_scope: str,
    status: str | None,
    hours_status: str | None = None,
    activities_status: str | None = None,
) -> FieldBundleOutcome:
    """한 문서·한 묶음의 네 칸 중 하나를 고른다."""
    if (
        bundle == "subsidiary"
        and fs_scope != "consolidated"
        and status == "not_applicable"
    ):
        return "not_applicable"
    if (
        bundle == "communications"
        and status == "not_found"
        and hours_status == "ok"
        and activities_status == "ok"
    ):
        return "expected_missing"
    if status == "ok":
        return "ok"
    return "fail"


def empty_field_bundle_counts() -> dict[str, dict[str, int]]:
    """잡 params·집계 초기값."""
    return {
        key: {
            "ok": 0,
            "not_applicable": 0,
            "expected_missing": 0,
            "fail": 0,
        }
        for key in BUNDLE_KEYS
    }


def add_fact_outcomes(
    counts: dict[str, dict[str, int]],
    fact: AuditReportFact,
) -> None:
    """fetch_status=ok 행만 12묶음에 더한다."""
    if fact.fetch_status != "ok":
        return
    for bundle in BUNDLE_KEYS:
        outcome = classify_outcome(
            bundle,
            fs_scope=fact.fs_scope,
            status=getattr(fact, status_attr(bundle)),
            hours_status=fact.hours_status,
            activities_status=fact.activities_status,
        )
        counts[bundle][outcome] += 1
```

- [ ] **Step 4: Run tests to verify they pass**

```text
.\.venv\Scripts\python.exe -m pytest tests/test_field_bundles.py -q
```

Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/extracting/field_bundles.py packages/web-api/tests/test_field_bundles.py
git commit -m "feat: 추출 필드 묶음 12개의 성공·실패 분류를 둔다"
```

---

### Task 2: 창 집계·실패 목록 서비스

**Files:**
- Modify: `packages/web-api/app/schemas/extract.py`
- Modify: `packages/web-api/app/services/completeness_service.py`
- Test: `packages/web-api/tests/test_extract_admin_api.py` (서비스는 API Task 3에서 같이 돌려도 됨 — 이 태스크는 서비스 메서드를 직접 호출하는 테스트를 같은 파일 하단에 추가)

**Interfaces:**
- Consumes: `classify_outcome`, `BUNDLE_KEYS`, `BUNDLE_LABELS`, `FIELD_BUNDLE_REPORT_TYPES`, `status_attr`, `empty_field_bundle_counts`, `EXPORT_PAGE_SIZE`, `DART_DISCLOSURE_VIEW`, 기존 `_window` / `_fact_window` 조인, `encode_cursor` / `decode_cursor`
- Produces: `CompletenessService.summarize_field_bundles`, `list_field_bundle_fail_items`, `FieldBundleCountsResponse`, `FieldBundleRow`, `FieldBundleFailItem`, `FieldBundleFailListResponse`

- [ ] **Step 1: Write failing service tests**

`test_extract_admin_api.py` 하단 (기존 `_seed` / `_ok_fact` / `_entry` / `memory_app` 재사용):

```python
from app.extracting.constants import EXTRACTOR_VERSION
from app.extracting.field_bundles import BUNDLE_KEYS
from app.services.completeness_service import CompletenessService


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
```

- [ ] **Step 2: Run the new test to verify it fails**

```text
.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_api.py::test_field_bundles_exclude_stale_and_fetch_failed_and_classify -q
```

Expected: FAIL (`AttributeError: summarize_field_bundles`)

- [ ] **Step 3: Add schemas**

`schemas/extract.py`에 추가:

```python
from app.extracting.field_bundles import BUNDLE_KEYS

class FieldBundleRow(BaseModel):
    """창 표 한 줄."""

    bundle: str
    label: str
    ok: int
    not_applicable: int
    expected_missing: int
    fail: int


class FieldBundleCountsResponse(BaseModel):
    """기간 안 현재 추출기 facts의 12묶음 집계."""

    start_date: str
    end_date: str
    extractor_version: str
    eligible: int
    bundles: list[FieldBundleRow]


class FieldBundleFailItem(BaseModel):
    """실패 목록·TSV 한 행."""

    report_type: str
    rcept_no: str
    dcm_no: str
    fs_scope: str
    bundle: str
    status: str | None
    extractor_version: str | None
    viewer_url: str | None


class FieldBundleFailListResponse(BaseModel):
    """실패 목록 한 페이지."""

    items: list[FieldBundleFailItem]
    next_cursor: str | None = None
```

- [ ] **Step 4: Implement service methods**

`completeness_service.py` import:

```python
from app.extracting.field_bundles import (
    BUNDLE_KEYS,
    BUNDLE_LABELS,
    DART_DISCLOSURE_VIEW,
    EXPORT_PAGE_SIZE,
    FIELD_BUNDLE_REPORT_TYPES,
    classify_outcome,
    empty_field_bundle_counts,
    status_attr,
)
from app.schemas.extract import (
    CompletenessItem,
    CompletenessResponse,
    DateOverrideResponse,
    FieldBundleCountsResponse,
    FieldBundleFailItem,
    FieldBundleFailListResponse,
    FieldBundleRow,
)
from app.models.entry import Entry
```

`CompletenessService`에 추가. `_eligible_fact_window(start_dt, end_dt)`는

```python
and_(
    AuditReportFact.fetch_status == "ok",
    AuditReportFact.extractor_version == EXTRACTOR_VERSION,
    AuditReportFact.source_report_type.in_(list(FIELD_BUNDLE_REPORT_TYPES)),
    Disclosure.rcept_dt >= start_dt,
    Disclosure.rcept_dt <= end_dt,
)
```

`summarize_field_bundles`:

1. `start_dt, end_dt = self._window(start_date, end_date)`
2. `eligible = count()` 위 조건
3. `counts = empty_field_bundle_counts()`
4. 한 쿼리: `select`에 각 bundle마다 네 `SUM(CASE)` — 조건은 `classify_outcome`과 같게:
   - subsidiary NA: `fs_scope != 'consolidated' AND subsidiary_status == 'not_applicable'`
   - communications expected: `communications_status == 'not_found' AND hours_status == 'ok' AND activities_status == 'ok'`
   - ok: 위가 아니고 `col == 'ok'`
   - fail: 그 외 (eligible 행이므로 `eligible - ok - na - expected`로 계산해도 됨)
5. `FieldBundleRow(bundle=key, label=BUNDLE_LABELS[key], ...)` 12개
6. 반환 `FieldBundleCountsResponse(start_date=start_date, end_date=end_date, extractor_version=EXTRACTOR_VERSION, eligible=eligible, bundles=rows)`

SQLAlchemy CASE 예 (한 묶음):

```python
from sqlalchemy import case, literal

col = getattr(AuditReportFact, status_attr(bundle))
if bundle == "subsidiary":
    is_na = and_(
        AuditReportFact.fs_scope != "consolidated",
        col == "not_applicable",
    )
else:
    is_na = literal(False)
if bundle == "communications":
    is_expected = and_(
        col == "not_found",
        AuditReportFact.hours_status == "ok",
        AuditReportFact.activities_status == "ok",
    )
else:
    is_expected = literal(False)
is_ok = and_(~is_na, ~is_expected, col == "ok")
```

`_sum_if`는 이미 completeness_service에 있다. 48개 SUM을 한 `select(...).join(Disclosure).where(eligible)`에 넣고 row에서 채운다.

`list_field_bundle_fail_items(..., bundle, cursor, limit)`:

1. `bundle not in BUNDLE_KEYS` → `BadRequest("bundle은 12개 필드 키 중 하나여야 합니다.")`
2. eligible 조인 + Python과 같은 fail 조건 (SQL: `~is_na & ~is_expected & col != 'ok'` — `col`이 NULL이면 실패이므로 `or_(col.is_(None), col != "ok")` 를 is_ok의 반대로)
3. `order_by(rcept_no, dcm_no)`, keyset `decode_cursor`
4. `limit+1` 행
5. 각 행 `viewer_url`: 같은 세션에서 `select(Entry.viewer_url).where(Entry.rcept_no==, Entry.dcm_no==, Entry.viewer_url.is_not(None)).limit(1)`. 없으면 `DART_DISCLOSURE_VIEW.format(rcept_no=...)`
6. `status`는 해당 컬럼 값. `report_type`은 `source_report_type`

Fail SQL 조건 헬퍼 `_fail_predicate(bundle)`를 `summarize`의 fail 합과 목록이 공유한다.

- [ ] **Step 5: Run the service test**

```text
.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_api.py::test_field_bundles_exclude_stale_and_fetch_failed_and_classify -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/web-api/app/schemas/extract.py packages/web-api/app/services/completeness_service.py packages/web-api/tests/test_extract_admin_api.py
git commit -m "feat: 연구 창 필드 묶음 12줄을 disclosures 조인으로 센다"
```

---

### Task 3: JSON API (집계·실패 목록·TSV)

**Files:**
- Modify: `packages/web-api/app/api/admin/extract.py`
- Test: `packages/web-api/tests/test_extract_admin_api.py`

**Interfaces:**
- Consumes: `summarize_field_bundles`, `list_field_bundle_fail_items`, `EXPORT_PAGE_SIZE`
- Produces: `GET /admin/extract/audit-opinion/field-bundles`, `.../field-bundles/items`, `.../field-bundles/export`

- [ ] **Step 1: Write failing API tests**

같은 시드 패턴으로:

```python
async def test_field_bundles_api_requires_token(client_factory) -> None:
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
```

`outcome=ok`도 400인지 한 줄 추가:

```python
async def test_field_bundle_items_reject_non_fail_outcome(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
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
```

- [ ] **Step 2: Run tests to verify they fail**

```text
.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_api.py::test_field_bundles_api_requires_token tests/test_extract_admin_api.py::test_field_bundle_items_reject_unknown_bundle tests/test_extract_admin_api.py::test_field_bundle_export_tsv_and_fail_list tests/test_extract_admin_api.py::test_field_bundle_items_reject_non_fail_outcome -q
```

Expected: FAIL (404)

- [ ] **Step 3: Add routes**

`extract.py` — `Response` import, 스키마 import. completeness GET 아래에:

```python
from fastapi import Response

@router.get(
    "/audit-opinion/field-bundles",
    response_model=FieldBundleCountsResponse,
    summary="추출 필드 묶음 12줄 집계",
)
async def read_field_bundles(
    start_date: str = Query(pattern=r"^\d{8}$"),
    end_date: str = Query(pattern=r"^\d{8}$"),
    service: CompletenessService = Depends(get_completeness_service),
) -> FieldBundleCountsResponse:
    """현재 추출기 ok facts의 12묶음 건수를 반환한다."""
    return await service.summarize_field_bundles(
        start_date=start_date,
        end_date=end_date,
    )


@router.get(
    "/audit-opinion/field-bundles/items",
    response_model=FieldBundleFailListResponse,
    summary="필드 묶음 실패 문서 목록",
)
async def read_field_bundle_items(
    start_date: str = Query(pattern=r"^\d{8}$"),
    end_date: str = Query(pattern=r"^\d{8}$"),
    bundle: str = Query(),
    outcome: str = Query(),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=50),
    service: CompletenessService = Depends(get_completeness_service),
) -> FieldBundleFailListResponse:
    """outcome=fail만 허용한다."""
    if outcome != "fail":
        raise BadRequest("outcome은 fail만 지원합니다. 실패 목록을 요청해 주세요.")
    return await service.list_field_bundle_fail_items(
        start_date=start_date,
        end_date=end_date,
        bundle=bundle,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/audit-opinion/field-bundles/export",
    summary="필드 묶음 실패 TSV",
)
async def export_field_bundle_items(
    start_date: str = Query(pattern=r"^\d{8}$"),
    end_date: str = Query(pattern=r"^\d{8}$"),
    bundle: str = Query(),
    outcome: str = Query(),
    cursor: str | None = Query(default=None),
    service: CompletenessService = Depends(get_completeness_service),
) -> Response:
    """실패 행을 탭 구분 텍스트로 내려 준다. 최대 5000행."""
    if outcome != "fail":
        raise BadRequest("outcome은 fail만 지원합니다. 실패 목록을 요청해 주세요.")
    page = await service.list_field_bundle_fail_items(
        start_date=start_date,
        end_date=end_date,
        bundle=bundle,
        cursor=cursor,
        limit=EXPORT_PAGE_SIZE,
    )
    headers_row = [
        "report_type",
        "rcept_no",
        "dcm_no",
        "fs_scope",
        "bundle",
        "status",
        "extractor_version",
        "viewer_url",
    ]
    lines = ["\t".join(headers_row)]
    for item in page.items:
        lines.append(
            "\t".join(
                [
                    item.report_type,
                    item.rcept_no,
                    item.dcm_no,
                    item.fs_scope,
                    item.bundle,
                    item.status or "",
                    item.extractor_version or "",
                    item.viewer_url or "",
                ]
            )
        )
    headers = {"Content-Type": "text/tab-separated-values; charset=utf-8"}
    if page.next_cursor:
        headers["X-Next-Cursor"] = page.next_cursor
    return Response(content="\n".join(lines) + "\n", headers=headers)
```

`list_field_bundle_fail_items`의 `limit`는 items에서 최대 50, export에서 5000을 그대로 넘긴다. 서비스는 `le=5000`까지 받는다 (API items는 Query le=50).

- [ ] **Step 4: Run API tests plus Task 2 test**

```text
.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_api.py -q
```

Expected: 기존 completeness 테스트 + 신규 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/api/admin/extract.py packages/web-api/tests/test_extract_admin_api.py
git commit -m "feat: 필드 묶음 집계·실패 목록·TSV Admin API를 연다"
```

---

### Task 4: Admin HTML 12줄 표와 실패 목록

**Files:**
- Modify: `packages/web-api/app/api/admin/ui.py`
- Modify: `packages/web-api/app/templates/admin/partials/extract_completeness.html`
- Create: `packages/web-api/app/templates/admin/partials/extract_field_bundle_items.html`
- Modify: `packages/web-api/tests/test_extract_admin_ui.py`
- Modify: `packages/web-api/app/templates/admin/base.html` (표가 깨지면 최소 CSS만)

**Interfaces:**
- Consumes: `summarize_field_bundles`, `list_field_bundle_fail_items`
- Produces: cards partial의 `field_bundles`, `GET /admin/extract/field-bundle-items`

- [ ] **Step 1: Write failing UI tests**

`FakeCompletenessService`에:

```python
from app.extracting.field_bundles import BUNDLE_KEYS, BUNDLE_LABELS, empty_field_bundle_counts
from app.schemas.extract import (
    FieldBundleCountsResponse,
    FieldBundleFailItem,
    FieldBundleFailListResponse,
    FieldBundleRow,
)
from app.extracting.constants import EXTRACTOR_VERSION

async def summarize_field_bundles(self, **kwargs) -> FieldBundleCountsResponse:
    self.bundle_calls = getattr(self, "bundle_calls", [])
    self.bundle_calls.append(kwargs)
    rows = []
    for key in BUNDLE_KEYS:
        rows.append(
            FieldBundleRow(
                bundle=key,
                label=BUNDLE_LABELS[key],
                ok=1,
                not_applicable=0 if key != "subsidiary" else 2,
                expected_missing=0 if key != "communications" else 3,
                fail=4,
            )
        )
    return FieldBundleCountsResponse(
        start_date=str(kwargs.get("start_date", "")),
        end_date=str(kwargs.get("end_date", "")),
        extractor_version=EXTRACTOR_VERSION,
        eligible=10,
        bundles=rows,
    )

async def list_field_bundle_fail_items(self, **kwargs) -> FieldBundleFailListResponse:
    return FieldBundleFailListResponse(
        items=[
            FieldBundleFailItem(
                report_type="F001",
                rcept_no="20200331000001",
                dcm_no="11111",
                fs_scope="separate",
                bundle=str(kwargs.get("bundle", "opinion")),
                status="not_found",
                extractor_version=EXTRACTOR_VERSION,
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=1",
            )
        ]
    )
```

테스트:

```python
async def test_completeness_cards_include_twelve_bundle_rows(
    client_factory: ClientFactory,
) -> None:
    """카드 partial에 12묶음 표와 실패 TSV 링크가 있다."""
    completeness = FakeCompletenessService()
    async with client_factory(_app(completeness=completeness)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get(
            "/admin/extract/completeness-cards?start_date=20200101&end_date=20201231"
        )
    assert response.status_code == 200
    assert "감사인" in response.text
    assert "종속기업" in response.text
    assert "제도상없음" in response.text
    assert "field-bundles/export" in response.text
    assert completeness.bundle_calls[0]["start_date"] == "20200101"


async def test_field_bundle_items_partial_lists_fail_row(
    client_factory: ClientFactory,
) -> None:
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get(
            "/admin/extract/field-bundle-items"
            "?start_date=20200101&end_date=20201231&bundle=opinion"
        )
    assert response.status_code == 200
    assert "20200331000001" in response.text
    assert "viewer.do" in response.text
```

기존 `test_completeness_cards_query_uses_requested_dates`는 문서 카드 단언을 유지한다.

- [ ] **Step 2: Run UI tests to verify they fail**

```text
.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_ui.py::test_completeness_cards_include_twelve_bundle_rows tests/test_extract_admin_ui.py::test_field_bundle_items_partial_lists_fail_row -q
```

Expected: FAIL (12라벨 없음 / 404)

- [ ] **Step 3: Wire UI**

`_extract_completeness_page`가 rows와 함께 `field_bundles`를 채운다. 날짜 오류면 `field_bundles=None`.

`extract_completeness_cards` 컨텍스트에 `field_bundles` 추가.

`extract_completeness.html` 카드 `div` 뒤에:

```html
{% if field_bundles %}
<table class="extract-field-bundles" aria-label="필드 묶음 추출 품질">
  <thead>
    <tr>
      <th>묶음</th>
      <th>성공</th>
      <th>해당없음</th>
      <th>제도상없음</th>
      <th>실패</th>
      <th>성공률</th>
    </tr>
  </thead>
  <tbody>
    {% for row in field_bundles.bundles %}
    {% set denom = row.ok + row.fail %}
    <tr>
      <th scope="row">{{ row.label }}</th>
      <td>{{ row.ok }}</td>
      <td>{{ row.not_applicable }}</td>
      <td>{{ row.expected_missing }}</td>
      <td>
        {% if row.fail %}
        <a href="/admin/extract/field-bundle-items?start_date={{ start_date }}&amp;end_date={{ end_date }}&amp;bundle={{ row.bundle }}"
           hx-get="/admin/extract/field-bundle-items?start_date={{ start_date }}&amp;end_date={{ end_date }}&amp;bundle={{ row.bundle }}"
           hx-target="#extract-field-bundle-items"
           hx-swap="innerHTML">{{ row.fail }}</a>
        {% else %}
        0
        {% endif %}
      </td>
      <td>{% if denom %}{{ (row.ok * 100 // denom) }}%{% else %}—{% endif %}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
<p>
  <span class="muted">모집단 {{ field_bundles.eligible }} · {{ field_bundles.extractor_version }}</span>
</p>
<div id="extract-field-bundle-items"></div>
{% endif %}
```

TSV 링크는 표 위 한 줄: 실패가 있는 묶음마다 작은 링크보다, 목록 조각 안에 「TSV 받기」를 둔다.

`extract_field_bundle_items.html`:

```html
{% if notice %}
<p class="banner-warn" role="status">{{ notice }}</p>
{% endif %}
{% if items %}
<p>
  <a class="btn btn-sm" href="{{ export_href }}">이 필터 TSV</a>
</p>
<ul class="extract-items">
  {% for item in items %}
  <li>
    {{ item.report_type }}
    <code>{{ item.rcept_no }}</code> / <code>{{ item.dcm_no }}</code>
    · {{ item.status }}
    {% if item.viewer_url %}
    <a href="{{ item.viewer_url }}" target="_blank" rel="noreferrer">원문</a>
    {% endif %}
  </li>
  {% endfor %}
</ul>
{% if next_href %}
<button type="button" class="btn btn-sm"
        hx-get="{{ next_href }}"
        hx-target="#extract-field-bundle-items"
        hx-swap="innerHTML">더 보기</button>
{% endif %}
{% elif not notice %}
<p class="muted">해당 실패 문서가 없습니다.</p>
{% endif %}
```

`ui.py` `GET /extract/field-bundle-items`: 토큰 검사, 기간 기본 연구 창, `list_field_bundle_fail_items(..., limit=50)`, `export_href`는 JSON export URL (`/admin/extract/audit-opinion/field-bundles/export?...&outcome=fail`).

`base.html`에 `.extract-field-bundles { width:100%; border-collapse:collapse; font-size:13px; }` 정도만. 기존 extract 카드 스타일 근처에.

- [ ] **Step 4: Run extract UI tests**

```text
.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_ui.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/api/admin/ui.py packages/web-api/app/templates/admin/partials/extract_completeness.html packages/web-api/app/templates/admin/partials/extract_field_bundle_items.html packages/web-api/app/templates/admin/base.html packages/web-api/tests/test_extract_admin_ui.py
git commit -m "feat: 추출 화면에 필드 묶음 12줄과 실패 목록을 넣는다"
```

---

### Task 5: 잡 카드 12묶음 가산

**Files:**
- Modify: `packages/web-api/app/services/extraction_service.py`
- Modify: `packages/web-api/app/templates/admin/partials/extract_job.html`
- Test: `packages/web-api/tests/test_extraction_service.py`
- Test: `packages/web-api/tests/test_extract_admin_ui.py`

**Interfaces:**
- Consumes: `empty_field_bundle_counts`, `add_fact_outcomes`
- Produces: `job.params.field_bundles` (12키 × `{ok,not_applicable,expected_missing,fail}`)

- [ ] **Step 1: Write failing tests**

`test_extraction_service.py` — 기존 `test_extract_f001_cover_and_opinion_saves_unqualified_fact` 다음에 단언을 추가하지 말고 **별도 테스트** (기존 테스트가 HTML mock으로 ok fact를 남김):

기존 테스트 이름을 재사용하지 않고:

```python
async def test_run_job_adds_field_bundle_counts_for_ok_fact(
    sessionmaker_fixture,
) -> None:
    """fetch ok로 저장한 문서만 params.field_bundles에 더한다."""
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    service, client = _service(sessionmaker_fixture)
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        job = await session.get(ExtractionJob, job_id)
    assert job is not None
    bundles = job.params["field_bundles"]
    assert bundles["opinion"]["ok"] == 1
    assert bundles["subsidiary"]["not_applicable"] == 1
```

`test_extract_admin_ui.py`의 `RUNNING_EXTRACT` params에 `field_bundles`를 넣고:

```python
async def test_extract_job_card_shows_field_bundle_fail(
    client_factory: ClientFactory,
) -> None:
    from copy import deepcopy
    job = deepcopy(RUNNING_EXTRACT)
    job.params["field_bundles"] = {
        "opinion": {"ok": 3, "not_applicable": 0, "expected_missing": 0, "fail": 1},
    }
    extraction = FakeExtractionService(job)
    async with client_factory(_app(extraction)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/extract/job-status")
    assert "감사의견" in response.text
    assert "실패 1" in response.text or ">1<" in response.text
```

잡 카드가 12키를 돌 때 없는 키는 `empty_field_bundle_counts`로 채운다. 테스트는 opinion만 있어도 라벨이 보이게 템플릿이 `BUNDLE_KEYS`를 순회하며 `job.params.field_bundles`에서 읽게 한다.

- [ ] **Step 2: Run tests to verify they fail**

```text
.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py::test_run_job_adds_field_bundle_counts_for_ok_fact tests/test_extract_admin_ui.py::test_extract_job_card_shows_field_bundle_fail -q
```

Expected: FAIL (`field_bundles` KeyError / 카드에 감사의견 없음)

- [ ] **Step 3: Implement**

`run_job`에서 `target_count`를 넣을 때:

```python
from app.extracting.field_bundles import (
    BUNDLE_LABELS,
    add_fact_outcomes,
    empty_field_bundle_counts,
)

params["field_bundles"] = empty_field_bundle_counts()
```

`_process_document`이 fact를 커밋한 뒤 `fetch_status=="ok"`이면 그 세션에서 counts를 읽어 `add_fact_outcomes` 후 `update_params`. **방문 루프의 `update_params`와 한 번에** 하도록: 루프에서 `current["field_bundles"]`를 유지하는 편이 세션을 덜 연다.

구현:

1. `run_job` 로컬 변수 `bundle_counts = empty_field_bundle_counts()`
2. `fetch_status = await self._process_document(...)` 후, `fetch_status == "ok"`이면 fact를 다시 읽지 말고 `_process_document`이 `(fetch_status, fact | None)`을 반환하게 바꾸면 기존 호출부가 깨진다. **최소 변경:** `_process_document` 반환은 그대로 두고, ok일 때만 `FactRepository.get`으로 방금 행을 읽어 `add_fact_outcomes`.
3. `update_params` 때 `current["field_bundles"] = bundle_counts`

건너뛰기(`None`)와 `fetch_failed`는 가산하지 않는다.

`extract_job.html` — 진행 막대 아래:

```html
{% set bundles = job.params.get("field_bundles") or {} %}
{% if bundles %}
<table class="extract-job-bundles" aria-label="이번 잡 필드 묶음">
  {% for key, label in bundle_labels %}
  {% set row = bundles.get(key) or {} %}
  <tr>
    <th scope="row">{{ label }}</th>
    <td>성공 {{ row.get("ok", 0) }}</td>
    <td>실패 {{ row.get("fail", 0) }}</td>
    <td>해당없음 {{ row.get("not_applicable", 0) }}</td>
    <td>제도상없음 {{ row.get("expected_missing", 0) }}</td>
  </tr>
  {% endfor %}
</table>
{% endif %}
```

`_extract_ops_context`에 `bundle_labels = list(BUNDLE_LABELS.items())`를 넣는다.

- [ ] **Step 4: Run tests**

```text
.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py::test_run_job_adds_field_bundle_counts_for_ok_fact tests/test_extraction_service.py::test_extract_f001_cover_and_opinion_saves_unqualified_fact tests/test_extract_admin_ui.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/services/extraction_service.py packages/web-api/app/api/admin/ui.py packages/web-api/app/templates/admin/partials/extract_job.html packages/web-api/tests/test_extraction_service.py packages/web-api/tests/test_extract_admin_ui.py
git commit -m "feat: 추출 잡이 필드 묶음 성공·실패를 누적해 보여 준다"
```

---

### Task 6: README

**Files:**
- Modify: `packages/web-api/README.md` Admin 추출 절

**Interfaces:**
- Consumes: 위 JSON 경로·분류 규칙

- [ ] **Step 1: Add README subsection under Admin 추출**

기존 completeness 표 아래에:

```markdown
### 필드 묶음 모니터

`/admin/extract` 왼쪽 문서 카드 아래에 현재 추출기 `fetch_status=ok` 행의 12묶음
(감사인·의견·GAAP·감사보고서일·당기·감사시간·실시항목·커뮤니케이션·계정·내부회계·계속기업·종속기업)
성공 / 해당없음 / 제도상없음 / 실패를 보여 줍니다. 성공률은 `성공/(성공+실패)`입니다.

- 별도·unknown 문서의 종속기업 `not_applicable`은 해당없음(분모 제외)
- 실시내용 1–3절 ok이고 4절만 `not_found`이면 커뮤니케이션은 제도상없음
- 구버전·미추출·fetch 실패는 이 표에 넣지 않습니다 (문서 카드)

JSON: `GET /admin/extract/audit-opinion/field-bundles`, 실패 목록
`.../field-bundles/items?bundle=&outcome=fail`, TSV
`.../field-bundles/export` (최대 5000행, `X-Next-Cursor`).
실행 중 잡은 `params.field_bundles`에 이번 처리분만 가산합니다.
```

테스트 없음. 맞춤법만 확인.

- [ ] **Step 2: Commit**

```bash
git add packages/web-api/README.md
git commit -m "docs: 추출 필드 묶음 모니터 API와 화면을 README에 적는다"
```

---

## Self-review

**Spec coverage**

| 스펙 | 태스크 |
|------|--------|
| 12키·라벨·분류 C | 1 |
| 창 모집단 현재 버전 ok, 구버전·fetch_failed 제외 | 2 |
| SQL 집계 12줄 | 2 |
| JSON field-bundles / items fail only / export TSV 5000 + X-Next-Cursor | 3 |
| 문서 카드 유지, 같은 cards partial, 60초 폴링 유지 | 4 |
| 실패 목록 viewer + TSV 링크 | 4 |
| 잡 field_bundles, ok fetch만 가산 | 5 |
| README | 6 |
| 유형 12×3·날짜컷·HTML 스냅샷·버전 업 | 비목표, 계획에 없음 |

**Placeholder scan:** TBD/TODO/`similar to Task N` 없음. 분류 SQL은 Task 2에 CASE 조건을 적음.

**Type consistency:** `FieldBundleOutcome` 네 칸 키가 JSON `ok` / `not_applicable` / `expected_missing` / `fail`로 잡 params와 동일. `bundle` 키는 `BUNDLE_KEYS`. `list_field_bundle_fail_items(start_date, end_date, bundle, cursor, limit)`.
