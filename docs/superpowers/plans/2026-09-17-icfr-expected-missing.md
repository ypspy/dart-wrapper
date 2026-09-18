# 내부회계 skipped → 제도상없음 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 내부회계 `skipped`를 외감법 대략 규칙으로 제도상없음으로 옮겨, 운영 화면과 `patch`가 진짜 실패만 보게 한다.

**Architecture:** `field_bundles`의 순수 함수가 정본이다. `classify_outcome`이 이를 쓰고, `CompletenessService` SQL은 같은 조건을 CASE로 복제한다. `icfr_status` 원값·추출기·facts 스키마는 그대로다.

**Tech Stack:** FastAPI, SQLAlchemy 2, SQLite, pytest.

## Global Constraints

- 패키지: `packages/web-api`만.
- 주석·Docstring·로그·사용자 메시지는 한국어.
- 테스트: `packages/web-api`에서 `.\.venv\Scripts\python.exe -m pytest <파일> -q --tb=short`. Windows에서 pytest가 통과 후 hang하면 해당 파일 테스트가 모두 통과한 뒤 hang으로 본다.
- KSIC/OpenDART 워킹 트리 변경은 커밋에 넣지 않음.
- `EXTRACTOR_VERSION` 올리지 않음. `listing_spells`·`PUBLIC`·자산 구간 없음.
- `icfr_status` 쓰기·selector·leaf GET 변경 없음.

## File map

| 파일 | 책임 |
|------|------|
| `app/extracting/field_bundles.py` | 상장·연도 헬퍼, `classify_outcome`/`add_fact_outcomes` |
| `app/services/completeness_service.py` | icfr SQL + `corps` LEFT JOIN |
| `app/services/extraction_service.py` | 잡 카운터에 `corp_cls`·`period_year` 전달 |
| `app/models/corp.py` | JOIN만. 스키마 변경 없음 |
| `tests/test_field_bundles.py` | 분류 단위 테스트 |
| `tests/test_extract_admin_api.py` | 완전성·patch·SQL=Python |
| `tests/test_extract_admin_ui.py` | 화면 한 줄 |
| `app/templates/admin/partials/extract_completeness.html` | 내부회계 주석 |
| `README.md` | 제도상없음 한 줄 |

---

### Task 1: `classify_outcome` 내부회계 제도상없음

**Files:**
- Modify: `packages/web-api/app/extracting/field_bundles.py`
- Test: `packages/web-api/tests/test_field_bundles.py`

**Interfaces:**
- Consumes: `parse_year_end`, `parse_rcept_dt` (`app/extracting/dates.py`)
- Produces:
  - `ICFR_LISTED_CORP_CLS: frozenset[str]` = `{"Y", "K", "N"}`
  - `ICFR_CONSOLIDATED_MANDATE_YEAR: int` = `2023`
  - `is_listed_for_icfr(corp_cls: str | None) -> bool`
  - `icfr_period_year(year_end: str | None, rcept_dt: str | None) -> int | None`
  - `is_icfr_expected_missing(*, status: str | None, report_type: str | None, corp_cls: str | None, period_year: int | None) -> bool`
  - `classify_outcome(..., report_type: str | None = None, corp_cls: str | None = None, period_year: int | None = None)`
  - `add_fact_outcomes(counts, fact, *, report_type: str | None = None, corp_cls: str | None = None, period_year: int | None = None) -> None` — `report_type` 기본값은 `fact.source_report_type`

- [ ] **Step 1: Write the failing tests**

`packages/web-api/tests/test_field_bundles.py` 맨 아래(기존 `test_ok_status_is_ok` 근처)에 추가한다. import에 `icfr_period_year`, `is_icfr_expected_missing`, `is_listed_for_icfr`를 넣는다.

