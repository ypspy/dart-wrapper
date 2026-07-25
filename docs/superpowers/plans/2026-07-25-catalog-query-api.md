# Catalog Query API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Public `/api/v1/catalog`에 공시 목록·단건·leaf 목차(primary/all) API를 추가하고, 수집 시 `disclosures` 집계 테이블을 유지한다.

**Architecture:** 기존 레이어(`api` → `services` → `repositories` → `models`)를 확장한다. 공시 목록은 `disclosures`에서 keyset cursor로 읽고, 목차는 `entries` 전량 조회 후 코드 상수 allowlist로 `primary_entries`를 가른다. 수집(`CatalogService.run_job`)은 entry upsert 직후 disclosure를 upsert한다.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 async, aiosqlite, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-07-25-catalog-query-api-design.md`

## Global Constraints

- Python 3.11+, 모든 함수 입·출력 타입 힌트
- 주석·Docstring·로그·예외/사용자 메시지는 **한국어**
- I/O는 `async`/`await`
- Black / Flake8 (line length 100)
- DB에는 메타만 저장. 원문·정제 텍스트·표 저장 금지
- Repository 경계 유지. SQLite/PostgreSQL 동일 코드
- 작업 디렉터리: `packages/web-api` (명시 제외)
- 테스트는 실제 DART를 호출하지 않는다
- URL/`rcp_no` 응답 필드와 DB/`rcept_no`는 같은 접수번호

## File Structure

| Path | Responsibility |
|------|----------------|
| `app/errors.py` | `BadRequest`(400) 추가 — 손상된 cursor |
| `app/models/disclosure.py` | `Disclosure` ORM |
| `app/models/__init__.py` | `Disclosure` export → `create_all` 반영 |
| `app/catalog/__init__.py` | 패키지 |
| `app/catalog/primary_sections.py` | F001 allowlist + `is_primary_section` |
| `app/schemas/catalog_query.py` | 목록·목차 요청/응답 스키마 |
| `app/repositories/disclosure_repository.py` | keyset list / get / upsert_many / backfill |
| `app/repositories/entry_repository.py` | `list_toc_by_rcept_no` 추가 |
| `app/services/catalog_query_service.py` | cursor·조회 오케스트레이션·primary 분리 |
| `app/services/catalog_service.py` | 수집 후 disclosure upsert |
| `app/api/v1/catalog.py` | Public 라우터 |
| `app/api/deps.py` | `get_catalog_query_service` |
| `app/main.py` | 라우터 등록 |
| `scripts/backfill_disclosures.py` | 로컬 backfill CLI |
| `tests/test_*.py` | 각 단위 테스트 |
| `README.md` | 엔드포인트 문서 |

---

### Task 1: BadRequest(400) 예외

**Files:**
- Modify: `packages/web-api/app/errors.py`
- Test: `packages/web-api/tests/test_errors.py`

**Interfaces:**
- Consumes: 기존 `DartWrapperError`, `register_exception_handlers`
- Produces: `BadRequest(DartWrapperError)` → HTTP 400

- [ ] **Step 1: Write the failing test**

`tests/test_errors.py`에 추가:

```python
async def test_bad_request_returns_400(client_factory) -> None:
    from fastapi import FastAPI

    from app.errors import BadRequest, register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise BadRequest("커서 값이 올바르지 않습니다.")

    async with client_factory(app) as client:
        response = await client.get("/boom")

    assert response.status_code == 400
    assert response.json()["detail"] == "커서 값이 올바르지 않습니다."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_errors.py::test_bad_request_returns_400 -v`  
Expected: FAIL (`BadRequest` import/정의 없음)

- [ ] **Step 3: Implement**

`app/errors.py`에:

```python
class BadRequest(DartWrapperError):
    """잘못된 요청 파라미터(예: 손상된 cursor)일 때 발생한다."""


