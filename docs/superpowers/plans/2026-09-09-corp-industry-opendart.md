# 회사 마스터 업종 보강 (OpenDART 기업개황) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공시 distinct `corp_code`마다 OpenDART 기업개황으로 현재 업종·식별자를 `corps`에 붙이고, Admin에서 빠진 회사만 채우는 잡을 돌린다.

**Architecture:** `disclosures`에서 고유번호를 모으고 `fetch_status=ok`인 `corps`는 건너뛴다. httpx(DART Referer 없음)로 `company.json`만 호출하고, KSIC 10차 고정 JSON으로 이름을 붙인 뒤 회사 1행을 upsert한다. 잡은 기존 `extraction_jobs`에 `extractor_id=corp_industry`로 남긴다. `/admin`에는 문서 수집 카드와 별도인 회사 단위 칸을 둔다.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2 async, httpx, Jinja2, pytest

**Spec:** `docs/superpowers/specs/2026-09-09-corp-industry-opendart-design.md`

## Global Constraints

- 주석·Docstring·로그·예외·테스트 설명은 한국어. 함수 입출력 Type Hint 필수.
- I/O(httpx, DB)는 async. KSIC 매퍼는 순수 함수.
- OpenDART는 `GET https://opendart.fss.or.kr/api/company.json`만. 재무·목록·고유번호 ZIP·DART HTML 스크래핑 없음.
- DART `Referer` 헤더를 OpenDART 클라이언트에 붙이지 않음. `dart_job_lock`에 `corp_industry`를 넣지 않음.
- `disclosures`/`entries`에 업종 컬럼을 추가하지 않음. Catalog/Facts JOIN·회사 목록 HTML 없음.
- 모드 `fill_missing`만. `ok` 행은 재조회하지 않음.
- 작업 디렉터리: `packages/web-api`. pytest: `.\.venv\Scripts\python.exe -m pytest …` (`asyncio_mode = auto`).
- git 커밋은 **사용자가 요청한 경우에만**. 아래 Commit 스텝은 메시지 초안이다.
- Windows PowerShell 커밋은 bash HEREDOC 대신 `git commit -m "한글 한 줄"`을 쓴다.

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `packages/web-api/app/data/ksic10.json` | KSIC 제10차 코드 → 이름·parent |
| `packages/web-api/app/ksic.py` | 코드표 로드, `names_for` |
| `packages/web-api/app/models/corp.py` | `corps` ORM |
| `packages/web-api/app/models/__init__.py` | `Corp` export (`create_all`이 모델을 import해야 함) |
| `packages/web-api/app/repositories/corp_repository.py` | upsert, ok 코드 집합 |
| `packages/web-api/app/repositories/disclosure_repository.py` | distinct `corp_code` |
| `packages/web-api/app/repositories/extraction_job_repository.py` | `get`, `find_latest`, `update_params` |
| `packages/web-api/app/adapters/opendart_company.py` | `company.json` 클라이언트 |
| `packages/web-api/app/services/corp_industry_service.py` | 잡·대상·upsert |
| `packages/web-api/app/schemas/corps.py` | Admin 요청/응답 |
| `packages/web-api/app/config.py` | `opendart_*` |
| `packages/web-api/app/api/deps.py` | `get_corp_industry_service` |
| `packages/web-api/app/api/admin/corps.py` | JSON Admin API |
| `packages/web-api/app/api/admin/ui.py` | HTML 시작·패널·중단 |
| `packages/web-api/app/templates/admin/index.html` | 회사 업종 칸 |
| `packages/web-api/app/templates/admin/partials/corps_panel.html` | 숫자·버튼·진행 |
| `packages/web-api/app/main.py` | OpenDART httpx, 라우터 |
| `packages/web-api/.env.example` | `OPENDART_API_KEY=` |
| `packages/web-api/README.md`, `README.md` | Admin 경로 안내 |

기존 패턴 (복제하지 말고 같은 모양으로 맞출 것):

- 잡 수명: `DateResolverService.start` / `ExtractionService.request_soft_stop` (메모리 `_stop_requested`)
- 키 없음 400: `app/api/admin/extract.py` `resolve_dates`
- HTML 폼 vs JSON: 수집은 `POST /admin/collect`(303)와 `POST /admin/catalog/extract`(202). 회사 업종도 그렇게 가른다.
- 테스트 앱: `tests/test_date_resolver.py`의 `_app_with_resolver` + `client_factory`

---

### Task 1: KSIC 매퍼와 코드표

**Files:**
- Create: `packages/web-api/app/data/ksic10.json`
- Create: `packages/web-api/app/ksic.py`
- Test: `packages/web-api/tests/test_ksic.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `class KsicNames` — `induty_name_div/group/class/subclass/item: str | None`
  - `class KsicEntry` — `name: str`, `parent: str | None`, `level: str` (`div`/`group`/`class`/`subclass`/`item`)
  - `def load_ksic_table(path: Path | None = None) -> dict[str, KsicEntry]`
  - `def names_for(code: str | None, table: dict[str, KsicEntry]) -> KsicNames`
  - `KSIC_PATH: Path` — `app/data/ksic10.json`

- [ ] **Step 1: Write the failing test**

Create `packages/web-api/tests/test_ksic.py`:

```python
"""KSIC 제10차 코드 → 계층 이름 매퍼 테스트."""

from __future__ import annotations

from app.ksic import KsicEntry, load_ksic_table, names_for


def _table() -> dict[str, KsicEntry]:
    return {
        "C": KsicEntry(name="제조업", parent=None, level="div"),
        "26": KsicEntry(
            name="전자부품, 컴퓨터, 영상, 음향 및 통신장비 제조업",
            parent="C",
            level="group",
        ),
        "264": KsicEntry(name="통신 및 방송 장비 제조업", parent="26", level="class"),
        "2642": KsicEntry(
            name="방송 및 무선 통신장비 제조업", parent="264", level="subclass"
        ),
        "26421": KsicEntry(
            name="방송장비 제조업", parent="2642", level="item"
        ),
    }


def test_names_for_class_code_fills_div_group_class_only() -> None:
    """3자리 소분류는 세·세세를 비운다."""
    names = names_for("264", _table())
    assert names.induty_name_div == "제조업"
    assert names.induty_name_group == "전자부품, 컴퓨터, 영상, 음향 및 통신장비 제조업"
    assert names.induty_name_class == "통신 및 방송 장비 제조업"
    assert names.induty_name_subclass is None
    assert names.induty_name_item is None


def test_names_for_item_code_fills_all_levels() -> None:
    """5자리 세세분류는 다섯 칸을 채운다."""
    names = names_for("26421", _table())
    assert names.induty_name_item == "방송장비 제조업"
    assert names.induty_name_subclass == "방송 및 무선 통신장비 제조업"
    assert names.induty_name_class == "통신 및 방송 장비 제조업"


def test_names_for_unknown_code_returns_all_none() -> None:
    """표에 없으면 이름은 전부 NULL이다. 접두 추정은 하지 않는다."""
    names = names_for("99999", _table())
    assert names.induty_name_div is None
    assert names.induty_name_item is None