```python
def test_f001_skipped_unlisted_is_expected_missing() -> None:
    for corp_cls in ("E", None, ""):
        assert (
            classify_outcome(
                "icfr",
                fs_scope="separate",
                status="skipped",
                report_type="F001",
                corp_cls=corp_cls,
            )
            == "expected_missing"
        )


def test_f001_skipped_listed_is_fail() -> None:
    for corp_cls in ("Y", "K", "N"):
        assert (
            classify_outcome(
                "icfr",
                fs_scope="separate",
                status="skipped",
                report_type="F001",
                corp_cls=corp_cls,
            )
            == "fail"
        )


def test_f002_skipped_before_2023_is_expected_missing() -> None:
    assert (
        classify_outcome(
            "icfr",
            fs_scope="consolidated",
            status="skipped",
            report_type="F002",
            period_year=2022,
        )
        == "expected_missing"
    )


def test_f002_skipped_from_2023_is_fail() -> None:
    assert (
        classify_outcome(
            "icfr",
            fs_scope="consolidated",
            status="skipped",
            report_type="F002",
            period_year=2023,
        )
        == "fail"
    )


def test_f002_skipped_unknown_year_is_fail() -> None:
    assert (
        classify_outcome(
            "icfr",
            fs_scope="consolidated",
            status="skipped",
            report_type="F002",
            period_year=None,
        )
        == "fail"
    )


def test_a001_skipped_is_fail_regardless_of_listing() -> None:
    assert (
        classify_outcome(
            "icfr",
            fs_scope="separate",
            status="skipped",
            report_type="A001",
            corp_cls="E",
            period_year=2016,
        )
        == "fail"
    )


def test_icfr_not_found_is_fail() -> None:
    assert (
        classify_outcome(
            "icfr",
            fs_scope="separate",
            status="not_found",
            report_type="F001",
            corp_cls="E",
        )
        == "fail"
    )


def test_icfr_ok_is_ok() -> None:
    assert classify_outcome("icfr", fs_scope="separate", status="ok") == "ok"


def test_icfr_period_year_prefers_year_end() -> None:
    assert icfr_period_year("(2019.12)", "2020.03.31") == 2019
    assert icfr_period_year(None, "2020.03.31") == 2020
    assert icfr_period_year(None, None) is None


def test_is_listed_for_icfr_includes_konex() -> None:
    assert is_listed_for_icfr("N") is True
    assert is_listed_for_icfr("E") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_field_bundles.py::test_f001_skipped_unlisted_is_expected_missing tests/test_field_bundles.py::test_f001_skipped_listed_is_fail -q --tb=short`

Expected: FAIL (`ImportError` 또는 `icfr` skipped가 아직 `fail`).

- [ ] **Step 3: Write minimal implementation**

`packages/web-api/app/extracting/field_bundles.py`에 아래를 넣고 `classify_outcome`·`add_fact_outcomes`를 고친다.

```python
from app.extracting.dates import parse_rcept_dt, parse_year_end

ICFR_LISTED_CORP_CLS = frozenset({"Y", "K", "N"})
ICFR_CONSOLIDATED_MANDATE_YEAR = 2023


def is_listed_for_icfr(corp_cls: str | None) -> bool:
    """주권상장(코스피·코스닥·코넥스)이면 참."""
    return (corp_cls or "") in ICFR_LISTED_CORP_CLS


def icfr_period_year(year_end: str | None, rcept_dt: str | None) -> int | None:
    """목록 결산월 연도를 쓰고, 없으면 접수일 연도."""
    parsed_end = parse_year_end(year_end)
    if parsed_end is not None:
        return parsed_end.year
    parsed_rcept = parse_rcept_dt(rcept_dt)
    if parsed_rcept is not None:
        return parsed_rcept.year
    return None


def is_icfr_expected_missing(
    *,
    status: str | None,
    report_type: str | None,
    corp_cls: str | None,
    period_year: int | None,
) -> bool:
    """내부회계 leaf 없음이 제도상 구멍인지."""
    if status != "skipped":
        return False
    if report_type == "F001" and not is_listed_for_icfr(corp_cls):
        return True
    if (
        report_type == "F002"
        and period_year is not None
        and period_year < ICFR_CONSOLIDATED_MANDATE_YEAR
    ):
        return True
    return False
```

