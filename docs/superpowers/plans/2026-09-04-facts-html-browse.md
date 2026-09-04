# 감사 추출 결과 HTML 탐색 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** facts가 있는 감사 문서를 접수 조인 메타와 함께 Public 납작 표(`/facts`)와 JSON 목록(`GET /api/v1/facts`)으로 보여 준다.

**Architecture:** `FactRepository.list_page`가 `audit_report_facts`를 `disclosures`에 INNER JOIN한 뒤 keyset cursor로 자른다. `FactQueryService`가 커서를 인코딩하고 `FactListItem`으로 조립한다. HTML은 `/catalog`와 같은 Jinja 표이며 JSON 칸만 별도 셀 함수(`fact_cell`)를 쓴다. 기존 `GET /api/v1/disclosures/{rcp_no}/audit-facts`는 그대로 둔다.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2 async, Jinja2, pytest, httpx AsyncClient (테스트만)

**Spec:** `docs/superpowers/specs/2026-09-04-facts-html-browse-design.md`

## Global Constraints

- 주석·Docstring·로그·예외·테스트 설명은 한국어. 함수 입출력 Type Hint 필수.
- I/O는 async. extracting 순수 함수는 이 작업에 없음.
- DART HTTP·추출 잡·스키마 마이그레이션 없음. 메모리 SQLite만.
- 행 단위는 `rcept_no` + `dcm_no`. 공시 행이 없는 facts는 INNER JOIN으로 빠진다.
- `date_resolver_*`는 HTML·JSON 목록에 넣지 않음.
- 총건수 없음. `limit` 기본 20, 최대 100 (`Query(20, ge=1, le=100)`).
- 작업 디렉터리: `packages/web-api`. pytest: `.\.venv\Scripts\python.exe -m pytest …` (`asyncio_mode = auto`).
- git 커밋은 **사용자가 요청한 경우에만**. 아래 Commit 스텝은 메시지 초안이다.
- Windows PowerShell 커밋은 bash HEREDOC 대신 `git commit -m "한글 한 줄"`을 쓴다.

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `packages/web-api/app/schemas/facts.py` | `JOIN_COLUMNS`, `FACT_PUBLIC_COLUMNS`, `FactListItem`, `FactListResponse`, `fact_list_item_from` |
| `packages/web-api/app/repositories/fact_repository.py` | `list_page` (join·필터·keyset) |
| `packages/web-api/app/services/fact_query_service.py` | cursor 인코딩, `FactQueryService.list_page` |
| `packages/web-api/app/api/deps.py` | `get_fact_query_service` |
| `packages/web-api/app/api/v1/facts.py` | 기존 단건 라우터 유지 + `list_router` `GET /api/v1/facts` |
| `packages/web-api/app/api/facts/__init__.py` | 패키지 |
| `packages/web-api/app/api/facts/ui.py` | `GET /facts`, `fact_cell` |
| `packages/web-api/app/templates/facts/list.html` | 납작 표. `catalog/base.html` 확장 |
| `packages/web-api/app/templates/catalog/base.html` | Catalog · Facts 내비 |
| `packages/web-api/app/main.py` | HTML·목록 라우터 등록 |
| `packages/web-api/tests/test_facts_schema.py` | 공개 컬럼·조인 스키마 |
| `packages/web-api/tests/test_fact_query_service.py` | cursor·서비스 페이징 |
| `packages/web-api/tests/test_fact_repository.py` | `list_page` |
| `packages/web-api/tests/test_facts_api.py` | 목록 JSON 보강 |
| `packages/web-api/tests/test_facts_ui.py` | HTML |
| `README.md`, `packages/web-api/README.md` | `/facts` 안내 |

기존 패턴 (복제하지 말고 같은 모양으로 맞출 것):

- cursor: `app/services/catalog_query_service.py`의 `encode_cursor` / `decode_cursor` (`BadRequest` 문구 동일, payload에 `dcm_no`만 추가)
- keyset SQL: `app/repositories/disclosure_repository.py` `list_page` + 세 번째 키 `dcm_no ASC`
- HTML: `app/api/catalog/ui.py` + `templates/catalog/list.html`. JSON 칸은 `catalog_cell`의 ` › ` 조인을 **쓰지 않는다**
- 단건 facts 시드: `tests/test_facts_api.py`의 `_memory_app` / `_fact` / `_seed`

---

### Task 1: 목록 스키마와 공개 컬럼

**Files:**
- Modify: `packages/web-api/app/schemas/facts.py`
- Test: `packages/web-api/tests/test_facts_schema.py`

**Interfaces:**
- Consumes: `AuditReportFactItem`, `AuditReportFact.__table__.columns`, `Disclosure`
- Produces:
  - `JOIN_COLUMNS: tuple[str, ...] = ("corp_name", "year_end", "rcept_dt", "correction_type")`
  - `DATE_RESOLVER_COLUMNS: tuple[str, ...]`
  - `FACT_PUBLIC_COLUMNS: tuple[str, ...]` — 모델 선언 순서에서 resolver 3칸 제외
  - `LIST_COLUMNS: tuple[str, ...] = JOIN_COLUMNS + FACT_PUBLIC_COLUMNS`
  - `class FactJoinFields(BaseModel)`
  - `class FactListItem(FactJoinFields, AuditReportFactItem)` — 다중 상속으로 JSON 키가 조인 4칸부터 시작
  - `class FactListResponse(BaseModel)` — `items: list[FactListItem]`, `next_cursor: str | None = None`
  - `def fact_list_item_from(fact: AuditReportFact, disclosure: Disclosure) -> FactListItem`

- [ ] **Step 1: Write the failing test**

Create `packages/web-api/tests/test_facts_schema.py`:

```python
"""FactListItem 조인 칸·공개 컬럼 테스트."""

from datetime import datetime, timezone

from app.extracting.constants import EXTRACTOR_VERSION
from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
from app.schemas.facts import (
    DATE_RESOLVER_COLUMNS,
    FACT_PUBLIC_COLUMNS,
    JOIN_COLUMNS,
    LIST_COLUMNS,
    fact_list_item_from,
)


def test_public_columns_follow_model_and_drop_resolver() -> None:
    names = [column.name for column in AuditReportFact.__table__.columns]
    assert DATE_RESOLVER_COLUMNS == (
        "date_resolver_model",
        "date_resolver_prompt_version",
        "date_resolver_raw_response",
    )
    assert FACT_PUBLIC_COLUMNS == tuple(
        name for name in names if name not in DATE_RESOLVER_COLUMNS
    )
    assert JOIN_COLUMNS == ("corp_name", "year_end", "rcept_dt", "correction_type")
    assert LIST_COLUMNS == JOIN_COLUMNS + FACT_PUBLIC_COLUMNS


def test_fact_list_item_from_joins_catalog_and_hides_resolver() -> None:
    fact = AuditReportFact(
        rcept_no="20200331000001",
        dcm_no="11111",
        source_report_type="F001",
        fs_scope="separate",
        fetch_status="ok",
        extractor_version=EXTRACTOR_VERSION,
        date_resolver_model="gpt-4o-mini",
        extracted_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
    )
    disc = Disclosure(
        rcept_no="20200331000001",
        corp_name="삼호저축은행",
        year_end="(2025.12)",
        rcept_dt="2026.06.01",
        correction_type="최초공시",
        entry_count=1,
    )
    item = fact_list_item_from(fact, disc)
    dumped = item.model_dump()
    keys = list(dumped)
    assert keys[:4] == ["corp_name", "year_end", "rcept_dt", "correction_type"]
    assert dumped["corp_name"] == "삼호저축은행"
    assert dumped["year_end"] == "(2025.12)"
    assert dumped["rcept_dt"] == "2026.06.01"
    assert dumped["correction_type"] == "최초공시"
    assert dumped["rcept_no"] == "20200331000001"
    assert dumped["dcm_no"] == "11111"
    assert "date_resolver_model" not in dumped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/web-api` 후 `.\.venv\Scripts\python.exe -m pytest tests/test_facts_schema.py -v`

Expected: FAIL — `ImportError` (`FACT_PUBLIC_COLUMNS` / `fact_list_item_from` 없음)

- [ ] **Step 3: Write minimal implementation**

`packages/web-api/app/schemas/facts.py` 상단 import에 모델을 추가하고, 파일 하단에 목록 타입을 붙인다. `AuditReportFact`는 schemas를 import하지 않으므로 순환이 없다.

기존 import 블록을 다음처럼 바꾼다:

```python
from pydantic import BaseModel, ConfigDict, Field

from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
```

`AuditReportFactItem` 클래스 **아래**에 추가:

```python
JOIN_COLUMNS: tuple[str, ...] = (
    "corp_name",
    "year_end",
    "rcept_dt",
    "correction_type",
)
DATE_RESOLVER_COLUMNS: tuple[str, ...] = (
    "date_resolver_model",
    "date_resolver_prompt_version",
    "date_resolver_raw_response",
)
FACT_PUBLIC_COLUMNS: tuple[str, ...] = tuple(
    column.name
    for column in AuditReportFact.__table__.columns
    if column.name not in DATE_RESOLVER_COLUMNS
)
LIST_COLUMNS: tuple[str, ...] = JOIN_COLUMNS + FACT_PUBLIC_COLUMNS


class FactJoinFields(BaseModel):
    """목록 JSON에서 앞에 둘 카탈로그 조인 칸."""

    corp_name: str | None = None
    year_end: str | None = None
    rcept_dt: str | None = None
    correction_type: str | None = None


class FactListItem(FactJoinFields, AuditReportFactItem):
    """목록 한 행. 조인 4칸 + 공개 facts (`date_resolver_*` 없음)."""


class FactListResponse(BaseModel):
    """추출 결과 목록과 다음 페이지 cursor."""

    items: list[FactListItem] = Field(default_factory=list)
    next_cursor: str | None = None


def fact_list_item_from(fact: AuditReportFact, disclosure: Disclosure) -> FactListItem:
    """facts 행과 공시 메타를 목록 아이템으로 합친다."""
    base = AuditReportFactItem.model_validate(fact)
    return FactListItem(
        **base.model_dump(),
        corp_name=disclosure.corp_name,
        year_end=disclosure.year_end,
        rcept_dt=disclosure.rcept_dt,
        correction_type=disclosure.correction_type,
    )
```

`AuditReportFactItem`만 상속하면 Pydantic이 부모 필드를 앞에 두어 조인 칸이 JSON 뒤로 간다. `FactJoinFields`를 **첫 베이스**로 둔다.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_facts_schema.py -v`

Expected: PASS

- [ ] **Step 5: Commit (초안, 사용자 요청 시에만)**

```text
git add packages/web-api/app/schemas/facts.py packages/web-api/tests/test_facts_schema.py
git commit -m "feat: 추출 목록 조인 스키마와 공개 컬럼을 둔다"
```

---

### Task 2: 세 필드 cursor

**Files:**
- Create: `packages/web-api/app/services/fact_query_service.py`
- Test: `packages/web-api/tests/test_fact_query_service.py`

**Interfaces:**
- Consumes: `app.errors.BadRequest`
- Produces:
  - `def encode_fact_cursor(rcept_dt: str, rcept_no: str, dcm_no: str) -> str`
  - `def decode_fact_cursor(cursor: str) -> tuple[str, str, str]` — 실패 시 `BadRequest` (카탈로그와 같은 안내 문구)

이 태스크에서는 `FactQueryService` 클래스를 만들지 않는다. repository import도 없다.

- [ ] **Step 1: Write the failing test**

Create `packages/web-api/tests/test_fact_query_service.py`:

```python
"""FactQueryService cursor·목록 테스트."""

import pytest

from app.errors import BadRequest
from app.services.fact_query_service import decode_fact_cursor, encode_fact_cursor


def test_fact_cursor_roundtrip() -> None:
    token = encode_fact_cursor("2026.06.01", "20260601000466", "11411460")
    assert decode_fact_cursor(token) == (
        "2026.06.01",
        "20260601000466",
        "11411460",
    )