def test_names_for_strips_whitespace_and_empty_is_blank() -> None:
    """앞뒤 공백은 제거하고, 빈 코드는 이름을 비운다."""
    assert names_for(" 264 ", _table()).induty_name_class == "통신 및 방송 장비 제조업"
    assert names_for(None, _table()).induty_name_class is None
    assert names_for("", _table()).induty_name_class is None


def test_load_ksic_table_includes_sample_264() -> None:
    """저장소 코드표에 설계 예시 264가 있다."""
    table = load_ksic_table()
    names = names_for("264", table)
    assert names.induty_name_class is not None
    assert names.induty_name_div is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ksic.py -v`

Expected: FAIL with `ModuleNotFoundError: app.ksic`

- [ ] **Step 3: Write minimal implementation**

Create `packages/web-api/app/data/ksic10.json`. 각 키는 코드, 값은 `{name, parent, level}`이다. `parent`는 없거나 빈 문자열이면 대분류. 최소로 대분류 A–U와 테스트용 `26`/`264`/`2642`/`26421`을 넣는다. 나머지 공식 코드는 같은 스키마로 더 넣어도 매퍼는 그대로다.

```json
{
  "A": {"name": "농업, 임업 및 어업", "parent": null, "level": "div"},
  "B": {"name": "광업", "parent": null, "level": "div"},
  "C": {"name": "제조업", "parent": null, "level": "div"},
  "D": {"name": "전기, 가스, 증기 및 공기조절 공급업", "parent": null, "level": "div"},
  "E": {"name": "수도, 하수 및 폐기물 처리, 원료 재생업", "parent": null, "level": "div"},
  "F": {"name": "건설업", "parent": null, "level": "div"},
  "G": {"name": "도매 및 소매업", "parent": null, "level": "div"},
  "H": {"name": "운수 및 창고업", "parent": null, "level": "div"},
  "I": {"name": "숙박 및 음식점업", "parent": null, "level": "div"},
  "J": {"name": "정보통신업", "parent": null, "level": "div"},
  "K": {"name": "금융 및 보험업", "parent": null, "level": "div"},
  "L": {"name": "부동산업", "parent": null, "level": "div"},
  "M": {"name": "전문, 과학 및 기술 서비스업", "parent": null, "level": "div"},
  "N": {"name": "사업시설 관리, 사업 지원 및 임대 서비스업", "parent": null, "level": "div"},
  "O": {"name": "공공 행정, 국방 및 사회보장 행정", "parent": null, "level": "div"},
  "P": {"name": "교육 서비스업", "parent": null, "level": "div"},
  "Q": {"name": "보건업 및 사회복지 서비스업", "parent": null, "level": "div"},
  "R": {"name": "예술, 스포츠 및 여가관련 서비스업", "parent": null, "level": "div"},
  "S": {"name": "협회 및 단체, 수리 및 기타 개인 서비스업", "parent": null, "level": "div"},
  "T": {"name": "가구 내 고용활동 및 달리 분류되지 않은 자가 소비 생산활동", "parent": null, "level": "div"},
  "U": {"name": "국제 및 외국기관", "parent": null, "level": "div"},
  "26": {
    "name": "전자부품, 컴퓨터, 영상, 음향 및 통신장비 제조업",
    "parent": "C",
    "level": "group"
  },
  "264": {"name": "통신 및 방송 장비 제조업", "parent": "26", "level": "class"},
  "2642": {"name": "방송 및 무선 통신장비 제조업", "parent": "264", "level": "subclass"},
  "26421": {"name": "방송장비 제조업", "parent": "2642", "level": "item"}
}
```

Create `packages/web-api/app/ksic.py`:

```python
"""KSIC 제10차 코드표로 OpenDART 업종코드에 이름을 붙인다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

KSIC_PATH = Path(__file__).resolve().parent / "data" / "ksic10.json"

_LEVEL_FIELD = {
    "div": "induty_name_div",
    "group": "induty_name_group",
    "class": "induty_name_class",
    "subclass": "induty_name_subclass",
    "item": "induty_name_item",
}


@dataclass(frozen=True)
class KsicEntry:
    """코드표 한 줄."""

    name: str
    parent: str | None
    level: str


@dataclass(frozen=True)
class KsicNames:
    """회사 행에 붙일 계층 이름. 없는 단계는 None."""

    induty_name_div: str | None = None
    induty_name_group: str | None = None
    induty_name_class: str | None = None
    induty_name_subclass: str | None = None
    induty_name_item: str | None = None


def load_ksic_table(path: Path | None = None) -> dict[str, KsicEntry]:
    """JSON 코드표를 읽어 코드 → 항목 사전을 만든다."""
    payload = json.loads((path or KSIC_PATH).read_text(encoding="utf-8"))
    table: dict[str, KsicEntry] = {}
    for code, raw in payload.items():
        parent = raw.get("parent")
        table[str(code)] = KsicEntry(
            name=str(raw["name"]),
            parent=str(parent) if parent else None,
            level=str(raw["level"]),
        )
    return table


def names_for(code: str | None, table: dict[str, KsicEntry]) -> KsicNames:
    """정확 일치한 코드부터 parent를 따라 이름을 채운다. 없으면 전부 None."""
    if code is None:
        return KsicNames()
    normalized = code.strip()
    if not normalized or normalized not in table:
        return KsicNames()

    values: dict[str, str | None] = {field: None for field in _LEVEL_FIELD.values()}
    current: str | None = normalized
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        entry = table.get(current)
        if entry is None:
            break
        field = _LEVEL_FIELD.get(entry.level)
        if field is not None and values[field] is None:
            values[field] = entry.name
        current = entry.parent
    return KsicNames(**values)
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ksic.py -v`

Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api/app/ksic.py packages/web-api/app/data/ksic10.json packages/web-api/tests/test_ksic.py
git commit -m "feat: KSIC 10차 코드에 계층 이름을 붙인다"
```

---

### Task 2: `corps` 모델과 스키마 생성

**Files:**
- Create: `packages/web-api/app/models/corp.py`
- Modify: `packages/web-api/app/models/__init__.py`
- Test: `packages/web-api/tests/test_ensure_schema.py`

**Interfaces:**
- Consumes: `app.models.base.Base`, `ensure_schema`/`create_all`
- Produces: `class Corp` — `__tablename__ = "corps"`, PK `corp_code: str`, 스펙 §4.1 컬럼

- [ ] **Step 1: Write the failing test**

Append to `packages/web-api/tests/test_ensure_schema.py`:

```python
async def test_ensure_schema_creates_corps_table() -> None:
    """빈 DB를 열면 corps 테이블이 생긴다."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await ensure_schema(engine)
    async with engine.begin() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'corps'"
                )
            )
        ).first()
        columns = {
            row[1]
            for row in (await connection.execute(text("PRAGMA table_info(corps)"))).fetchall()
        }
    await engine.dispose()
    assert rows is not None
    assert "corp_code" in columns
    assert "induty_code" in columns
    assert "induty_name_div" in columns
    assert "fetch_status" in columns
    assert "opendart_status" in columns
    assert "fetched_at" in columns