`classify_outcome` 시그니처에 `report_type`/`corp_cls`/`period_year`를 추가하고, 커뮤니케이션 분기 **다음**·`status == "ok"` **앞에** 둔다.

```python
    if is_icfr_expected_missing(
        status=status if bundle == "icfr" else None,
        report_type=report_type,
        corp_cls=corp_cls,
        period_year=period_year,
    ):
        return "expected_missing"
```

`add_fact_outcomes`:

```python
def add_fact_outcomes(
    counts: dict[str, dict[str, int]],
    fact: AuditReportFact,
    *,
    report_type: str | None = None,
    corp_cls: str | None = None,
    period_year: int | None = None,
) -> None:
    """fetch_status=ok 행만 12묶음에 더한다."""
    if fact.fetch_status != "ok":
        return
    resolved_type = report_type or fact.source_report_type
    for bundle in BUNDLE_KEYS:
        outcome = classify_outcome(
            bundle,
            fs_scope=fact.fs_scope,
            status=getattr(fact, status_attr(bundle)),
            hours_status=fact.hours_status,
            activities_status=fact.activities_status,
            report_type=resolved_type,
            corp_cls=corp_cls,
            period_year=period_year,
        )
        counts[bundle][outcome] += 1
```

기존 `test_add_fact_outcomes_counts_ok_fetch`는 `icfr_status`가 기본 `None`이라 실패 칸으로 간다. 그 테스트에 `icfr_status="ok"`를 넣거나, 이번 추가 테스트만 통과하면 된다. `None`은 실패가 맞다. 기존 테스트가 `icfr`를 assert하지 않으면 깨지지 않는다.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_field_bundles.py -q --tb=short`

Expected: PASS (기존 + 신규).

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/extracting/field_bundles.py packages/web-api/tests/test_field_bundles.py
git commit -m "feat: 내부회계 skipped를 상장·연도로 제도상없음으로 분류한다"
```

KSIC/OpenDART 파일은 `git add`하지 않는다.

---

### Task 2: 완전성 SQL과 화면 집계

**Files:**
- Modify: `packages/web-api/app/services/completeness_service.py`
- Modify: `packages/web-api/tests/test_extract_admin_api.py`
- Test: `packages/web-api/tests/test_extract_admin_api.py`

**Interfaces:**
- Consumes: Task 1의 `ICFR_LISTED_CORP_CLS`, `ICFR_CONSOLIDATED_MANDATE_YEAR`, `is_listed_for_icfr`, `icfr_period_year`, `add_fact_outcomes` 키워드 인자
- Produces: `_bundle_predicates("icfr")`의 `is_expected`가 Python과 같음. `field_partial`/`patch`/`field-bundle fail` 목록이 그 조건을 씀.

- [ ] **Step 1: Write the failing tests**

`packages/web-api/tests/test_extract_admin_api.py`에 `Corp` import를 추가한다.

```python
from app.models.corp import Corp
```

`_seed` 뒤에 헬퍼를 둔다.

```python
async def _seed_corp(
    sessionmaker,
    corp_code: str = "00126380",
    corp_cls: str | None = "Y",
) -> None:
    """완전성 조인에 쓸 corps 한 행."""
    async with sessionmaker() as session:
        session.add(Corp(corp_code=corp_code, fetch_status="ok", corp_cls=corp_cls))
        await session.commit()
```

기존 `test_completeness_field_partial_includes_icfr_skipped`를 **상장 스냅샷을 심도록** 바꾼다. docstring도 맞춘다.

```python
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
    assert body["field_partial"] == 1
    assert body["all_success"] == 0
```

신규 테스트:

```python
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


async def test_list_patch_skips_unlisted_f001_icfr_only(
    memory_app: tuple[FastAPI, object],
) -> None:
    """비상장 F001 내부회계 skipped만 있으면 patch 키가 비고, 코넥스는 들어간다."""
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
        keys = await CompletenessService(session).list_patch_document_keys(
            start_date="20200301",
            end_date="20200331",
            report_types=["F001"],
        )
    assert keys == [("20200331000002", "22222")]
```