def test_decode_fact_cursor_rejects_garbage() -> None:
    with pytest.raises(BadRequest, match="커서 값이 올바르지 않습니다"):
        decode_fact_cursor("!!!")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fact_query_service.py::test_fact_cursor_roundtrip -v`

Expected: FAIL — `ModuleNotFoundError` (`app.services.fact_query_service`)

- [ ] **Step 3: Write minimal implementation**

Create `packages/web-api/app/services/fact_query_service.py` **전체**:

```python
"""Public 감사 추출 결과 목록 조회."""

from __future__ import annotations

import base64
import json

from app.errors import BadRequest


def encode_fact_cursor(rcept_dt: str, rcept_no: str, dcm_no: str) -> str:
    """목록 페이지의 opaque cursor를 만든다."""
    payload = json.dumps(
        {"rcept_dt": rcept_dt, "rcept_no": rcept_no, "dcm_no": dcm_no},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_fact_cursor(cursor: str) -> tuple[str, str, str]:
    """opaque cursor를 (rcept_dt, rcept_no, dcm_no)로 복원한다.

    :raises BadRequest: 손상되었거나 필드가 없는 경우
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        return data["rcept_dt"], data["rcept_no"], data["dcm_no"]
    except Exception as exc:
        raise BadRequest(
            "커서 값이 올바르지 않습니다. 이전 응답의 next_cursor를 그대로 전달해 주세요."
        ) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fact_query_service.py -v`

Expected: PASS (2 tests)

- [ ] **Step 5: Commit (초안, 사용자 요청 시에만)**

```text
git add packages/web-api/app/services/fact_query_service.py packages/web-api/tests/test_fact_query_service.py
git commit -m "feat: 추출 목록 cursor를 접수일·접수번호·dcm으로 둔다"
```

---

### Task 3: FactRepository.list_page

**Files:**
- Modify: `packages/web-api/app/repositories/fact_repository.py`
- Test: `packages/web-api/tests/test_fact_repository.py`

**Interfaces:**
- Consumes: `AuditReportFact`, `Disclosure`
- Produces: `async def list_page(self, *, corp_code: str | None = None, corp_name: str | None = None, report_nm: str | None = None, report_type: str | None = None, start_date: str | None = None, end_date: str | None = None, limit: int, cursor_rcept_dt: str | None = None, cursor_rcept_no: str | None = None, cursor_dcm_no: str | None = None) -> list[tuple[AuditReportFact, Disclosure]]`

필터: 회사·보고서명·날짜는 `Disclosure`. `report_type`은 `AuditReportFact.source_report_type` (스펙).  
정렬: `Disclosure.rcept_dt.desc()`, `AuditReportFact.rcept_no.desc()`, `AuditReportFact.dcm_no.asc()`.  
keyset (내림차순 두 키 + `dcm_no` 오름차순):

- `rcept_dt < cursor` 이거나
- 같은 `rcept_dt`이고 `rcept_no < cursor` 이거나
- 세 키가 같고 `dcm_no > cursor`

- [ ] **Step 1: Write the failing test**

Create `packages/web-api/tests/test_fact_repository.py`:

```python
"""FactRepository.list_page 조인·정렬·cursor 테스트."""

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.extracting.constants import EXTRACTOR_VERSION
from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
from app.repositories.fact_repository import FactRepository


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def _fact(**overrides: object) -> AuditReportFact:
    values: dict[str, object] = {
        "rcept_no": "20200331000001",
        "dcm_no": "11111",
        "source_report_type": "F001",
        "fs_scope": "separate",
        "fetch_status": "ok",
        "extractor_version": EXTRACTOR_VERSION,
    }
    values.update(overrides)
    return AuditReportFact(**values)


def _disc(**overrides: object) -> Disclosure:
    values: dict[str, object] = {
        "rcept_no": "20200331000001",
        "corp_name": "갑",
        "year_end": "(2019.12)",
        "rcept_dt": "2020.03.31",
        "correction_type": "최초공시",
        "report_nm": "감사보고서",
        "report_type": "F001",
        "corp_code": "00123456",
        "entry_count": 1,
    }
    values.update(overrides)
    return Disclosure(**values)


async def test_list_page_inner_join_drops_orphan_facts(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        await session.commit()
        rows = await FactRepository(session).list_page(limit=20)
    assert rows == []


async def test_list_page_orders_date_desc_rcept_desc_dcm_asc(
    sessionmaker_fixture,
) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all(
            [
                _disc(rcept_no="20240331000002", rcept_dt="2024.03.31", corp_name="을"),
                _disc(
                    rcept_no="20240331000001",
                    rcept_dt="2024.03.31",
                    corp_name="병",
                    report_type="A001",
                    report_nm="사업보고서",
                ),
                _disc(rcept_no="20200331000001", rcept_dt="2020.03.31"),
                _fact(rcept_no="20200331000001"),
                _fact(
                    rcept_no="20240331000001",
                    dcm_no="22222",
                    source_report_type="A001",
                    fs_scope="consolidated",
                ),
                _fact(
                    rcept_no="20240331000001",
                    dcm_no="11111",
                    source_report_type="A001",
                    fs_scope="separate",
                ),
                _fact(rcept_no="20240331000002", dcm_no="33333"),
            ]
        )
        await session.commit()
        rows = await FactRepository(session).list_page(limit=20)
    keys = [(d.rcept_dt, f.rcept_no, f.dcm_no) for f, d in rows]
    assert keys == [
        ("2024.03.31", "20240331000002", "33333"),
        ("2024.03.31", "20240331000001", "11111"),
        ("2024.03.31", "20240331000001", "22222"),
        ("2020.03.31", "20200331000001", "11111"),
    ]


async def test_list_page_filters_and_keyset(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all(
            [
                _disc(rcept_no="a", rcept_dt="2024.03.31", corp_name="삼성전자"),
                _disc(rcept_no="b", rcept_dt="2024.03.31", corp_name="다른회사"),
                _fact(rcept_no="a", dcm_no="1"),
                _fact(rcept_no="b", dcm_no="1"),
            ]
        )
        await session.commit()
        repo = FactRepository(session)
        named = await repo.list_page(limit=20, corp_name="삼성")
        assert [f.rcept_no for f, _d in named] == ["a"]
        page1 = await repo.list_page(limit=1)
        assert page1[0][0].rcept_no == "b"
        page2 = await repo.list_page(
            limit=1,
            cursor_rcept_dt=page1[0][1].rcept_dt,
            cursor_rcept_no=page1[0][0].rcept_no,
            cursor_dcm_no=page1[0][0].dcm_no,
        )
        assert page2[0][0].rcept_no == "a"


async def test_list_page_report_type_uses_source_report_type(
    sessionmaker_fixture,
) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all(
            [
                _disc(rcept_no="a", report_type="A001"),
                _fact(rcept_no="a", source_report_type="A001"),
            ]
        )
        await session.commit()
        repo = FactRepository(session)
        matched = await repo.list_page(limit=20, report_type="A001")
        missed = await repo.list_page(limit=20, report_type="F001")
    assert [f.source_report_type for f, _d in matched] == ["A001"]
    assert missed == []
```

같은 날짜에서 `rcept_no` ASCII 내림차순은 `"b" > "a"`이므로 `limit=1` 첫 행은 `"b"`다.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fact_repository.py::test_list_page_inner_join_drops_orphan_facts -v`

Expected: FAIL — `AttributeError: 'FactRepository' object has no attribute 'list_page'`

- [ ] **Step 3: Write minimal implementation**

`packages/web-api/app/repositories/fact_repository.py` 상단 import를 다음으로 바꾼다:

```python
from collections.abc import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
from app.models.entry import Entry
```

`FactRepository` 클래스 안, `list_by_rcept_nos` **다음**에 메서드를 추가한다:

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
        cursor_dcm_no: str | None = None,
    ) -> list[tuple[AuditReportFact, Disclosure]]:
        """공시와 조인한 추출 행을 keyset으로 돌려준다."""
        statement = select(AuditReportFact, Disclosure).join(
            Disclosure, AuditReportFact.rcept_no == Disclosure.rcept_no
        )
        if corp_code:
            statement = statement.where(Disclosure.corp_code == corp_code)
        if corp_name:
            statement = statement.where(Disclosure.corp_name.contains(corp_name))
        if report_nm:
            statement = statement.where(Disclosure.report_nm.contains(report_nm))
        if report_type:
            statement = statement.where(AuditReportFact.source_report_type == report_type)
        if start_date:
            statement = statement.where(Disclosure.rcept_dt >= start_date)
        if end_date:
            statement = statement.where(Disclosure.rcept_dt <= end_date)
        if (
            cursor_rcept_dt is not None
            and cursor_rcept_no is not None
            and cursor_dcm_no is not None
        ):
            statement = statement.where(
                or_(
                    Disclosure.rcept_dt < cursor_rcept_dt,
                    and_(
                        Disclosure.rcept_dt == cursor_rcept_dt,
                        AuditReportFact.rcept_no < cursor_rcept_no,
                    ),
                    and_(
                        Disclosure.rcept_dt == cursor_rcept_dt,
                        AuditReportFact.rcept_no == cursor_rcept_no,
                        AuditReportFact.dcm_no > cursor_dcm_no,
                    ),
                )
            )
        statement = statement.order_by(
            Disclosure.rcept_dt.desc(),
            AuditReportFact.rcept_no.desc(),
            AuditReportFact.dcm_no.asc(),
        ).limit(limit)
        result = await self._session.execute(statement)
        return [(fact, disc) for fact, disc in result.all()]
```

기존 `upsert` / `get` / `list_by_rcept_no` / `list_ambiguous_dates` / `list_siblings`는 바꾸지 않는다.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fact_repository.py -v`

Expected: PASS (4 tests)

- [ ] **Step 5: Commit (초안, 사용자 요청 시에만)**

```text
git add packages/web-api/app/repositories/fact_repository.py packages/web-api/tests/test_fact_repository.py
git commit -m "feat: 추출 목록을 공시와 조인해 keyset으로 읽는다"
```

---

### Task 4: FactQueryService.list_page

**Files:**
- Modify: `packages/web-api/app/services/fact_query_service.py`
- Modify: `packages/web-api/tests/test_fact_query_service.py`

**Interfaces:**
- Consumes: `FactRepository.list_page`, `encode_fact_cursor`, `decode_fact_cursor`, `fact_list_item_from`
- Produces: `class FactQueryService` with `async def list_page(self, *, corp_code: str | None = None, corp_name: str | None = None, report_nm: str | None = None, report_type: str | None = None, start_date: str | None = None, end_date: str | None = None, limit: int = 20, cursor: str | None = None) -> FactListResponse`

저장소에는 `limit + 1`을 넘긴다. 초과분이 있으면 `rows[limit - 1]`로 `next_cursor`를 만들고 `rows[:limit]`만 반환한다.

- [ ] **Step 1: Write the failing test**

`packages/web-api/tests/test_fact_query_service.py` **전체**를 다음으로 교체한다 (cursor 테스트 유지, 서비스 테스트 추가):

```python
"""FactQueryService cursor·목록 테스트."""

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import BadRequest
from app.extracting.constants import EXTRACTOR_VERSION
from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
from app.repositories.fact_repository import FactRepository
from app.services.fact_query_service import (
    FactQueryService,
    decode_fact_cursor,
    encode_fact_cursor,
)


def test_fact_cursor_roundtrip() -> None:
    token = encode_fact_cursor("2026.06.01", "20260601000466", "11411460")
    assert decode_fact_cursor(token) == (
        "2026.06.01",
        "20260601000466",
        "11411460",
    )


def test_decode_fact_cursor_rejects_garbage() -> None:
    with pytest.raises(BadRequest, match="커서 값이 올바르지 않습니다"):
        decode_fact_cursor("!!!")


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


async def test_list_page_sets_next_cursor_and_maps_join(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all(
            [
                Disclosure(
                    rcept_no="r2",
                    rcept_dt="2024.03.31",
                    corp_name="을",
                    correction_type="최초공시",
                    year_end="(2023.12)",
                    entry_count=1,
                ),
                Disclosure(
                    rcept_no="r1",
                    rcept_dt="2024.03.31",
                    corp_name="갑",
                    correction_type="기재정정",
                    year_end="(2023.12)",
                    entry_count=1,
                ),
                AuditReportFact(
                    rcept_no="r2",
                    dcm_no="2",
                    source_report_type="F001",
                    fs_scope="separate",
                    fetch_status="ok",
                    extractor_version=EXTRACTOR_VERSION,
                ),
                AuditReportFact(
                    rcept_no="r1",
                    dcm_no="1",
                    source_report_type="F001",
                    fs_scope="separate",
                    fetch_status="section_missing",
                    extractor_version=EXTRACTOR_VERSION,
                ),
            ]
        )
        await session.commit()
        service = FactQueryService(FactRepository(session))
        page1 = await service.list_page(limit=1)
        assert len(page1.items) == 1
        assert page1.items[0].rcept_no == "r2"
        assert page1.items[0].corp_name == "을"
        assert page1.next_cursor is not None
        page2 = await service.list_page(limit=1, cursor=page1.next_cursor)
        assert [item.rcept_no for item in page2.items] == ["r1"]
        assert page2.items[0].fetch_status == "section_missing"
        assert page2.next_cursor is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fact_query_service.py::test_list_page_sets_next_cursor_and_maps_join -v`

Expected: FAIL — `ImportError` (`FactQueryService` 없음)

- [ ] **Step 3: Write minimal implementation**

`packages/web-api/app/services/fact_query_service.py` **전체**:

```python
"""Public 감사 추출 결과 목록 조회."""

from __future__ import annotations

import base64
import json

from app.errors import BadRequest
from app.repositories.fact_repository import FactRepository
from app.schemas.facts import FactListResponse, fact_list_item_from


def encode_fact_cursor(rcept_dt: str, rcept_no: str, dcm_no: str) -> str:
    """목록 페이지의 opaque cursor를 만든다."""
    payload = json.dumps(
        {"rcept_dt": rcept_dt, "rcept_no": rcept_no, "dcm_no": dcm_no},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_fact_cursor(cursor: str) -> tuple[str, str, str]:
    """opaque cursor를 (rcept_dt, rcept_no, dcm_no)로 복원한다.

    :raises BadRequest: 손상되었거나 필드가 없는 경우
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        return data["rcept_dt"], data["rcept_no"], data["dcm_no"]
    except Exception as exc:
        raise BadRequest(
            "커서 값이 올바르지 않습니다. 이전 응답의 next_cursor를 그대로 전달해 주세요."
        ) from exc


class FactQueryService:
    """추출 결과 목록 조회."""

    def __init__(self, facts: FactRepository) -> None:
        self._facts = facts

    async def list_page(
        self,
        *,
        corp_code: str | None = None,
        corp_name: str | None = None,
        report_nm: str | None = None,
        report_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> FactListResponse:
        """필터와 keyset cursor로 추출 목록을 반환한다."""
        cursor_dt = cursor_no = cursor_dcm = None
        if cursor:
            cursor_dt, cursor_no, cursor_dcm = decode_fact_cursor(cursor)
        rows = await self._facts.list_page(
            corp_code=corp_code,
            corp_name=corp_name,
            report_nm=report_nm,
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit + 1,
            cursor_rcept_dt=cursor_dt,
            cursor_rcept_no=cursor_no,
            cursor_dcm_no=cursor_dcm,
        )
        next_cursor: str | None = None
        if len(rows) > limit:
            last_fact, last_disc = rows[limit - 1]
            next_cursor = encode_fact_cursor(
                last_disc.rcept_dt, last_fact.rcept_no, last_fact.dcm_no
            )
            rows = rows[:limit]
        return FactListResponse(
            items=[fact_list_item_from(fact, disc) for fact, disc in rows],
            next_cursor=next_cursor,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fact_query_service.py -v`

Expected: PASS (3 tests)

- [ ] **Step 5: Commit (초안, 사용자 요청 시에만)**

```text
git add packages/web-api/app/services/fact_query_service.py packages/web-api/tests/test_fact_query_service.py
git commit -m "feat: 추출 목록 조회 서비스에 cursor 페이징을 붙인다"
```

---

### Task 5: GET /api/v1/facts

**Files:**
- Modify: `packages/web-api/app/api/deps.py`
- Modify: `packages/web-api/app/api/v1/facts.py`
- Modify: `packages/web-api/app/main.py`
- Modify: `packages/web-api/tests/test_facts_api.py`

**Interfaces:**
- Consumes: `FactQueryService.list_page`
- Produces:
  - `def get_fact_query_service(session: AsyncSession = Depends(get_session)) -> FactQueryService`
  - `list_router = APIRouter(prefix="/api/v1", tags=["Facts"])` 의 `GET /facts` → `FactListResponse`
  - 기존 `router` `GET /{rcp_no}/audit-facts` 유지

- [ ] **Step 1: Write the failing test**

`packages/web-api/tests/test_facts_api.py` 상단에 `Disclosure` import를 추가한다:

```python
from app.models.disclosure import Disclosure
```

파일 하단에 테스트를 추가한다. `_memory_app` / `_fact` / `_seed`는 기존과 같다.

```python
LIST_PATH = "/api/v1/facts"


async def test_list_facts_empty_is_not_404(client_factory) -> None:
    app, _sessionmaker, engine = await _memory_app()
    try:
        async with client_factory(app) as client:
            response = await client.get(LIST_PATH)
    finally:
        await engine.dispose()
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


async def test_list_facts_pages_and_rejects_bad_cursor(client_factory) -> None:
    app, sessionmaker, engine = await _memory_app()
    try:
        async with sessionmaker() as session:
            session.add(
                Disclosure(
                    rcept_no="20200331000001",
                    rcept_dt="2020.03.31",
                    corp_name="갑",
                    correction_type="최초공시",
                    year_end="(2019.12)",
                    entry_count=1,
                )
            )
            session.add(
                Disclosure(
                    rcept_no="20200331000002",
                    rcept_dt="2020.03.31",
                    corp_name="을",
                    correction_type="최초공시",
                    year_end="(2019.12)",
                    entry_count=1,
                )
            )
            await session.commit()
        await _seed(
            sessionmaker,
            [
                _fact(rcept_no="20200331000002", dcm_no="2"),
                _fact(rcept_no="20200331000001", dcm_no="1"),
            ],
        )
        async with client_factory(app) as client:
            first = await client.get(LIST_PATH, params={"limit": 1})
            assert first.status_code == 200
            body = first.json()
            assert len(body["items"]) == 1
            assert body["items"][0]["rcept_no"] == "20200331000002"
            assert body["items"][0]["corp_name"] == "을"
            assert "date_resolver_model" not in body["items"][0]
            assert body["next_cursor"]
            second = await client.get(
                LIST_PATH, params={"limit": 1, "cursor": body["next_cursor"]}
            )
            assert [row["rcept_no"] for row in second.json()["items"]] == [
                "20200331000001"
            ]
            bad = await client.get(LIST_PATH, params={"cursor": "!!!"})
            assert bad.status_code == 400
    finally:
        await engine.dispose()
```

기존 단건 테스트 4개는 그대로 통과해야 한다.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_facts_api.py::test_list_facts_empty_is_not_404 -v`

Expected: FAIL — `404` (경로 없음)

- [ ] **Step 3: Write minimal implementation**

`packages/web-api/app/api/deps.py` — `from app.services.catalog_query_service import CatalogQueryService` 근처에:

```python
from app.services.fact_query_service import FactQueryService
```

`get_catalog_query_service` **바로 아래**에:

```python
def get_fact_query_service(
    session: AsyncSession = Depends(get_session),
) -> FactQueryService:
    """Public 추출 목록 조회 서비스를 제공한다."""
    return FactQueryService(FactRepository(session))
```

`packages/web-api/app/api/v1/facts.py` **전체**:

```python
"""Public 감사 추출 결과 조회 라우터."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_fact_query_service, get_fact_repository
from app.models.audit_report_fact import AuditReportFact
from app.repositories.fact_repository import FactRepository
from app.schemas.facts import AuditReportFactItem, FactListResponse
from app.services.fact_query_service import FactQueryService

router = APIRouter(prefix="/api/v1/disclosures", tags=["Facts"])
list_router = APIRouter(prefix="/api/v1", tags=["Facts"])


@router.get(
    "/{rcp_no}/audit-facts",
    response_model=list[AuditReportFactItem],
    summary="공시별 감사 추출 결과 조회",
)
async def list_audit_facts(
    rcp_no: str,
    facts: FactRepository = Depends(get_fact_repository),
) -> list[AuditReportFact]:
    """접수번호의 추출 행을 반환한다. 없으면 빈 목록이다(404가 아니다)."""
    return await facts.list_by_rcept_no(rcp_no)


@list_router.get("/facts", response_model=FactListResponse, summary="감사 추출 결과 목록")
async def list_facts(
    corp_code: str | None = None,
    corp_name: str | None = None,
    report_nm: str | None = None,
    report_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    service: FactQueryService = Depends(get_fact_query_service),
) -> FactListResponse:
    """회사·보고서·기간으로 추출 문서 목록을 조회한다(keyset cursor)."""
    return await service.list_page(
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

`packages/web-api/app/main.py` `create_app`에서 `app.include_router(audit_facts.router)` **다음 줄**:

```python
    app.include_router(audit_facts.list_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_facts_api.py -v`

Expected: PASS (기존 4 + 목록 2)

- [ ] **Step 5: Commit (초안, 사용자 요청 시에만)**

```text
git add packages/web-api/app/api/deps.py packages/web-api/app/api/v1/facts.py packages/web-api/app/main.py packages/web-api/tests/test_facts_api.py
git commit -m "feat: Public 추출 목록 JSON API를 추가한다"
```

---

### Task 6: GET /facts HTML

**Files:**
- Create: `packages/web-api/app/api/facts/__init__.py` (빈 파일)
- Create: `packages/web-api/app/api/facts/ui.py`
- Create: `packages/web-api/app/templates/facts/list.html`
- Modify: `packages/web-api/app/templates/catalog/base.html`
- Modify: `packages/web-api/app/main.py`
- Test: `packages/web-api/tests/test_facts_ui.py`
- Modify: `packages/web-api/tests/test_catalog_ui.py`

`templates/catalog/list.html`은 수정하지 않는다. 내비는 `base.html`에만 넣으면 목록·목차 모두에 보인다.

**Interfaces:**
- Consumes: `FactQueryService.list_page`, `LIST_COLUMNS`
- Produces: `def fact_cell(value: Any) -> str`, `GET /facts` HTML

`fact_cell` 규칙:

- `None` / `""` / `[]` / `{}` → `—`
- `bool` → `true` / `false`
- `datetime` → `isoformat()`
- `list`·`dict`(비어 있지 않음) → `json.dumps(..., ensure_ascii=False, separators=(",", ":"))`
- 그 외 `str(value)`, 빈 문자열이면 `—`

Jinja는 HTML 이스케이프하므로 브라우저 테스트는 `html.unescape`로 JSON을 확인한다. ` › ` 조인이 없음을 **단위 테스트**에서 본다.

카탈로그 HTML은 필터 쿼리를 넘기지 않지만, 스펙상 `/facts`는 쿼리 문자열이 있으면 서비스에 전달한다. 화면 폼은 없다. «다음»은 `limit`·필터·`cursor`를 유지한다.

잘못된 cursor는 카탈로그와 같이 `BadRequest`를 잡아 안내를 보여 주고, `cursor=None`으로 첫 페이지를 다시 읽는다.

- [ ] **Step 1: Write the failing test**

Create `packages/web-api/tests/test_facts_ui.py`:

```python
"""Public Facts HTML 탐색 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape

from app.api.deps import get_fact_query_service
from app.main import create_app
from app.schemas.facts import LIST_COLUMNS, FactListItem, FactListResponse


class FakeFactQueryService:
    def __init__(self, response: FactListResponse) -> None:
        self._response = response
        self.last_kwargs: dict[str, object] = {}

    async def list_page(self, **kwargs: object) -> FactListResponse:
        self.last_kwargs = kwargs
        return self._response


def _item(**overrides: object) -> FactListItem:
    values: dict[str, object] = {
        "corp_name": "삼호저축은행",
        "year_end": "(2025.12)",
        "rcept_dt": "2026.06.01",
        "correction_type": "최초공시",
        "rcept_no": "20260601000466",
        "dcm_no": "11411460",
        "source_report_type": "F001",
        "fs_scope": "separate",
        "hours": [{"role": "cpa", "value": 10}],
        "fetch_status": "ok",
        "extracted_at": datetime(2026, 9, 4, tzinfo=timezone.utc),
        "extractor_version": "audit_opinion.v15",
    }
    values.update(overrides)
    return FactListItem.model_validate(values)


def _app(fake: FakeFactQueryService) -> object:
    app = create_app()
    app.dependency_overrides[get_fact_query_service] = lambda: fake
    return app


def test_fact_cell_dumps_json_without_path_join() -> None:
    from app.api.facts.ui import fact_cell

    dumped = fact_cell([{"role": "cpa", "value": 10}])
    assert dumped == '{"role":"cpa","value":10}'
    assert " › " not in dumped
    assert fact_cell([]) == "—"
    assert fact_cell({}) == "—"
    assert fact_cell(None) == "—"


async def test_facts_list_shows_join_and_public_headers(client_factory) -> None:
    fake = FakeFactQueryService(
        FactListResponse(items=[_item()], next_cursor="tok")
    )
    async with client_factory(_app(fake)) as client:
        response = await client.get("/facts")
    assert response.status_code == 200
    assert "Facts · 추출 결과" in response.text
    assert 'href="/catalog"' in response.text
    assert "date_resolver" not in response.text
    for header in LIST_COLUMNS:
        assert f"<th>{header}</th>" in response.text
    assert 'href="/catalog/20260601000466"' in response.text
    assert '{"role":"cpa","value":10}' in unescape(response.text)
    assert " › " not in unescape(response.text)
    assert "다음" in response.text
    assert "tok" in response.text


async def test_facts_list_empty_is_not_404(client_factory) -> None:
    fake = FakeFactQueryService(FactListResponse(items=[]))
    async with client_factory(_app(fake)) as client:
        response = await client.get("/facts")
    assert response.status_code == 200
    assert "표시할 추출 결과가 없습니다." in response.text


async def test_facts_a001_two_rows_stay_in_order(client_factory) -> None:
    items = [
        _item(source_report_type="A001", fs_scope="separate", dcm_no="1"),
        _item(source_report_type="A001", fs_scope="consolidated", dcm_no="2"),
    ]
    fake = FakeFactQueryService(FactListResponse(items=items))
    async with client_factory(_app(fake)) as client:
        response = await client.get("/facts")
    text = response.text
    assert text.find("separate") < text.find("consolidated")


async def test_facts_list_passes_query_filters(client_factory) -> None:
    fake = FakeFactQueryService(FactListResponse(items=[]))
    async with client_factory(_app(fake)) as client:
        response = await client.get(
            "/facts", params={"corp_name": "삼호", "limit": 10}
        )
    assert response.status_code == 200
    assert fake.last_kwargs["corp_name"] == "삼호"
    assert fake.last_kwargs["limit"] == 10
```

`packages/web-api/tests/test_catalog_ui.py`의 `test_catalog_list_shows_all_disclosure_columns`에 한 줄을 추가한다:

```python
    assert 'href="/facts"' in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_facts_ui.py::test_facts_list_empty_is_not_404 -v`

Expected: FAIL — `404` (`/facts` 없음). `test_fact_cell_*`는 `ui.py`가 없어 `ImportError`.

- [ ] **Step 3: Write minimal implementation**

`packages/web-api/app/api/facts/__init__.py`: 빈 파일.

Create `packages/web-api/app/api/facts/ui.py` **전체**:

```python
"""Public 추출 결과 HTML 탐색 라우터."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import get_fact_query_service
from app.errors import BadRequest
from app.schemas.facts import LIST_COLUMNS
from app.services.fact_query_service import FactQueryService

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(prefix="/facts", tags=["Facts UI"], include_in_schema=False)


def fact_cell(value: Any) -> str:
    """facts 표 셀. JSON은 compact 한 줄, catalog path 조인을 쓰지 않는다."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        if value == [] or value == {}:
            return "—"
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = str(value)
    return text if text else "—"


def _attr(obj: Any, name: str) -> Any:
    """템플릿에서 동적 속성 조회."""
    return getattr(obj, name, None)


templates.env.globals["fact_cell"] = fact_cell
templates.env.globals["attr"] = _attr


@router.get("", response_class=HTMLResponse)
async def facts_list(
    request: Request,
    corp_code: str | None = None,
    corp_name: str | None = None,
    report_nm: str | None = None,
    report_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    service: FactQueryService = Depends(get_fact_query_service),
) -> HTMLResponse:
    """추출 문서 목록을 조인 메타 + 공개 컬럼 표로 렌더링한다."""
    cursor_error: str | None = None
    try:
        result = await service.list_page(
            corp_code=corp_code,
            corp_name=corp_name,
            report_nm=report_nm,
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            cursor=cursor,
        )
    except BadRequest as exc:
        cursor_error = str(exc)
        result = await service.list_page(
            corp_code=corp_code,
            corp_name=corp_name,
            report_nm=report_nm,
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            cursor=None,
        )
    next_href: str | None = None
    if result.next_cursor:
        params: dict[str, str | int] = {"limit": limit, "cursor": result.next_cursor}
        if corp_code:
            params["corp_code"] = corp_code
        if corp_name:
            params["corp_name"] = corp_name
        if report_nm:
            params["report_nm"] = report_nm
        if report_type:
            params["report_type"] = report_type
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        next_href = "/facts?" + urlencode(params)
    return templates.TemplateResponse(
        request,
        "facts/list.html",
        {
            "items": result.items,
            "columns": LIST_COLUMNS,
            "next_href": next_href,
            "cursor_error": cursor_error,
        },
    )
```

Create `packages/web-api/app/templates/facts/list.html` **전체**:

```jinja
{% extends "catalog/base.html" %}
{% block title %}Facts · 추출 결과{% endblock %}
{% block header %}
  <h1>Facts · 추출 결과</h1>
{% endblock %}
{% block content %}
  {% if cursor_error %}
  <p class="error">{{ cursor_error }}</p>
  {% endif %}
  <div class="table-scroll">
    <table>
      <thead>
        <tr>
          {% for col in columns %}
          <th>{{ col }}</th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for item in items %}
        <tr>
          {% for col in columns %}
          <td>
            {% if col == "rcept_no" %}
            <a href="/catalog/{{ item.rcept_no }}">{{ item.rcept_no }}</a>
            {% else %}
            {{ fact_cell(attr(item, col)) }}
            {% endif %}
          </td>
          {% endfor %}
        </tr>
        {% else %}
        <tr><td colspan="{{ columns|length }}">표시할 추출 결과가 없습니다.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% if next_href %}
  <p class="pager"><a href="{{ next_href }}">다음</a></p>
  {% endif %}
{% endblock %}
```

`packages/web-api/app/templates/catalog/base.html`의 `<header class="page-header">`를 다음으로 바꾼다:

```html
  <header class="page-header">
    <nav><a href="/catalog">Catalog</a> · <a href="/facts">Facts</a></nav>
    {% block header %}{% endblock %}
  </header>
```

`packages/web-api/app/main.py` — `from app.api.catalog import ui as catalog_ui` 옆에:

```python
from app.api.facts import ui as facts_ui
```

`app.include_router(catalog_ui.router)` **다음**:

```python
    app.include_router(facts_ui.router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_facts_ui.py tests/test_catalog_ui.py -v`

Expected: PASS

- [ ] **Step 5: Commit (초안, 사용자 요청 시에만)**

```text
git add packages/web-api/app/api/facts packages/web-api/app/templates/facts packages/web-api/app/templates/catalog/base.html packages/web-api/app/main.py packages/web-api/tests/test_facts_ui.py packages/web-api/tests/test_catalog_ui.py
git commit -m "feat: 추출 결과를 /facts 납작 표로 보여 준다"
```

---

### Task 7: README와 스펙 상태

**Files:**
- Modify: `README.md`
- Modify: `packages/web-api/README.md`
- Modify: `docs/superpowers/specs/2026-09-04-facts-html-browse-design.md`

**Interfaces:** 없음. 문서만.

- [ ] **Step 1: Update READMEs and spec status**

루트 `README.md`:

- 기본 흐름 2번을 `Catalog HTML(/catalog)·Facts HTML(/facts)` 로 고친다.
- Catalog 탐색 불릿 **다음**에 추가:

```markdown
- Facts 탐색: http://127.0.0.1:8000/facts  
  (추출된 감사 문서 1행 표, 인증 없음)
```

- Public 경로 표에 Catalog 목록 다음 행:

```markdown
| GET | `/api/v1/facts` | 감사 추출 결과 목록 (cursor) |
```

`packages/web-api/README.md` 엔드포인트 표:

- `GET /api/v1/disclosures/{rcp_no}/audit-facts` **위**에:

```markdown
| GET | `/api/v1/facts` | 감사 추출 결과 목록 (인증 없음, cursor) |
```

- `GET /catalog` **위**에:

```markdown
| GET | `/facts` | 추출 문서 납작 표 (조인 메타 + facts 공개 컬럼). `rcept_no`는 Catalog 링크 |
```

스펙 `docs/superpowers/specs/2026-09-04-facts-html-browse-design.md` 상단:

`상태: 승인 (브레인스토밍)` → `상태: 승인 (구현)`

- [ ] **Step 2: Commit (초안, 사용자 요청 시에만)**

```text
git add README.md packages/web-api/README.md docs/superpowers/specs/2026-09-04-facts-html-browse-design.md
git commit -m "docs: /facts 목록 경로를 README와 스펙에 적는다"
```

- [ ] **Step 3: Regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_facts_schema.py tests/test_fact_repository.py tests/test_fact_query_service.py tests/test_facts_api.py tests/test_facts_ui.py tests/test_catalog_ui.py -v`

Expected: PASS

---

## Spec coverage (self-review)

| Spec | Task |
|------|------|
| `GET /facts` HTML 납작 표 | 6 |
| `GET /api/v1/facts` | 5 |
| 단건 `.../audit-facts` 유지 | 5 (기존 테스트) |
| 조인 4칸 + 모델 순 공개 컬럼, JSON 조인 칸 선행 | 1, 6 |
| `date_resolver_*` 제외 | 1, 5, 6 |
| INNER JOIN, orphan 제외 | 3 |
| 정렬 dt DESC, rcept DESC, dcm ASC | 3 |
| `report_type` = `source_report_type` | 3 |
| cursor 3필드·400 | 2, 4, 5 |
| HTML 쿼리 필터, 폼 없음, «다음» | 6 |
| `fact_cell` JSON compact, path 조인 없음 | 6 |
| Catalog↔Facts 링크 | 6 |
| 빈 목록 404 아님 | 5, 6 |
| `ok` / `section_missing` / `fetch_failed` 글자 그대로 | 4 (`section_missing`), 6 (`fetch_status` 헤더) |
| README | 7 |
| 범위 밖(QA, 중첩 표, freeze, 추출 실행) | 구현하지 않음 |