```

파일 상단에 `ensure_schema` import가 이미 있으면 유지한다.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ensure_schema.py::test_ensure_schema_creates_corps_table -v`

Expected: FAIL (`assert rows is not None` 또는 테이블 없음)

- [ ] **Step 3: Write minimal implementation**

Create `packages/web-api/app/models/corp.py` — `Disclosure`와 같은 `DateTime(timezone=True)`, `_now` 패턴:

```python
"""회사 마스터. OpenDART 기업개황의 현재 스냅샷만 저장한다."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Corp(Base):
    """corp_code당 현재 업종·식별자 1행."""

    __tablename__ = "corps"

    corp_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    corp_name: Mapped[str | None] = mapped_column(String(255))
    stock_name: Mapped[str | None] = mapped_column(String(255))
    stock_code: Mapped[str | None] = mapped_column(String(16))
    corp_cls: Mapped[str | None] = mapped_column(String(8))
    bizr_no: Mapped[str | None] = mapped_column(String(32))
    acc_mt: Mapped[str | None] = mapped_column(String(8))
    induty_code: Mapped[str | None] = mapped_column(String(16))
    induty_name_div: Mapped[str | None] = mapped_column(String(255))
    induty_name_group: Mapped[str | None] = mapped_column(String(255))
    induty_name_class: Mapped[str | None] = mapped_column(String(255))
    induty_name_subclass: Mapped[str | None] = mapped_column(String(255))
    induty_name_item: Mapped[str | None] = mapped_column(String(255))
    fetch_status: Mapped[str] = mapped_column(String(16), nullable=False, default="api_error")
    opendart_status: Mapped[str | None] = mapped_column(String(8))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
```

Modify `packages/web-api/app/models/__init__.py`: `from app.models.corp import Corp`를 넣고 `__all__`에 `"Corp"`를 추가한다. `app/db/session.py`가 `from app.models import ...` 또는 `Base.metadata`를 쓰려면 **반드시 Corp가 import**되어야 `create_all`이 테이블을 만든다. `session.py` 상단이 `from app.models.entry import Entry`처럼 개별 import면 `from app.models.corp import Corp`를 `session.py`에도 추가한다.

`packages/web-api/app/db/session.py`를 열어 `Base.metadata.create_all` 전에 모델 import 목록을 확인하고 `Corp`를 넣는다.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ensure_schema.py -v`

Expected: PASS (기존 테스트 + 신규)

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api/app/models/corp.py packages/web-api/app/models/__init__.py packages/web-api/app/db/session.py packages/web-api/tests/test_ensure_schema.py
git commit -m "feat: corps 회사 마스터 테이블을 만든다"
```

---

### Task 3: 대상 회사 조회와 upsert

**Files:**
- Create: `packages/web-api/app/repositories/corp_repository.py`
- Modify: `packages/web-api/app/repositories/disclosure_repository.py`
- Modify: `packages/web-api/app/repositories/extraction_job_repository.py`
- Test: `packages/web-api/tests/test_corp_repository.py`

**Interfaces:**
- Consumes: `Corp`, `Disclosure`, `ExtractionJob`
- Produces:
  - `DisclosureRepository.list_distinct_corp_codes() -> list[str]`
  - `CorpRepository.upsert(corp: Corp) -> None`
  - `CorpRepository.list_ok_codes() -> set[str]`
  - `CorpRepository.count_ok() -> int`
  - `ExtractionJobRepository.get(job_id: str) -> ExtractionJob | None`
  - `ExtractionJobRepository.find_latest(extractor_id: str) -> ExtractionJob | None`
  - `ExtractionJobRepository.update_params(job_id: str, params: dict[str, Any]) -> None`

- [ ] **Step 1: Write the failing test**

Create `packages/web-api/tests/test_corp_repository.py`:

```python
"""회사 마스터 대상 집합과 upsert 테스트."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.models.corp import Corp
from app.models.disclosure import Disclosure
from app.models.extraction_job import ExtractionJob
from app.repositories.corp_repository import CorpRepository
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.extraction_job_repository import ExtractionJobRepository


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def _disc(rcept_no: str, corp_code: str | None) -> Disclosure:
    return Disclosure(
        rcept_no=rcept_no,
        corp_code=corp_code,
        corp_name="회사",
        report_nm="감사보고서",
        report_type="F001",
        rcept_dt="20200331",
        entry_count=1,
    )


async def test_list_distinct_corp_codes_skips_blank_and_dedupes(
    sessionmaker_fixture,
) -> None:
    """NULL·빈 문자열을 빼고 고유번호만 모은다."""
    async with sessionmaker_fixture() as session:
        session.add_all(
            [
                _disc("a", "00126380"),
                _disc("b", "00126380"),
                _disc("c", ""),
                _disc("d", None),
                _disc("e", "00401731"),
            ]
        )
        await session.commit()
        codes = await DisclosureRepository(session).list_distinct_corp_codes()
    assert codes == ["00126380", "00401731"]


async def test_list_ok_codes_and_upsert(sessionmaker_fixture) -> None:
    """ok만 건너뛸 집합에 들어가고, 같은 PK는 덮어쓴다."""
    async with sessionmaker_fixture() as session:
        repos = CorpRepository(session)
        await repos.upsert(
            Corp(
                corp_code="00126380",
                fetch_status="ok",
                induty_code="264",
                fetched_at=datetime.now(timezone.utc),
            )
        )
        await repos.upsert(
            Corp(
                corp_code="00126380",
                fetch_status="ok",
                induty_code="265",
                fetched_at=datetime.now(timezone.utc),
            )
        )
        await repos.upsert(
            Corp(corp_code="00401731", fetch_status="not_found", opendart_status="013")
        )
        await session.commit()
        ok = await repos.list_ok_codes()
        assert ok == {"00126380"}
        assert await repos.count_ok() == 1
        loaded = await session.get(Corp, "00126380")
        assert loaded is not None
        assert loaded.induty_code == "265"


async def test_extraction_job_find_latest_and_update_params(
    sessionmaker_fixture,
) -> None:
    """extractor별 최신 잡과 JSON params 갱신."""
    async with sessionmaker_fixture() as session:
        jobs = ExtractionJobRepository(session)
        await jobs.create("old", "corp_industry", {"processed_count": 0})
        await jobs.create("new", "corp_industry", {"processed_count": 0})
        await jobs.create("other", "audit_opinion", {})
        await session.commit()
        latest = await jobs.find_latest("corp_industry")
        assert latest is not None
        assert latest.job_id == "new"
        await jobs.update_params("new", {"processed_count": 3, "target_count": 10})
        await session.commit()
        loaded = await jobs.get("new")
        assert loaded is not None
        assert loaded.params["processed_count"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corp_repository.py -v`

Expected: FAIL (`CorpRepository` 또는 메서드 없음)

- [ ] **Step 3: Write minimal implementation**

`disclosure_repository.py`에:

```python
async def list_distinct_corp_codes(self) -> list[str]:
    """공시에 나온 비어 있지 않은 고유번호를 정렬해 반환한다."""
    statement = (
        select(Disclosure.corp_code)
        .where(Disclosure.corp_code.is_not(None))
        .where(Disclosure.corp_code != "")
        .distinct()
        .order_by(Disclosure.corp_code)
    )
    result = await self._session.execute(statement)
    return [row[0] for row in result.all() if row[0]]
```

Create `packages/web-api/app/repositories/corp_repository.py`:

```python
"""회사 마스터 영속화."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corp import Corp


class CorpRepository:
    """corps upsert와 ok 집합."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, corp: Corp) -> None:
        """corp_code 기준으로 병합 저장한다."""
        await self._session.merge(corp)

    async def list_ok_codes(self) -> set[str]:
        """fetch_status=ok인 고유번호."""
        statement = select(Corp.corp_code).where(Corp.fetch_status == "ok")
        result = await self._session.execute(statement)
        return {row[0] for row in result.all()}

    async def count_ok(self) -> int:
        """ok 행 수."""
        statement = select(func.count()).select_from(Corp).where(Corp.fetch_status == "ok")
        result = await self._session.execute(statement)
        return int(result.scalar_one())
```

`extraction_job_repository.py`에 (`from sqlalchemy.orm.attributes import flag_modified` 추가):

```python
async def get(self, job_id: str) -> ExtractionJob | None:
    """작업 단건. 없으면 None."""
    return await self._session.get(ExtractionJob, job_id)

async def find_latest(self, extractor_id: str) -> ExtractionJob | None:
    """해당 추출기의 가장 최근 잡."""
    statement = (
        select(ExtractionJob)
        .where(ExtractionJob.extractor_id == extractor_id)
        .order_by(ExtractionJob.created_at.desc())
        .limit(1)
    )
    result = await self._session.execute(statement)
    return result.scalars().first()

async def update_params(self, job_id: str, params: dict[str, Any]) -> None:
    """잡 params JSON을 통째로 교체한다."""
    job = await self._require(job_id)
    job.params = params
    flag_modified(job, "params")
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corp_repository.py tests/test_job_repository.py tests/test_audit_report_fact_repository.py -v`

Expected: PASS (`find_any_active` 등 기존 추출 잡 테스트 회귀 포함)

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api/app/repositories/corp_repository.py packages/web-api/app/repositories/disclosure_repository.py packages/web-api/app/repositories/extraction_job_repository.py packages/web-api/tests/test_corp_repository.py
git commit -m "feat: 공시 고유번호와 corps upsert를 조회한다"
```

---

### Task 4: OpenDART 기업개황 클라이언트

**Files:**
- Create: `packages/web-api/app/adapters/opendart_company.py`
- Test: `packages/web-api/tests/test_opendart_company.py`

**Interfaces:**
- Consumes: `httpx.AsyncClient` (DART Referer 없는 인스턴스)
- Produces:
  - `COMPANY_URL = "https://opendart.fss.or.kr/api/company.json"`
  - `class CompanyOverview` — `status: str`, `message: str`, `corp_name/stock_name/stock_code/corp_cls/bizr_no/acc_mt/induty_code: str | None`
  - `class OpenDartHttpError(Exception)` — 재시도 소진
  - `class OpenDartCompanyClient`
    - `__init__(self, client: httpx.AsyncClient, *, timeout_seconds: float, max_retries: int)`
    - `async def fetch(self, corp_code: str, api_key: str) -> CompanyOverview`

- [ ] **Step 1: Write the failing test**

Create `packages/web-api/tests/test_opendart_company.py`:

```python
"""OpenDART company.json 클라이언트 테스트. 실호출 없음."""

from __future__ import annotations

import httpx
import pytest

from app.adapters.opendart_company import (
    COMPANY_URL,
    OpenDartCompanyClient,
    OpenDartHttpError,
)


def _client(handler: object, max_retries: int = 0) -> OpenDartCompanyClient:
    transport = httpx.MockTransport(handler)
    return OpenDartCompanyClient(
        httpx.AsyncClient(transport=transport),
        timeout_seconds=1.0,
        max_retries=max_retries,
    )


async def test_fetch_maps_flat_000() -> None:
    """최상위 status=000과 개황 필드를 매핑한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(COMPANY_URL)
        assert request.url.params["crtfc_key"] == "key"
        assert request.url.params["corp_code"] == "00126380"
        return httpx.Response(
            200,
            json={
                "status": "000",
                "message": "정상",
                "corp_name": "삼성전자",
                "stock_name": "삼성전자",
                "stock_code": "005930",
                "corp_cls": "Y",
                "bizr_no": "1248100998",
                "acc_mt": "12",
                "induty_code": "264",
            },
        )

    overview = await _client(handler).fetch("00126380", "key")
    assert overview.status == "000"
    assert overview.corp_name == "삼성전자"
    assert overview.stock_code == "005930"
    assert overview.induty_code == "264"


async def test_fetch_reads_status_under_result() -> None:
    """result.status도 읽는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"result": {"status": "013", "message": "조회된 데이타가 없습니다."}},
        )

    overview = await _client(handler).fetch("00000000", "key")
    assert overview.status == "013"
    assert overview.induty_code is None