`test_field_bundle_sql_counts_match_python_rules`의 픽스처에 내부회계 행을 더하고, Python 쪽도 disclosure·corp를 넘긴다. 기존 5행은 `icfr_status="ok"`라 칸이 안 바뀐다. 루프를 이렇게 바꾼다.

```python
    facts = [
        # ... 기존 5행 유지 ...
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
```

00007은 `year_end=(2022.12)` → 제도상없음, 00008은 `(2023.12)` → 실패.

기존 `entries = [_entry(... report_type=fact.source_report_type) for fact in facts]`를 명시 리스트로 바꾼다.

```python
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
```

파일 상단 import에 `icfr_period_year`를 추가한다.

이 시점에서 비상장 skipped 테스트는 SQL이 아직 `fail`이라 FAIL이어야 한다.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_api.py::test_completeness_unlisted_f001_icfr_skipped_is_not_field_partial tests/test_extract_admin_api.py::test_list_patch_skips_unlisted_f001_icfr_only -q --tb=short`

Expected: FAIL (`field_partial == 1` 또는 patch 키가 두 개).

- [ ] **Step 3: Write minimal implementation**

`completeness_service.py` import:

```python
from sqlalchemy import Integer, and_, case, cast, exists, func, literal, or_, select

from app.extracting.field_bundles import (
    BUNDLE_KEYS,
    BUNDLE_LABELS,
    DART_DISCLOSURE_VIEW,
    EXPORT_PAGE_SIZE,
    FIELD_BUNDLE_REPORT_TYPES,
    ICFR_CONSOLIDATED_MANDATE_YEAR,
    ICFR_LISTED_CORP_CLS,
    empty_field_bundle_counts,
    status_attr,
)
from app.models.corp import Corp
```

헬퍼 (모듈 수준, `_bundle_predicates` 위):

```python
def _join_facts_window(statement: object) -> object:
    """facts–disclosures 필수, corps는 내부회계 판정용 LEFT JOIN."""
    return statement.join(
        Disclosure, AuditReportFact.rcept_no == Disclosure.rcept_no
    ).outerjoin(Corp, Corp.corp_code == Disclosure.corp_code)


def _icfr_period_year_sql() -> object:
    """icfr_period_year와 같이 결산월 연, 없으면 접수일 연. 이상값은 NULL."""
    year_from_end = cast(
        func.substr(
            Disclosure.year_end,
            func.instr(func.coalesce(Disclosure.year_end, ""), ".") - 4,
            4,
        ),
        Integer,
    )
    compact_rcept = func.replace(
        func.replace(func.coalesce(Disclosure.rcept_dt, ""), ".", ""),
        "-",
        "",
    )
    year_from_rcept = cast(func.substr(compact_rcept, 1, 4), Integer)
    year_end_usable = and_(
        Disclosure.year_end.is_not(None),
        Disclosure.year_end != "",
        func.instr(Disclosure.year_end, ".") > 4,
    )
    raw = case((year_end_usable, year_from_end), else_=year_from_rcept)
    return case((and_(raw >= 1900, raw <= 2100), raw), else_=None)
```

`_bundle_predicates`의 `else: is_expected = literal(False)`를 icfr 분기로 바꾼다.

```python
    if bundle == "communications":
        is_expected = and_(
            col == "not_found",
            AuditReportFact.hours_status == "ok",
            AuditReportFact.activities_status == "ok",
        )
    elif bundle == "icfr":
        period_year = _icfr_period_year_sql()
        unlisted = or_(
            Corp.corp_cls.is_(None),
            Corp.corp_cls == "",
            ~Corp.corp_cls.in_(tuple(ICFR_LISTED_CORP_CLS)),
        )
        is_expected = and_(
            col == "skipped",
            or_(
                and_(
                    AuditReportFact.source_report_type == "F001",
                    unlisted,
                ),
                and_(
                    AuditReportFact.source_report_type == "F002",
                    period_year.is_not(None),
                    period_year < ICFR_CONSOLIDATED_MANDATE_YEAR,
                ),
            ),
        )
    else:
        is_expected = literal(False)