_STATUS_BY_EXCEPTION: dict[type[DartWrapperError], int] = {
    CatalogNotFound: 404,
    BadRequest: 400,
    SourceFetchError: 502,
    ParseError: 502,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_errors.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/errors.py packages/web-api/tests/test_errors.py
git commit -m "feat(web-api): map BadRequest to HTTP 400"
```

---

### Task 2: Disclosure 모델

**Files:**
- Create: `packages/web-api/app/models/disclosure.py`
- Modify: `packages/web-api/app/models/__init__.py`
- Test: `packages/web-api/tests/test_models.py`

**Interfaces:**
- Consumes: `app.models.base.Base`
- Produces: `Disclosure` — PK `rcept_no`, 스펙 §3.1 컬럼, 인덱스 `(rcept_dt, rcept_no)`, `corp_code`, `report_type`

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`에 추가:

```python
async def test_disclosure_table_roundtrip(sessionmaker_fixture) -> None:
    from app.models.disclosure import Disclosure

    async with sessionmaker_fixture() as session:
        session.add(
            Disclosure(
                rcept_no="20260724000650",
                corp_code="00224628",
                corp_name="테스트",
                report_nm="감사보고서",
                report_type="F001",
                rcept_dt="20260724",
                entry_count=3,
                disclosure_url="https://example.com",
            )
        )
        await session.commit()

    async with sessionmaker_fixture() as session:
        row = await session.get(Disclosure, "20260724000650")

    assert row is not None
    assert row.entry_count == 3
    assert row.corp_name == "테스트"
```

`sessionmaker_fixture`가 없으면 `test_entry_repository.py`와 동일하게 인메모리 엔진 fixture를 두고, `create_all`이 `Disclosure`를 포함해야 한다.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_disclosure_table_roundtrip -v`  
Expected: FAIL

- [ ] **Step 3: Implement model**

`app/models/disclosure.py`:

```python
"""공시(접수) 단위 집계 테이블. 목록 조회용 메타만 저장한다."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Disclosure(Base):
    """접수번호 1건의 공시 메타와 leaf 개수."""

    __tablename__ = "disclosures"
    __table_args__ = (
        Index("ix_disclosures_rcept_dt_rcept_no", "rcept_dt", "rcept_no"),
        Index("ix_disclosures_corp_code", "corp_code"),
        Index("ix_disclosures_report_type", "report_type"),
    )

    rcept_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    corp_code: Mapped[str | None] = mapped_column(String(16))
    corp_name: Mapped[str | None] = mapped_column(String(255))
    report_nm: Mapped[str | None] = mapped_column(String(255))
    report_type: Mapped[str | None] = mapped_column(String(16))
    correction_type: Mapped[str | None] = mapped_column(String(32))
    submitter: Mapped[str | None] = mapped_column(String(255))
    rcept_dt: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    bsns_year: Mapped[str | None] = mapped_column(String(8))
    year_end: Mapped[str | None] = mapped_column(String(32))
    disclosure_url: Mapped[str | None] = mapped_column(String(1024))
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
```

`app/models/__init__.py`에서 `Disclosure`를 import하고 `__all__`에 추가한다.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/models/disclosure.py packages/web-api/app/models/__init__.py packages/web-api/tests/test_models.py
git commit -m "feat(web-api): add disclosures ORM model"
```

---

### Task 3: primary_sections allowlist

**Files:**
- Create: `packages/web-api/app/catalog/__init__.py`
- Create: `packages/web-api/app/catalog/primary_sections.py`
- Test: `packages/web-api/tests/test_primary_sections.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `PRIMARY_SECTION_PATTERNS: dict[str, tuple[str, ...]]`
  - `is_primary_section(report_type: str | None, section_name: str | None, document_name: str | None = None) -> bool`

- [ ] **Step 1: Write the failing test**

```python
from app.catalog.primary_sections import is_primary_section


def test_f001_matches_financial_statements() -> None:
    assert is_primary_section("F001", "재무상태표") is True
    assert is_primary_section("F001", "  주석  ") is True
    assert is_primary_section("F001", "감사인의 감사보고서") is False


def test_unknown_report_type_is_never_primary() -> None:
    assert is_primary_section("A001", "재무상태표") is False
    assert is_primary_section(None, "재무상태표") is False


def test_falls_back_to_document_name() -> None:
    assert is_primary_section("F001", None, "손익계산서") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_primary_sections.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement**

```python
"""report_type별 디폴트(primary) 섹션 이름 allowlist."""

from __future__ import annotations

PRIMARY_SECTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "F001": (
        "재무상태표",
        "손익계산서",
        "포괄손익계산서",
        "자본변동표",
        "현금흐름표",
        "주석",
    ),
}


def is_primary_section(
    report_type: str | None,
    section_name: str | None,
    document_name: str | None = None,
) -> bool:
    """섹션명(없으면 문서명)이 allowlist 패턴을 포함하면 True."""
    if not report_type:
        return False
    patterns = PRIMARY_SECTION_PATTERNS.get(report_type)
    if not patterns:
        return False
    target = (section_name or document_name or "").strip()
    if not target:
        return False
    return any(pattern in target for pattern in patterns)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_primary_sections.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/catalog packages/web-api/tests/test_primary_sections.py
git commit -m "feat(web-api): add F001 primary section allowlist"
```

---

### Task 4: DisclosureRepository

**Files:**
- Create: `packages/web-api/app/repositories/disclosure_repository.py`
- Test: `packages/web-api/tests/test_disclosure_repository.py`

**Interfaces:**
- Consumes: `Disclosure`, `Entry`, `AsyncSession`
- Produces:
  - `DisclosureRepository.upsert_many(rows: Sequence[Disclosure]) -> int`
  - `get(rcept_no: str) -> Disclosure | None`
  - `list_page(*, corp_code, corp_name, report_nm, report_type, start_date, end_date, limit, cursor_rcept_dt, cursor_rcept_no) -> list[Disclosure]`
  - `backfill_from_entries() -> int`

- [ ] **Step 1: Write failing tests**

핵심 케이스:

1. upsert 두 번 → 행 1개, `entry_count` 갱신
2. `(rcept_dt DESC, rcept_no DESC)` 정렬 + cursor 경계(같은 `rcept_dt` tie)
3. `corp_name` 부분일치, `report_type` 정확일치, 날짜 범위
4. backfill: entries만 있을 때 disclosures 생성, 두 번 실행 idempotent

cursor 조건:

```python
Disclosure.rcept_dt < cursor_dt OR (
    Disclosure.rcept_dt == cursor_dt AND Disclosure.rcept_no < cursor_no
)
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_disclosure_repository.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement repository**

```python
async def list_page(
    self,
    *,
    corp_code: str | None = None,
    corp_name: str | None = None,
    report_nm: str | None = None,
    report_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int,
    cursor_rcept_dt: str | None = None,
    cursor_rcept_no: str | None = None,
) -> list[Disclosure]:
    statement = select(Disclosure)
    if corp_code:
        statement = statement.where(Disclosure.corp_code == corp_code)
    if corp_name:
        statement = statement.where(Disclosure.corp_name.contains(corp_name))
    if report_nm:
        statement = statement.where(Disclosure.report_nm.contains(report_nm))
    if report_type:
        statement = statement.where(Disclosure.report_type == report_type)
    if start_date:
        statement = statement.where(Disclosure.rcept_dt >= start_date)
    if end_date:
        statement = statement.where(Disclosure.rcept_dt <= end_date)
    if cursor_rcept_dt is not None and cursor_rcept_no is not None:
        statement = statement.where(
            or_(
                Disclosure.rcept_dt < cursor_rcept_dt,
                and_(
                    Disclosure.rcept_dt == cursor_rcept_dt,
                    Disclosure.rcept_no < cursor_rcept_no,
                ),
            )
        )
    statement = statement.order_by(
        Disclosure.rcept_dt.desc(), Disclosure.rcept_no.desc()
    ).limit(limit)
    result = await self._session.execute(statement)
    return list(result.scalars().all())
```

`backfill_from_entries`: Entry 전량을 `rcept_no`로 groupby해 `Disclosure` merge. Python groupby로 SQLite/Postgres 공통 구현.

```python
async def backfill_from_entries(self) -> int:
    result = await self._session.execute(select(Entry))
    entries = list(result.scalars().all())
    by_rcp: dict[str, list[Entry]] = {}
    for entry in entries:
        by_rcp.setdefault(entry.rcept_no, []).append(entry)
    rows: list[Disclosure] = []
    for rcept_no, group in by_rcp.items():
        sample = group[0]
        rows.append(
            Disclosure(
                rcept_no=rcept_no,
                corp_code=sample.corp_code,
                corp_name=sample.corp_name,
                report_nm=sample.report_nm,
                report_type=sample.report_type,
                correction_type=sample.correction_type,
                submitter=sample.submitter,
                rcept_dt=sample.rcept_dt or "",
                bsns_year=sample.bsns_year,
                year_end=sample.year_end,
                disclosure_url=sample.disclosure_url,
                entry_count=len(group),
            )
        )
    return await self.upsert_many(rows)
```

- [ ] **Step 4: Run tests PASS**

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/repositories/disclosure_repository.py packages/web-api/tests/test_disclosure_repository.py
git commit -m "feat(web-api): add DisclosureRepository with keyset paging"
```

---

### Task 5: EntryRepository TOC 조회

**Files:**
- Modify: `packages/web-api/app/repositories/entry_repository.py`
- Test: `packages/web-api/tests/test_entry_repository.py`

**Interfaces:**
- Produces: `list_toc_by_rcept_no(rcept_no: str) -> list[Entry]`  
  정렬: body 우선(`source == "body"`), `dcm_no`, `ele_id`, `entry_id`

- [ ] **Step 1: Failing test**

본문·첨부 섞인 레코드를 insert한 뒤 body가 앞에 오고, 같은 source 안에서는 `ele_id` 순인지 검증.

- [ ] **Step 2: Run fail → implement**

```python
async def list_toc_by_rcept_no(self, rcept_no: str) -> list[Entry]:
    statement = (
        select(Entry)
        .where(Entry.rcept_no == rcept_no)
        .order_by(
            case((Entry.source == "body", 0), else_=1),
            Entry.dcm_no,
            Entry.ele_id,
            Entry.entry_id,
        )
    )
    result = await self._session.execute(statement)
    return list(result.scalars().all())
```

(`case`는 `sqlalchemy`에서 import)

- [ ] **Step 3: PASS + Commit**

```bash
git commit -m "feat(web-api): add entry TOC listing ordered by source"
```

---

### Task 6: catalog_query 스키마

**Files:**
- Create: `packages/web-api/app/schemas/catalog_query.py`
- Test: `packages/web-api/tests/test_catalog_query_schemas.py`

**Interfaces:**
- Produces:
  - `DisclosureSummary` — `rcp_no`, `corp_code`, `corp_name`, `report_nm`, `report_type`, `rcept_dt`, `entry_count`, `disclosure_url`
  - `DisclosureListResponse` — `items`, `next_cursor`
  - `EntrySummary` — `entry_id`, `source`, `dcm_no`, `ele_id`, `document_name`, `section_name`, `path`, `depth`
  - `DisclosureEntriesResponse` — `rcp_no`, `report_type`, `primary_entries`, `all_entries`

`DisclosureSummary.from_model(row: Disclosure)`에서 `rcp_no=row.rcept_no` 매핑.

- [ ] Implement + smoke test + Commit

```bash
git commit -m "feat(web-api): add catalog query response schemas"
```

---

### Task 7: CatalogQueryService

**Files:**
- Create: `packages/web-api/app/services/catalog_query_service.py`
- Test: `packages/web-api/tests/test_catalog_query_service.py`

**Interfaces:**
- Consumes: `DisclosureRepository`, `EntryRepository`, `is_primary_section`, `BadRequest`, `CatalogNotFound`
- Produces:
  - `encode_cursor(rcept_dt: str, rcept_no: str) -> str`
  - `decode_cursor(cursor: str) -> tuple[str, str]`
  - `CatalogQueryService.list_disclosures(...) -> DisclosureListResponse`
  - `get_disclosure(rcp_no: str) -> DisclosureSummary`
  - `list_entries(rcp_no: str) -> DisclosureEntriesResponse`

cursor:

```python
import base64
import json

def encode_cursor(rcept_dt: str, rcept_no: str) -> str:
    payload = json.dumps(
        {"rcept_dt": rcept_dt, "rcept_no": rcept_no},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        return data["rcept_dt"], data["rcept_no"]
    except Exception as exc:
        raise BadRequest(
            "커서 값이 올바르지 않습니다. 이전 응답의 next_cursor를 그대로 전달해 주세요."
        ) from exc
```

`list_disclosures`: cursor decode → `list_page(limit=limit+1)` → 초과 시 `next_cursor`.

`list_entries`: disclosure 없으면 `CatalogNotFound`; toc → `EntrySummary`;  
`primary = [e for e in all if is_primary_section(...)]`.

- [ ] TDD: cursor roundtrip, bad cursor, paging, missing rcp, primary ⊆ all
- [ ] Commit

```bash
git commit -m "feat(web-api): add CatalogQueryService with keyset cursor"
```

---

### Task 8: 수집 시 disclosure upsert

**Files:**
- Modify: `packages/web-api/app/services/catalog_service.py`
- Modify: `packages/web-api/tests/test_catalog_service.py`

**Interfaces:**
- Consumes: `DisclosureRepository`, `EntryRecord`
- Produces: `run_job`이 entries 저장 후 `rcept_no`별 `Disclosure` upsert

```python
def disclosures_from_records(records: Sequence[EntryRecord]) -> list[Disclosure]:
    by_rcp: dict[str, list[EntryRecord]] = {}
    for record in records:
        by_rcp.setdefault(record.rcept_no, []).append(record)
    rows: list[Disclosure] = []
    for rcept_no, group in by_rcp.items():
        sample = group[0]
        rows.append(
            Disclosure(
                rcept_no=rcept_no,
                corp_code=sample.corp_code,
                corp_name=sample.corp_name,
                report_nm=sample.report_nm,
                report_type=sample.report_type,
                correction_type=sample.correction_type,
                submitter=sample.submitter,
                rcept_dt=sample.rcept_dt or "",
                bsns_year=sample.bsns_year,
                year_end=sample.year_end,
                disclosure_url=sample.disclosure_url,
                entry_count=len(group),
            )
        )
    return rows
```

`run_job` 성공 경로에서 `EntryRepository.upsert_many` 직후  
`DisclosureRepository.upsert_many(disclosures_from_records(records))`.

주의: `entry_count`는 **이번 배치 leaf 수**다. 부분 재수집 시 DB에 남은 이전 leaf와 어긋날 수 있다. 1차는 배치 완전 수집을 전제로 하고, 필요 시 후속으로 entries `COUNT` 재계산.

- [ ] 테스트: 2 rcp × N leaf → disclosures 2행; 재실행 시 행 수 유지
- [ ] Commit

```bash
git commit -m "feat(web-api): upsert disclosures during catalog extract"
```

---

### Task 9: Public API 라우터 · DI · 앱 등록

**Files:**
- Create: `packages/web-api/app/api/v1/catalog.py`
- Modify: `packages/web-api/app/api/deps.py`
- Modify: `packages/web-api/app/main.py`
- Test: `packages/web-api/tests/test_catalog_query_api.py`

**Interfaces:**
- Produces:
  - `GET /api/v1/catalog/disclosures`
  - `GET /api/v1/catalog/disclosures/{rcp_no}`
  - `GET /api/v1/catalog/disclosures/{rcp_no}/entries`
  - `get_catalog_query_service(session) -> CatalogQueryService`

```python
router = APIRouter(prefix="/api/v1/catalog", tags=["Catalog"])

@router.get("/disclosures", response_model=DisclosureListResponse)
async def list_disclosures(
    corp_code: str | None = None,
    corp_name: str | None = None,
    report_nm: str | None = None,
    report_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    service: CatalogQueryService = Depends(get_catalog_query_service),
) -> DisclosureListResponse:
    return await service.list_disclosures(
        corp_code=corp_code,
        corp_name=corp_name,
        report_nm=report_nm,
        report_type=report_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        cursor=cursor,
    )
```

API 테스트는 `dependency_overrides[get_catalog_query_service]`로 Fake 주입.

커버: 200 스키마, limit>100 → 422, BadRequest → 400, CatalogNotFound → 404, entries에 primary/all/entry_id.

- [ ] Commit

```bash
git commit -m "feat(web-api): expose public catalog query endpoints"
```

---

### Task 10: backfill 스크립트 · README · 전체 검증

**Files:**
- Create: `packages/web-api/scripts/backfill_disclosures.py`
- Modify: `packages/web-api/README.md`

```python
"""entries로부터 disclosures를 일회성으로 채운다."""
import asyncio
from app.config import get_settings
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.repositories.disclosure_repository import DisclosureRepository


async def main() -> None:
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        count = await DisclosureRepository(session).backfill_from_entries()
        await session.commit()
    await engine.dispose()
    print(f"disclosures upsert {count}건 완료")


if __name__ == "__main__":
    asyncio.run(main())
```

README에 세 엔드포인트·cursor·primary/all·backfill 명령 추가.

- [ ] **전체 테스트**

```bash
cd packages/web-api
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m black --check .
.\.venv\Scripts\python.exe -m flake8
```

Expected: 전 테스트 PASS, style clean

- [ ] Commit

```bash
git commit -m "docs(web-api): document catalog query API and backfill"
```

---

## Spec coverage checklist

| Spec 요구 | Task |
|-----------|------|
| `disclosures` 테이블 | 2 |
| keyset cursor 목록 | 4, 7, 9 |
| 단건 / 목차 API | 7, 9 |
| `primary_entries` + `all_entries` | 3, 7, 9 |
| F001 코드 상수 allowlist | 3 |
| 수집 시 disclosure upsert | 8 |
| backfill | 4, 10 |
| BadRequest 400 | 1, 7, 9 |
| 필터 corp/report/date | 4, 9 |
| total 미제공 / 전역 leaf API 없음 | 의도적 범위 밖 |
| Alembic / Admin 인증 / Viewer 캐시 | 범위 밖 |

## Consistency notes

- 응답 `rcp_no` ↔ DB `rcept_no` 매핑은 Task 6·7에서만 수행
- `entry_count`는 Task 8에서 **배치 leaf 수** (후속 개선 가능)
- `list_toc` 정렬은 Task 5와 스펙 §4.3 일치