async def test_fetch_blank_stock_code_becomes_none() -> None:
    """비상장 빈 종목코드는 None이다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "000", "message": "정상", "stock_code": "  ", "induty_code": ""},
        )

    overview = await _client(handler).fetch("001", "key")
    assert overview.stock_code is None
    assert overview.induty_code is None


async def test_fetch_retries_then_raises() -> None:
    """HTTP 오류는 재시도 후 OpenDartHttpError."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(500, text="err")

    with pytest.raises(OpenDartHttpError):
        await _client(handler, max_retries=1).fetch("00126380", "key")
    assert attempts["n"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_opendart_company.py -v`

Expected: FAIL (`opendart_company` 없음)

- [ ] **Step 3: Write minimal implementation**

Create `packages/web-api/app/adapters/opendart_company.py`. UTF-8 JSON만 다룬다(EUC-KR 디코더 재사용 금지). 재시도는 `DartHttpClient`처럼 `max_retries + 1`회, 백오프 0.5s×2^attempt. 빈 문자열 필드는 `None`. `status`는 `payload["status"]`가 있으면 그걸 쓰고, 없으면 `payload["result"]["status"]`. 개황 필드는 최상위를 먼저 보고, 없으면 `result` 딕셔너리에서 읽는다.

```python
"""OpenDART 기업개황(company.json) 클라이언트."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

COMPANY_URL = "https://opendart.fss.or.kr/api/company.json"
_EMPTY = frozenset({"", " "})


class OpenDartHttpError(Exception):
    """재시도 후에도 기업개황 HTTP가 실패한 경우."""


@dataclass(frozen=True)
class CompanyOverview:
    """기업개황 한 건. API status는 원문 코드."""

    status: str
    message: str
    corp_name: str | None = None
    stock_name: str | None = None
    stock_code: str | None = None
    corp_cls: str | None = None
    bizr_no: str | None = None
    acc_mt: str | None = None
    induty_code: str | None = None


def _blank_to_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_company_payload(payload: dict[str, object]) -> CompanyOverview:
    """최상위 또는 result 아래 status·필드를 정규화한다."""
    nested = payload.get("result")
    body: dict[str, object] = payload
    if isinstance(nested, dict):
        status = str(payload.get("status") or nested.get("status") or "")
        message = str(payload.get("message") or nested.get("message") or "")
        if "corp_name" not in payload and "induty_code" not in payload:
            body = nested
    else:
        status = str(payload.get("status") or "")
        message = str(payload.get("message") or "")
    return CompanyOverview(
        status=status,
        message=message,
        corp_name=_blank_to_none(body.get("corp_name")),
        stock_name=_blank_to_none(body.get("stock_name")),
        stock_code=_blank_to_none(body.get("stock_code")),
        corp_cls=_blank_to_none(body.get("corp_cls")),
        bizr_no=_blank_to_none(body.get("bizr_no")),
        acc_mt=_blank_to_none(body.get("acc_mt")),
        induty_code=_blank_to_none(body.get("induty_code")),
    )


class OpenDartCompanyClient:
    """인증키와 고유번호로 기업개황 JSON을 가져온다."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds

    async def fetch(self, corp_code: str, api_key: str) -> CompanyOverview:
        """company.json 1건. HTTP 실패만 재시도한다."""
        last_reason = "알 수 없는 오류"
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(
                    COMPANY_URL,
                    params={"crtfc_key": api_key, "corp_code": corp_code},
                    timeout=self._timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise OpenDartHttpError("기업개황 응답이 객체가 아닙니다.")
                return parse_company_payload(payload)
            except (httpx.HTTPError, ValueError, OpenDartHttpError) as exc:
                last_reason = str(exc)
                if attempt >= self._max_retries:
                    break
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
        raise OpenDartHttpError(
            f"기업개황을 가져오지 못했습니다({corp_code}): {last_reason}"
        )
```

`parse_company_payload`의 nested 분기는 테스트 `result.status`만 있는 경우를 통과해야 한다.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_opendart_company.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api/app/adapters/opendart_company.py packages/web-api/tests/test_opendart_company.py
git commit -m "feat: OpenDART 기업개황 JSON 클라이언트를 추가한다"
```

---

### Task 5: CorpIndustryService 잡

**Files:**
- Create: `packages/web-api/app/services/corp_industry_service.py`
- Modify: `packages/web-api/app/config.py`
- Modify: `packages/web-api/.env.example`
- Test: `packages/web-api/tests/test_corp_industry_service.py`

**Interfaces:**
- Consumes: Task 1–4, `ExtractionJobRepository`, `CatalogConflict`, `CatalogNotFound`, `BadRequest`
- Produces:
  - `CORP_INDUSTRY_EXTRACTOR_ID = "corp_industry"`
  - `FILL_MISSING_MODE = "fill_missing"`
  - `FATAL_OPENDART_STATUSES = frozenset({"010", "011", "012", "020", "800", "901"})`
  - `STALE_RUNNING_SECONDS = 3600` (`dart_job_lock`과 동일 숫자, 이 추출기만)
  - `class CorpIndustrySummary` — `disclosure_corps: int`, `ok_count: int`, `remaining_count: int`
  - `class CorpIndustryService`
    - `__init__(self, sessionmaker, client: OpenDartCompanyClient, ksic: dict[str, KsicEntry], *, api_key: str, concurrency: int = 2)`
    - `async def start(self) -> str`
    - `async def run_job(self, job_id: str) -> None`
    - `async def request_soft_stop(self, job_id: str) -> None`
    - `async def force_finish(self, job_id: str) -> None`
    - `async def get_status(self, job_id: str | None) -> tuple[ExtractionJob, list[ExtractionJobLog]]` — `job_id` None이면 `find_latest`; 없으면 `CatalogNotFound`. 로그는 `recent_logs` 최신순
    - `async def summarize(self) -> CorpIndustrySummary`
  - Settings: `opendart_api_key: str = ""`, `opendart_concurrency: int = 2`, `opendart_timeout_seconds: float = 15.0`, `opendart_max_retries: int = 2`

`start` 규칙:

1. `api_key`가 빈 문자열이면 `BadRequest("OpenDART 인증키가 없습니다. OPENDART_API_KEY를 설정한 뒤 다시 시작해 주세요.")` — **잡 행을 만들지 않음**.
2. `find_any_active(extractor_id=corp_industry)`가 있고 stale이면 `failed`로 마감한 뒤 진행. stale이 아니면 `CatalogConflict("회사 업종 작업이 이미 진행 중입니다. 현재 작업({id[:8]} · {status})이 끝난 뒤에 다시 시작해 주세요.")`.
3. 카탈로그/`audit_opinion` running은 무시.
4. `create(..., mode="fill_missing")`.

`run_job` 규칙:

- 대상 = distinct codes − ok codes. 0건이면 `succeeded`.
- `params = {target_count, processed_count: 0}` 후 회사마다 fetch → `Corp` 조립 → upsert → `processed_count += 1` → 로그 `"{code} ok · {induty_code} {class or ''}"`.
- `OpenDartHttpError` → `fetch_status=api_error`, 계속.
- status `013` → `not_found`, 계속.
- status `000` → `ok` (업종 없어도 ok, KSIC 미적중도 ok).
- status in FATAL → 사용자 메시지: `020`은 `"OpenDART 요청 한도를 넘었습니다. 이미 채운 회사는 유지됩니다. 다음 날 다시 실행해 주세요."`, 키/IP는 `"OpenDART 인증키 또는 접근 권한을 확인해 주세요."`, `800`은 `"OpenDART가 점검 중입니다. 이미 채운 회사는 유지됩니다."` — 잡 `failed`, 나머지 회사는 호출하지 않음.
- 그 외 status → `api_error`, 계속.
- 다음 회사 **시작 전** `_stop_requested`면 `partial`.
- `concurrency`는 `asyncio.Semaphore`. 중단 후에는 새 태스크를 넣지 않고 진행 중만 끝낸다.

`Corp` 조립 시 `fetched_at=datetime.now(timezone.utc)`, KSIC `names_for(overview.induty_code, ksic)`.

- [ ] **Step 1: Write the failing test**

Create `packages/web-api/tests/test_corp_industry_service.py`. Fake client:

```python
"""회사 업종 잡 오케스트레이션 테스트."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.adapters.opendart_company import CompanyOverview, OpenDartHttpError
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import BadRequest, CatalogConflict
from app.ksic import KsicEntry
from app.models.corp import Corp
from app.models.disclosure import Disclosure
from app.models.extraction_job import ExtractionJob
from app.repositories.extraction_job_repository import ExtractionJobRepository
from app.repositories.job_repository import JobRepository
from app.services.corp_industry_service import (
    CORP_INDUSTRY_EXTRACTOR_ID,
    CorpIndustryService,
)


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


KSIC = {
    "C": KsicEntry(name="제조업", parent=None, level="div"),
    "26": KsicEntry(name="전자부품", parent="C", level="group"),
    "264": KsicEntry(name="통신장비", parent="26", level="class"),
}


@dataclass
class FakeClient:
    by_code: dict[str, CompanyOverview | Exception]

    async def fetch(self, corp_code: str, api_key: str) -> CompanyOverview:
        item = self.by_code[corp_code]
        if isinstance(item, Exception):
            raise item
        return item


def _disc(rcept_no: str, corp_code: str) -> Disclosure:
    return Disclosure(
        rcept_no=rcept_no,
        corp_code=corp_code,
        corp_name="회사",
        report_nm="감사보고서",
        report_type="F001",
        rcept_dt="20200331",
        entry_count=1,
    )


def _svc(sessionmaker, client: FakeClient, api_key: str = "key") -> CorpIndustryService:
    return CorpIndustryService(
        sessionmaker, client, KSIC, api_key=api_key, concurrency=1
    )


async def test_start_rejects_missing_api_key(sessionmaker_fixture) -> None:
    service = _svc(sessionmaker_fixture, FakeClient({}), api_key="")
    with pytest.raises(BadRequest, match="인증키"):
        await service.start()
    async with sessionmaker_fixture() as session:
        assert await ExtractionJobRepository(session).find_latest(
            CORP_INDUSTRY_EXTRACTOR_ID
        ) is None


async def test_start_rejects_duplicate_active_job(sessionmaker_fixture) -> None:
    service = _svc(sessionmaker_fixture, FakeClient({}))
    first = await service.start()
    async with sessionmaker_fixture() as session:
        await ExtractionJobRepository(session).set_status(first, "running")
        await session.commit()
    with pytest.raises(CatalogConflict, match="회사 업종"):
        await service.start()


async def test_start_ignores_catalog_and_audit_locks(sessionmaker_fixture) -> None:
    """수집·감사 추출이 돌아도 회사 업종은 시작한다."""
    async with sessionmaker_fixture() as session:
        await JobRepository(session).create(
            "cat-1", {"report_type": "F001"}, "k", mode="collect"
        )
        await ExtractionJobRepository(session).create(
            "ext-1", "audit_opinion", {}, mode="extract"
        )
        await ExtractionJobRepository(session).set_status("ext-1", "running")
        await session.commit()
    service = _svc(sessionmaker_fixture, FakeClient({}))
    job_id = await service.start()
    assert job_id


async def test_run_skips_ok_and_fills_missing(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all([_disc("a", "00126380"), _disc("b", "00401731")])
        session.add(Corp(corp_code="00126380", fetch_status="ok", induty_code="264"))
        await session.commit()
    client = FakeClient(
        {
            "00401731": CompanyOverview(
                status="000",
                message="정상",
                corp_name="SK하이닉스",
                stock_code="000660",
                corp_cls="Y",
                induty_code="264",
            )
        }
    )
    service = _svc(sessionmaker_fixture, client)
    job_id = await service.start()
    await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        sk = await session.get(Corp, "00401731")
        samsung = await session.get(Corp, "00126380")
        job = await session.get(ExtractionJob, job_id)
    assert sk is not None
    assert sk.fetch_status == "ok"
    assert sk.induty_name_class == "통신장비"
    assert sk.induty_name_div == "제조업"
    assert samsung is not None
    assert samsung.induty_code == "264"
    assert job is not None
    assert job.status == "succeeded"
    assert job.params["target_count"] == 1
    assert job.params["processed_count"] == 1
    # 00126380은 FakeClient에 없다. 스킵되지 않으면 KeyError로 실패한다.


async def test_run_succeeds_when_target_empty(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_disc("a", "00126380"))
        session.add(Corp(corp_code="00126380", fetch_status="ok"))
        await session.commit()
    service = _svc(sessionmaker_fixture, FakeClient({}))
    job_id = await service.start()
    await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        job = await session.get(ExtractionJob, job_id)
    assert job is not None
    assert job.status == "succeeded"


async def test_run_stops_on_quota(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all([_disc("a", "001"), _disc("b", "002")])
        await session.commit()
    client = FakeClient(
        {
            "001": CompanyOverview(status="000", message="정상", induty_code="264"),
            "002": CompanyOverview(status="020", message="요청 제한"),
        }
    )
    service = _svc(sessionmaker_fixture, client)
    job_id = await service.start()
    await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        job = await session.get(ExtractionJob, job_id)
        one = await session.get(Corp, "001")
        two = await session.get(Corp, "002")
    assert job is not None
    assert job.status == "failed"
    assert "한도" in (job.error_message or "")
    assert one is not None and one.fetch_status == "ok"
    assert two is None


async def test_run_http_error_continues(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all([_disc("a", "001"), _disc("b", "002")])
        await session.commit()
    client = FakeClient(
        {
            "001": OpenDartHttpError("timeout"),
            "002": CompanyOverview(status="013", message="없음"),
        }
    )
    service = _svc(sessionmaker_fixture, client)
    job_id = await service.start()
    await service.run_job(job_id)
    async with sessionmaker_fixture() as session:
        one = await session.get(Corp, "001")
        two = await session.get(Corp, "002")
        job = await session.get(ExtractionJob, job_id)
    assert one is not None and one.fetch_status == "api_error"
    assert two is not None and two.fetch_status == "not_found"
    assert job is not None
    assert job.status == "succeeded"


async def test_summarize_counts(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all([_disc("a", "001"), _disc("b", "001"), _disc("c", "002")])
        session.add(Corp(corp_code="001", fetch_status="ok"))
        await session.commit()
    summary = await _svc(sessionmaker_fixture, FakeClient({})).summarize()
    assert summary.disclosure_corps == 2
    assert summary.ok_count == 1
    assert summary.remaining_count == 1
```

`test_run_skips_ok`에서 `00126380`이 fake에 없으면 호출 시 KeyError가 난다. 스킵이 동작하면 통과한다. `00401731`만 fetch한다.

`test_run_stops_on_quota`는 concurrency=1이고 코드 정렬이 `001` 다음 `002`이므로 한도 전에 1건이 저장된다. `002`는 FATAL이라 행을 남기지 않는다.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corp_industry_service.py -v`

Expected: FAIL (`corp_industry_service` 없음)

- [ ] **Step 3: Write minimal implementation**

`config.py`의 `Settings`에 네 필드를 추가한다. `.env.example`에 다음을 붙인다:

```
# OpenDART 기업개황 (비우면 회사 업종 잡을 시작하지 않는다)
OPENDART_API_KEY=
OPENDART_CONCURRENCY=2
OPENDART_TIMEOUT_SECONDS=15
OPENDART_MAX_RETRIES=2
```

`corp_industry_service.py`는 `DateResolverService`처럼 세션을 짧게 열고 커밋한다. 회사 루프는 정렬된 `missing` 리스트. Semaphore와 함께 `processed`는 코루틴 락으로 올린다.

치명 상태 분기 예:

```python
if overview.status in FATAL_OPENDART_STATUSES:
    raise OpenDartFatalError(overview.status, _fatal_message(overview.status))
```

`run_job`의 `except OpenDartFatalError`에서 `set_status(..., "failed", error_message=str(exc))`. 일반 `Exception`은 로그 후 `failed`. HTTP/013/기타는 회사 단위.

소프트 스톱: `ExtractionService.request_soft_stop`과 같이 `_stop_requested: set[str]`, 로그 한국어 `"중단 요청을 받았습니다. 진행 중인 회사까지만 처리합니다."`.

강제 종료: 추출과 같이 active면 `partial`, `"운영자가 작업을 강제 종료했습니다."`.

`get_status(None)` → `find_latest`; 없으면 `CatalogNotFound("회사 업종 작업을 찾을 수 없습니다.")`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corp_industry_service.py tests/test_extraction_service.py::test_start_raises_when_audit_extraction_running -v`

Expected: PASS. 기존 추출 잠금 테스트가 깨지면 `dart_job_lock`을 수정하지 말고 서비스가 그 함수를 **호출하지 않는지** 확인한다.

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api/app/services/corp_industry_service.py packages/web-api/app/config.py packages/web-api/.env.example packages/web-api/tests/test_corp_industry_service.py
git commit -m "feat: 빠진 회사만 OpenDART 개황으로 채운다"
```

---

### Task 6: Admin JSON API

**Files:**
- Create: `packages/web-api/app/schemas/corps.py`
- Create: `packages/web-api/app/api/admin/corps.py`
- Modify: `packages/web-api/app/api/deps.py`
- Modify: `packages/web-api/app/main.py`
- Test: `packages/web-api/tests/test_corps_admin_api.py`

**Interfaces:**
- Consumes: `CorpIndustryService`, `Settings.opendart_api_key`
- Produces:
  - `get_corp_industry_service(request) -> CorpIndustryService` — `app.state.corp_industry_service`에 캐시. 클라이언트는 `request.app.state.opendart_http_client` (없으면 Referer 없는 `httpx.AsyncClient()`를 그 요청에서만 만들지 말고, Task 6에서 lifespan에 붙인다).
  - `POST /admin/corps/enrich` → 202 `{job_id, status: pending, mode: fill_missing}`
  - `GET /admin/corps/status?job_id=` (job_id 생략 가능)
  - `POST /admin/corps/jobs/{job_id}/soft-stop` → 202
  - `POST /admin/corps/jobs/{job_id}/force-finish` → 202
  - `GET /admin/corps/summary`

라우터: `APIRouter(prefix="/admin/corps", tags=["Admin"], dependencies=[Depends(require_admin)])`.

키 검사는 `extract.resolve_dates`처럼 라우터에서 `BadRequest`. 서비스 `start`도 이중 검사해도 된다.

`main.py` `lifespan`:

```python
opendart_http_client = httpx.AsyncClient(follow_redirects=True)
app.state.opendart_http_client = opendart_http_client
```

`finally`에서 `await opendart_http_client.aclose()`. DART `http_client`와 공유하지 않는다.

`create_app`에 `app.include_router(admin_corps.router)`.

- [ ] **Step 1: Write the failing test**

Create `packages/web-api/tests/test_corps_admin_api.py`. `tests/test_date_resolver.py`의 `TOKEN_HEADER`와 `client_factory`를 재사용하려면 그 픽스처가 있는 모듈에서 import하지 말고, `test_extract_admin_api.py`의 `TOKEN_HEADER = {"X-Admin-Token": "dev-admin-token"}`과 `client_factory`를 이 파일에 같은 패턴으로 둔다.

`test_extract_admin_api.py` 상단의 `client_factory` 정의를 복사한다 (httpx ASGI). Fake 서비스:

```python
class FakeCorpService:
    def __init__(self) -> None:
        self.started = 0
        self.executed: list[str] = []

    async def start(self) -> str:
        self.started += 1
        return "job-corps-1"

    async def run_job(self, job_id: str) -> None:
        self.executed.append(job_id)
```

테스트:

- `POST /admin/corps/enrich` 토큰 없음 → 401
- 키 빈 Settings → 400, `started == 0`
- 키 있음 → 202, `job_id`, `run_job` 호출
- Fake `start`가 `CatalogConflict` → 409, 본문에 `진행`
- `GET /admin/corps/summary`는 실제 메모리 앱으로 `disclosure_corps` 숫자 (override 없이 sessionmaker + seed). 요약만 서비스 실구현을 써도 되고, Fake `summarize`를 둬도 된다. **실구현 요약을 쓰려면** `memory_app`에 `CorpIndustryService`를 붙인다.

요약 테스트는 Fake:

```python
async def summarize(self):
    from app.services.corp_industry_service import CorpIndustrySummary
    return CorpIndustrySummary(disclosure_corps=3, ok_count=1, remaining_count=2)
```

`GET /admin/corps/summary` → `{"disclosure_corps": 3, "ok_count": 1, "remaining_count": 2}`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corps_admin_api.py -v`

Expected: FAIL (라우터 없음)

- [ ] **Step 3: Write minimal implementation**

`schemas/corps.py`:

```python
class CorpEnrichResponse(BaseModel):
    job_id: str
    status: str = "pending"
    mode: str = "fill_missing"

class CorpSummaryResponse(BaseModel):
    disclosure_corps: int
    ok_count: int
    remaining_count: int

class CorpJobStatusResponse(BaseModel):
    job_id: str
    status: str
    mode: str = "fill_missing"
    params: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stop_requested: bool = False
    logs: list[JobLogItem] = Field(default_factory=list)
```

`get_status`는 잡 ORM을 이 스키마로 변환. `stop_requested`는 `job_id in service._stop_requested`.

`deps.get_corp_industry_service`: `OpenDartCompanyClient(request.app.state.opendart_http_client, timeout_seconds=settings.opendart_timeout_seconds, max_retries=settings.opendart_max_retries)`, `load_ksic_table()`, `CorpIndustryService(sessionmaker, client, table, api_key=settings.opendart_api_key, concurrency=settings.opendart_concurrency)`. 캐시는 `app.state.corp_industry_service`. **테스트가 서비스를 override하면 캐시를 우회한다.**

라우터 `enrich`:

```python
if not settings.opendart_api_key:
    raise BadRequest(
        "OpenDART 인증키가 없습니다. OPENDART_API_KEY를 설정한 뒤 다시 시작해 주세요."
    )
job_id = await service.start()
background_tasks.add_task(service.run_job, job_id)
return CorpEnrichResponse(job_id=job_id)
```

테스트에서 `create_app()` + override 시 lifespan이 안 돌면 `opendart_http_client`가 없을 수 있다. Fake 서비스 override만 쓰는 테스트는 클라이언트가 필요 없다. lifespan 없이 실서비스를 붙일 때는 `app.state.opendart_http_client = httpx.AsyncClient()`를 테스트가 넣는다.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corps_admin_api.py tests/test_extract_admin_api.py tests/test_date_resolver.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api/app/schemas/corps.py packages/web-api/app/api/admin/corps.py packages/web-api/app/api/deps.py packages/web-api/app/main.py packages/web-api/tests/test_corps_admin_api.py
git commit -m "feat: 회사 업종 Admin JSON API를 연다"
```

---

### Task 7: Admin HTML 회사 업종 칸

**Files:**
- Create: `packages/web-api/app/templates/admin/partials/corps_panel.html`
- Modify: `packages/web-api/app/templates/admin/index.html`
- Modify: `packages/web-api/app/api/admin/ui.py`
- Test: `packages/web-api/tests/test_admin_ui.py` (또는 `tests/test_corps_admin_ui.py`)

**Interfaces:**
- Consumes: `CorpIndustryService.summarize`, `get_status`, `start`, `request_soft_stop`, `force_finish`
- Produces:
  - `GET /admin/corps-panel` — HTMX 5초, 토큰 쿠키
  - `POST /admin/corps/start` — 폼, 303 `/admin` (JSON `/admin/corps/enrich`와 경로를 분리)
  - `POST /admin/corps/jobs/{job_id}/stop` — 303 (HTML). JSON soft-stop은 Task 6 경로 유지
  - `POST /admin/corps/jobs/{job_id}/finish` — 303

화면 문구 (한국어):

- 제목 `회사 업종`
- `공시 회사 {n} · 채움(ok) {ok} · 남음 {remaining}`
- 버튼 `빠진 회사 채우기`
- 키 없음: 버튼 disabled, `OpenDART 인증키가 없습니다.`
- 잡 진행 중: 버튼 disabled, `회사 업종 작업이 진행 중입니다.`
- 진행: `{status_label} · 처리 {processed} / 대상 {target}` (params 기본 0)
- 최근 로그 한 줄
- 소프트 스톱 / 강제 종료 버튼 (active일 때만)

`index.html` 수집 폼과 로그 **사이**:

```html
    <h3>회사 업종</h3>
    <div hx-get="/admin/corps-panel"
         hx-trigger="every 5s"
         hx-swap="innerHTML">
      {% include "admin/partials/corps_panel.html" %}
    </div>
```

대시보드 GET도 패널 컨텍스트(`corps_summary`, `corps_job`, `opendart_ready`)를 넣어야 첫 페인트에 include가 비지 않는다. `index` 핸들러에서 `summarize()`를 호출한다. 잡이 없으면 `corps_job is none`.

키 검사는 `settings.opendart_api_key`가 비어 있지 않음. 진행 중은 `corps_job.status in ("pending", "running")`.

- [ ] **Step 1: Write the failing test**

`test_admin_ui.py`에 Fake catalog가 이미 있다. 회사 패널은 **별도 파일** `tests/test_corps_admin_ui.py`로 고립한다. Fake `CorpIndustryService` + `get_settings_dep` + `get_corp_industry_service` override. `GET /admin` (쿠키 토큰) 본문에 `회사 업종`, `빠진 회사 채우기`가 있다. `GET /admin/corps-panel`에도 `공시 회사`가 있다. 키 없으면 `disabled`와 `인증키`. `POST /admin/corps/start` → 303, fake `started == 1`.

토큰 쿠키: `test_admin_ui.py`가 쓰는 로그인 흐름을 따른다 (`ADMIN_TOKEN` 폼 또는 쿠키 `admin_token=dev-admin-token`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corps_admin_ui.py -v`

Expected: FAIL (`corps-panel` 없음)

- [ ] **Step 3: Write minimal implementation**

`corps_panel.html`은 `job_card.html` 칩 클래스를 재사용해도 된다. 수집 카드 마크업을 복사하지 말고 **회사 수 전용** 마크업을 둔다. 진행 바는 `target_count`가 있을 때만.

`ui.py` 대시보드 컨텍스트에 패널 변수를 넣고, 토큰 없는 요청은 기존처럼 토큰 페이지.

HTML `start`는 JSON과 같이 키 없으면 리다이렉트 후 배너 대신 패널의 disabled로 충분하다. 키가 없는데 POST가 오면 `BadRequest`가 JSON으로 나갈 수 있으니, HTML 핸들러는 키 없으면 303 `/admin`만 한다 (잡 생성 없음).

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corps_admin_ui.py tests/test_admin_ui.py -v`

Expected: PASS. `/admin` 스모크가 깨지면 include 컨텍스트 누락을 고친다.

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api/app/templates/admin/partials/corps_panel.html packages/web-api/app/templates/admin/index.html packages/web-api/app/api/admin/ui.py packages/web-api/tests/test_corps_admin_ui.py
git commit -m "feat: Admin에 회사 업종 칸을 둔다"
```

---

### Task 8: README와 스펙 상태

**Files:**
- Modify: `packages/web-api/README.md`
- Modify: `README.md` (Admin 한 줄이면)
- Modify: `docs/superpowers/specs/2026-09-09-corp-industry-opendart-design.md`

**Interfaces:**
- Consumes: Task 6–7 경로
- Produces: 운영자가 키와 버튼을 찾을 수 있는 문서

- [ ] **Step 1: Write the README rows**

`packages/web-api/README.md` Admin 표에:

| 메서드 | 경로 | 설명 |
| POST | `/admin/corps/enrich` | 빠진 회사 OpenDART 개황 채우기 (202, `job_id`) |
| GET | `/admin/corps/status?job_id=` | 회사 업종 잡 현황·로그 |
| GET | `/admin/corps/summary` | 공시 distinct / ok / 남음 |
| POST | `/admin/corps/jobs/{job_id}/soft-stop` | 다음 회사 경계에서 중단 |
| POST | `/admin/corps/jobs/{job_id}/force-finish` | 강제 마감 |

본문에: OpenDART는 기업개황만, `OPENDART_API_KEY`, `/admin` 오른쪽 **회사 업종** 칸, 단위는 distinct `corp_code`. 수집·감사 추출 잠금과 무관.

스펙 상태 줄을 `승인 (구현)`으로 바꾼다.

- [ ] **Step 2: Run a focused regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ksic.py tests/test_ensure_schema.py tests/test_corp_repository.py tests/test_opendart_company.py tests/test_corp_industry_service.py tests/test_corps_admin_api.py tests/test_corps_admin_ui.py tests/test_extraction_service.py::test_start_raises_when_audit_extraction_running tests/test_admin_ui.py -v`

Expected: PASS

- [ ] **Step 3: Commit**

```powershell
git add packages/web-api/README.md README.md docs/superpowers/specs/2026-09-09-corp-industry-opendart-design.md
git commit -m "docs: 회사 업종 OpenDART 보강 경로를 적는다"
```

---

## Self-review (plan vs spec)

| Spec | Task |
|------|------|
| `corps` PK·컬럼·create_all | 2 |
| KSIC 파일·264 계층·미적중 NULL | 1 |
| `company.json`만, status 위치, 빈 stock_code | 4 |
| distinct disclosures, skip ok, fill_missing | 3, 5 |
| 키 없음 400, 충돌 409, 020/010 중단, HTTP 계속 | 5, 6 |
| dart_job_lock 비공유 | 5 테스트 |
| Admin JSON 5경로 | 6 |
| `/admin` 별도 칸, 회사 수, HTMX, 폼 | 7 |
| 비범위 (Facts JOIN, 이력, ZIP, 주소 필드) | 코드에 넣지 않음 |
| 사용자 한국어 메시지 | 5, 6, 7 |