```

`completeness_service.py`에서 `.join(Disclosure, AuditReportFact.rcept_no == Disclosure.rcept_no)` **6곳**을 `_join_facts_window(select(...))`로 바꾼다. `select_from`이 있는 쿼리는:

```python
        statement = _join_facts_window(
            select(*columns).select_from(AuditReportFact)
        ).where(eligible_where)
```

`unextracted` 목록의 `Disclosure.outerjoin(AuditReportFact)`는 그대로 둔다. 거기는 묶음 실패 SQL이 없다.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_api.py tests/test_field_bundles.py -q --tb=short`

Expected: PASS. 비상장 F001 skipped → `all_success=1`. 코넥스 N → patch 키 1개. SQL 네 칸 = Python.

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/services/completeness_service.py packages/web-api/tests/test_extract_admin_api.py
git commit -m "feat: 내부회계 제도상없음을 완전성 SQL에 맞춘다"
```

---

### Task 3: 잡 카운터에 상장·연도 전달

**Files:**
- Modify: `packages/web-api/app/services/extraction_service.py` (`_record_document_progress`, 약 473–496행)
- Test: `packages/web-api/tests/test_extraction_service.py`

**Interfaces:**
- Consumes: `add_fact_outcomes(..., corp_cls=, period_year=)`, `icfr_period_year`
- Produces: `params.field_bundles["icfr"]["expected_missing"]`가 비상장 F001 skipped에서 1

- [ ] **Step 1: Write the failing test**

`test_run_job_adds_field_bundle_counts_for_ok_fact`는 mock HTML에 내부회계 leaf가 없어 `icfr_status=skipped`다. `_f001_leaves()`의 `corp_code`가 있고 `corps`가 없으면 미매핑 → 제도상없음이어야 한다. 아래 assert를 그 테스트에 추가한다.

```python
    assert bundles["icfr"]["expected_missing"] == 1
    assert bundles["icfr"]["fail"] == 0
```

`test_run_job_adds_field_bundle_counts_for_ok_fact`의 새 assert는 Task 1만으로도 통과한다(미매핑 = 제도상없음). 상장 스냅샷 테스트가 이 Task의 빨간 테스트다. `_f001_leaves()`의 `corp_code`는 `00126380`이다.

```python
from app.models.corp import Corp


async def test_run_job_counts_listed_icfr_skipped_as_fail(
    sessionmaker_fixture,
) -> None:
    """주권상장 F001에 내부회계 leaf가 없으면 잡 카운터 icfr은 실패다."""
    await _seed_entries(sessionmaker_fixture, _f001_leaves())
    async with sessionmaker_fixture() as session:
        session.add(Corp(corp_code="00126380", fetch_status="ok", corp_cls="Y"))
        await session.commit()
    service, client = _service(sessionmaker_fixture)
    async with client:
        job_id = await service.start("20200301", "20200331", ["F001"], "extract")
        await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        job = await session.get(ExtractionJob, job_id)
    bundles = job.params["field_bundles"]
    assert bundles["icfr"]["fail"] == 1
    assert bundles["icfr"]["expected_missing"] == 0
```

`_f001_leaves()`의 `corp_code`는 `00126380`이다. `_seed_entries`가 `disclosures`도 넣는다.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py::test_run_job_counts_listed_icfr_skipped_as_fail -q --tb=short`

Expected: FAIL (`expected_missing == 1`, `fail == 0`) — 잡이 아직 `corp_cls`를 안 넘기므로 미매핑으로 본다.

- [ ] **Step 3: Write minimal implementation**

`extraction_service.py` import:

```python
from app.extracting.field_bundles import (
    add_fact_outcomes,
    empty_field_bundle_counts,
    icfr_period_year,
)
from app.models.corp import Corp
from app.models.disclosure import Disclosure
```

`_record_document_progress`의 `add_fact_outcomes(bundle_counts, fact)`를 교체한다. 같은 세션에서 disclosure·corp를 읽는다. disclosure가 없으면 `corp_cls`와 연도는 None이다.

```python
            if fetch_status == "ok":
                fact = await FactRepository(session).get(rcept_no, dcm_no)
                if fact is not None:
                    disclosure = await session.get(Disclosure, rcept_no)
                    corp_code = disclosure.corp_code if disclosure is not None else None
                    corp = await session.get(Corp, corp_code) if corp_code else None
                    add_fact_outcomes(
                        bundle_counts,
                        fact,
                        corp_cls=corp.corp_cls if corp is not None else None,
                        period_year=icfr_period_year(
                            disclosure.year_end if disclosure is not None else None,
                            disclosure.rcept_dt if disclosure is not None else None,
                        ),
                    )
```

`test_run_job_adds_field_bundle_counts_for_ok_fact`에 `assert bundles["icfr"]["expected_missing"] == 1`을 넣는다(corps 없음 = 미매핑).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py::test_run_job_adds_field_bundle_counts_for_ok_fact tests/test_extraction_service.py::test_run_job_counts_listed_icfr_skipped_as_fail tests/test_extract_admin_api.py tests/test_field_bundles.py -q --tb=short`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/services/extraction_service.py packages/web-api/tests/test_extraction_service.py
git commit -m "feat: 추출 잡 내부회계 칸에 상장 스냅샷을 반영한다"
```

---

### Task 4: README와 화면 주석

**Files:**
- Modify: `packages/web-api/README.md` (필드 묶음 모니터, 약 215–217행)
- Modify: `packages/web-api/app/templates/admin/partials/extract_completeness.html` (12줄 표 아래 muted)
- Test: `packages/web-api/tests/test_extract_admin_ui.py`

**Interfaces:**
- Consumes: 없음 (문구만)
- Produces: 운영자가 내부회계 제도상없음 규칙을 화면·README에서 봄

- [ ] **Step 1: Write the failing test**

`packages/web-api/tests/test_extract_admin_ui.py`의 `test_completeness_cards_include_twelve_bundle_rows`에 assert를 추가한다.

```python
    assert "비상장 개별" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_ui.py::test_completeness_cards_include_twelve_bundle_rows -q --tb=short`

Expected: FAIL (`비상장 개별` 없음).

- [ ] **Step 3: Write the copy**

`extract_completeness.html` 표 아래 `<p class="muted">모집단 ...` 옆에 문장을 추가한다.

```html
<p>
  <span class="muted">모집단 {{ field_bundles.eligible }} · {{ field_bundles.extractor_version }}</span>
</p>
<p class="muted">내부회계: 비상장 개별·연결 의무 전 skipped는 제도상없음. 코넥스는 상장이다.</p>
```

`README.md` 필드 묶음 불릿에 한 줄:

```markdown
- 실시내용 1–3절 ok이고 4절만 `not_found`이면 커뮤니케이션은 제도상없음
- 내부회계 `skipped`는 비상장 개별(F001)과 연결 의무 전(F002, 사업연도 ≤ 2022)만 제도상없음. 코넥스(`corp_cls=N`)는 주권상장이다. `not_found`와 A001 `skipped`는 실패
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_ui.py tests/test_extract_admin_api.py tests/test_field_bundles.py tests/test_extraction_service.py::test_run_job_adds_field_bundle_counts_for_ok_fact tests/test_extraction_service.py::test_run_job_counts_listed_icfr_skipped_as_fail -q --tb=short`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/README.md packages/web-api/app/templates/admin/partials/extract_completeness.html packages/web-api/tests/test_extract_admin_ui.py
git commit -m "docs: 내부회계 제도상없음 규칙을 화면과 README에 적는다"
```
