# Admin 카탈로그 · Public Viewer 뼈대 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `packages/web-api`에 FastAPI 기반 Admin 카탈로그 수집 모듈과 Public Viewer(Lazy Retrieval) 모듈의 동작하는 코드 뼈대를 만든다.

**Architecture:** 단일 FastAPI 앱을 레이어드 구조(`api` → `services` → `ports/adapters` → `db`)로 구성한다. Entry 수집은 기존 Node `@dart-wrapper/entry-extractor`를 `EntryCollector` 포트 뒤의 서브프로세스 어댑터로 감싸고, Viewer는 DB에 저장된 `viewer_url`로 요청 시점에 원문을 가져와 정제한다.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2 + pydantic-settings, httpx(Async), BeautifulSoup4 + lxml, SQLAlchemy 2.0(async) + aiosqlite / asyncpg, pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-07-25-admin-viewer-skeleton-design.md`

## Global Constraints

- Python 3.11+ 사용, 모든 함수 입력/출력에 타입 힌트 명시
- 주석·Docstring·로그·예외 메시지·사용자 응답 메시지는 **한국어**
- I/O(HTTP, DB, 서브프로세스)는 반드시 `async`/`await`
- Black / Flake8 기준 스타일 준수 (line length 100)
- OpenDART API 사용 금지 — DART 상세검색/상세페이지 HTML 스크래핑만 사용
- DB에는 entry 메타데이터만 저장. 원문 HTML·정제 텍스트·표는 저장하지 않음
- 원문 수집 시 EUC-KR / UTF-8 인코딩 자동 처리
- DB 접근은 Repository 경계 뒤에 둔다. `DATABASE_URL` 교체만으로 SQLite ↔ PostgreSQL 전환 가능
- 모든 작업 디렉터리는 `packages/web-api` 기준 (명시된 경우 제외)
- 테스트는 실제 DART 서버를 호출하지 않는다

## 스펙 대비 조정 사항 (구현 중 확정)

- `fetchDisclosureList`는 `corp_code` 필터를 지원하지 않는다. `corp_code`는 Python 어댑터에서 수집 후 필터링한다.
- `catalog_jobs`에 중복 실행 방지용 `params_key`(정렬된 JSON 문자열) 컬럼을 추가한다.
- 의존성 주입을 위해 스펙 디렉터리에 `app/api/deps.py`를 추가한다.
- `POST /admin/catalog/extract`는 비동기 수락을 명확히 하기 위해 `202 Accepted`로 응답한다.
- pandas는 이번 뼈대에서 사용하지 않으므로 `transform` optional extra로만 둔다.

---

## Task 1: 패키지 스캐폴딩 · 설정 · 앱 팩토리

**Files:**
- Create: `packages/web-api/pyproject.toml`
- Create: `packages/web-api/app/__init__.py`
- Create: `packages/web-api/app/config.py`
- Create: `packages/web-api/app/main.py`
- Create: `packages/web-api/tests/__init__.py`
- Create: `packages/web-api/tests/conftest.py`
- Test: `packages/web-api/tests/test_app.py`

**Interfaces:**
- Consumes: 없음 (첫 작업)
- Produces:
  - `app.config.Settings` — 속성: `database_url: str`, `node_executable: str`, `entry_collector_script: Path`, `collector_timeout_seconds: int`, `dart_fetch_concurrency: int`, `dart_fetch_timeout_seconds: float`, `dart_fetch_max_retries: int`
  - `app.config.get_settings() -> Settings` (lru_cache)
  - `app.main.create_app() -> FastAPI`

- [ ] **Step 1: 패키지 메타데이터 작성**

`packages/web-api/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "dart-wrapper-web-api"
version = "0.1.0"
description = "DART 공시 카탈로그 Admin 수집 및 Public Viewer API"
requires-python = ">=3.11"
dependencies = [
    "fastapi",
    "uvicorn[standard]",
    "pydantic",
    "pydantic-settings",
    "httpx",
    "beautifulsoup4",
    "lxml",
    "SQLAlchemy",
    "aiosqlite",
    "greenlet",
]

[project.optional-dependencies]
postgres = ["asyncpg"]
transform = ["pandas"]
dev = ["pytest", "pytest-asyncio", "black", "flake8"]

[tool.setuptools.packages.find]
include = ["app*"]

[tool.black]
line-length = 100

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: 의존성 설치**

Run (in `packages/web-api`):

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Expected: `Successfully installed ... dart-wrapper-web-api-0.1.0 ...`

이후 모든 `python` 명령은 `.venv\Scripts\python.exe`를 사용한다.

- [ ] **Step 3: 실패하는 테스트 작성**

`packages/web-api/tests/__init__.py`: 빈 파일.

`packages/web-api/tests/conftest.py`:

```python
"""테스트 공통 픽스처."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI


@pytest.fixture
def client_factory():
    """lifespan을 실행하지 않고 앱에 직접 요청하는 httpx 클라이언트를 만든다."""

    def _factory(app: FastAPI) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    return _factory
```

`packages/web-api/tests/test_app.py`:

```python
"""앱 팩토리와 기본 설정 테스트."""

from __future__ import annotations

from app.config import Settings
from app.main import create_app


async def test_health_endpoint_returns_ok(client_factory) -> None:
    app = create_app()
    async with client_factory(app) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_default_settings_use_local_sqlite() -> None:
    settings = Settings()

    assert settings.database_url.startswith("sqlite+aiosqlite")
    assert settings.dart_fetch_concurrency == 4
    assert settings.entry_collector_script.name == "collect-entries.js"
```

- [ ] **Step 4: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 5: 설정 모듈 구현**

`packages/web-api/app/__init__.py`: 빈 파일.

`packages/web-api/app/config.py`:

```python
"""애플리케이션 설정. 환경변수 또는 .env로 주입한다."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# packages/web-api/app/config.py → 모노레포 루트
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COLLECTOR_SCRIPT = (
    REPO_ROOT / "packages" / "entry-extractor" / "bin" / "collect-entries.js"
)


class Settings(BaseSettings):
    """환경변수 기반 설정값.

    개발 환경은 SQLite, 웹 배포는 PostgreSQL(Neon)을 사용한다.
    DATABASE_URL만 교체하면 코드 변경 없이 전환된다.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./dart_catalog.db"
    node_executable: str = "node"
    entry_collector_script: Path = DEFAULT_COLLECTOR_SCRIPT
    collector_timeout_seconds: int = 900
    dart_fetch_concurrency: int = 4
    dart_fetch_timeout_seconds: float = 15.0
    dart_fetch_max_retries: int = 2


@lru_cache
def get_settings() -> Settings:
    """설정 객체를 캐시해 반환한다."""
    return Settings()
```

- [ ] **Step 6: 앱 팩토리 구현**

`packages/web-api/app/main.py`:

```python
"""FastAPI 앱 생성 및 라우터 등록."""

from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    """DART 공시 파이프라인 API 앱을 생성한다."""
    app = FastAPI(
        title="DART 공시 파이프라인 API",
        description="Admin 카탈로그 수집과 Public Viewer(Lazy Retrieval)를 제공합니다.",
        version="0.1.0",
    )

    @app.get("/health", tags=["시스템"])
    async def health() -> dict[str, str]:
        """서비스 생존 여부를 반환한다."""
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 7: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_app.py -v`
Expected: PASS (2 passed)

- [ ] **Step 8: 커밋**

```bash
git add packages/web-api
git commit -m "feat(web-api): scaffold FastAPI package with settings and health endpoint"
```

---

## Task 2: 도메인 예외 · 예외 핸들러

**Files:**
- Create: `packages/web-api/app/errors.py`
- Modify: `packages/web-api/app/main.py`
- Test: `packages/web-api/tests/test_errors.py`

**Interfaces:**
- Consumes: `app.main.create_app()`
- Produces:
  - `app.errors.DartWrapperError(Exception)`
  - `app.errors.CatalogNotFound(DartWrapperError)` → HTTP 404
  - `app.errors.SourceFetchError(DartWrapperError)` → HTTP 502
  - `app.errors.ParseError(DartWrapperError)` → HTTP 502
  - `app.errors.register_exception_handlers(app: FastAPI) -> None`
  - 응답 본문 형식: `{"detail": "<한국어 메시지>"}`

- [ ] **Step 1: 실패하는 테스트 작성**

`packages/web-api/tests/test_errors.py`:

```python
"""도메인 예외가 HTTP 응답으로 변환되는지 검증한다."""

from __future__ import annotations

import pytest

from app.errors import CatalogNotFound, ParseError, SourceFetchError
from app.main import create_app


@pytest.mark.parametrize(
    ("exception", "expected_status", "expected_detail"),
    [
        (CatalogNotFound("카탈로그에 없습니다."), 404, "카탈로그에 없습니다."),
        (SourceFetchError("원문을 가져오지 못했습니다."), 502, "원문을 가져오지 못했습니다."),
        (ParseError("본문 파싱에 실패했습니다."), 502, "본문 파싱에 실패했습니다."),
    ],
)
async def test_domain_exception_maps_to_http_response(
    client_factory, exception: Exception, expected_status: int, expected_detail: str
) -> None:
    app = create_app()

    @app.get("/_test/raise")
    async def _raise() -> None:
        raise exception

    async with client_factory(app) as client:
        response = await client.get("/_test/raise")

    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.errors'`

- [ ] **Step 3: 예외 모듈 구현**

`packages/web-api/app/errors.py`:

```python
"""서비스 도메인 예외와 HTTP 변환 핸들러."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DartWrapperError(Exception):
    """서비스 공통 예외의 기반 클래스."""


class CatalogNotFound(DartWrapperError):
    """요청한 공시/섹션이 카탈로그에 없을 때 발생한다."""


class SourceFetchError(DartWrapperError):
    """DART 원문을 가져오지 못했을 때 발생한다."""


class ParseError(DartWrapperError):
    """원문 HTML 정제·표 파싱에 실패했을 때 발생한다."""


_STATUS_BY_EXCEPTION: dict[type[DartWrapperError], int] = {
    CatalogNotFound: 404,
    SourceFetchError: 502,
    ParseError: 502,
}


def register_exception_handlers(app: FastAPI) -> None:
    """도메인 예외를 한국어 메시지 JSON 응답으로 변환하는 핸들러를 등록한다."""

    async def handle(request: Request, exc: DartWrapperError) -> JSONResponse:
        status_code = _STATUS_BY_EXCEPTION.get(type(exc), 500)
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    for exception_type in _STATUS_BY_EXCEPTION:
        app.add_exception_handler(exception_type, handle)
```

- [ ] **Step 4: 앱 팩토리에 핸들러 등록**

`packages/web-api/app/main.py`의 import와 `create_app` 본문을 수정한다.

```python
from fastapi import FastAPI

from app.errors import register_exception_handlers
```

`app = FastAPI(...)` 생성 직후에 다음 한 줄을 추가한다.

```python
    register_exception_handlers(app)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -v`
Expected: PASS (5 passed)

- [ ] **Step 6: 커밋**

```bash
git add packages/web-api
git commit -m "feat(web-api): add domain errors with Korean HTTP responses"
```

---

## Task 3: DB 모델 · 세션 · Entry 스키마

**Files:**
- Create: `packages/web-api/app/models/__init__.py`
- Create: `packages/web-api/app/models/base.py`
- Create: `packages/web-api/app/models/entry.py`
- Create: `packages/web-api/app/models/catalog_job.py`
- Create: `packages/web-api/app/db/__init__.py`
- Create: `packages/web-api/app/db/session.py`
- Create: `packages/web-api/app/schemas/__init__.py`
- Create: `packages/web-api/app/schemas/entry.py`
- Test: `packages/web-api/tests/test_models.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `app.models.base.Base` (SQLAlchemy `DeclarativeBase`)
  - `app.models.entry.Entry` — PK `entry_id`, 인덱스 `rcept_no`, `corp_code`
  - `app.models.catalog_job.CatalogJob` — PK `job_id`, 컬럼 `status`, `params`, `params_key`, `total_entries`, `saved_entries`, `error_message`, `started_at`, `finished_at`, `created_at`
  - `app.models.catalog_job.CatalogJobLog` — PK `id`, FK `job_id`, `level`, `message`, `created_at`
  - `app.db.session.create_db_engine(database_url: str) -> AsyncEngine`
  - `app.db.session.create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]`
  - `app.db.session.create_all(engine: AsyncEngine) -> None` (async)
  - `app.schemas.entry.EntryRecord` (Pydantic, Node 출력 alias `reportType`/`dcmNo` 수용)

- [ ] **Step 1: 실패하는 테스트 작성**

`packages/web-api/tests/test_models.py`:

```python
"""모델·세션·EntryRecord 스키마 테스트."""

from __future__ import annotations

from sqlalchemy import select

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.models.entry import Entry
from app.schemas.entry import EntryRecord


def test_entry_record_accepts_node_aliases() -> None:
    record = EntryRecord.model_validate(
        {
            "entry_id": "20260724000650_11495035_5",
            "rcept_no": "20260724000650",
            "reportType": "F001",
            "dcmNo": "11495035",
            "source": "body",
            "section_name": "재무상태표",
            "path": ["(첨부)재무제표", "재무상태표"],
            "viewer_url": "https://dart.fss.or.kr/report/viewer.do?rcpNo=1",
            "무시되는필드": "값",
        }
    )

    assert record.report_type == "F001"
    assert record.dcm_no == "11495035"
    assert record.path == ["(첨부)재무제표", "재무상태표"]


async def test_entry_table_roundtrip() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)

    async with sessionmaker() as session:
        session.add(
            Entry(
                entry_id="20260724000650_11495035_5",
                rcept_no="20260724000650",
                source="body",
                section_name="재무상태표",
                path=["(첨부)재무제표", "재무상태표"],
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=1",
            )
        )
        await session.commit()

    async with sessionmaker() as session:
        stored = (await session.execute(select(Entry))).scalars().all()

    assert len(stored) == 1
    assert stored[0].path == ["(첨부)재무제표", "재무상태표"]
    await engine.dispose()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: Base와 세션 모듈 구현**

`packages/web-api/app/models/__init__.py`:

```python
"""SQLAlchemy 모델 패키지."""

from app.models.base import Base
from app.models.catalog_job import CatalogJob, CatalogJobLog
from app.models.entry import Entry

__all__ = ["Base", "CatalogJob", "CatalogJobLog", "Entry"]
```

`packages/web-api/app/models/base.py`:

```python
"""SQLAlchemy 선언적 베이스."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """모든 모델의 공통 베이스."""
```

`packages/web-api/app/db/__init__.py`: 빈 파일.

`packages/web-api/app/db/session.py`:

```python
"""비동기 DB 엔진·세션 팩토리. SQLite와 PostgreSQL을 함께 지원한다."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import Base


def create_db_engine(database_url: str) -> AsyncEngine:
    """DATABASE_URL로 비동기 엔진을 만든다."""
    return create_async_engine(database_url, future=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """요청 단위 세션을 만드는 세션메이커를 반환한다."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def create_all(engine: AsyncEngine) -> None:
    """모델 정의를 기준으로 테이블을 생성한다(뼈대 단계용)."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
```

- [ ] **Step 4: Entry 모델 구현**

`packages/web-api/app/models/entry.py`:

```python
"""flat leaf 엔트리 카탈로그 테이블. 메타데이터만 저장한다."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    """UTC 기준 현재 시각."""
    return datetime.now(timezone.utc)


class Entry(Base):
    """공시 컨테이너 내 leaf 문서·섹션 단위 엔트리."""

    __tablename__ = "entries"
    __table_args__ = (
        Index("ix_entries_rcept_no_entry_id", "rcept_no", "entry_id"),
    )

    entry_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    rcept_no: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    report_type: Mapped[str | None] = mapped_column(String(16))
    correction_type: Mapped[str | None] = mapped_column(String(32))
    report_nm: Mapped[str | None] = mapped_column(String(255))
    year_end: Mapped[str | None] = mapped_column(String(32))
    corp_code: Mapped[str | None] = mapped_column(String(16), index=True)
    corp_name: Mapped[str | None] = mapped_column(String(255))
    submitter: Mapped[str | None] = mapped_column(String(255))
    rcept_dt: Mapped[str | None] = mapped_column(String(16))
    bsns_year: Mapped[str | None] = mapped_column(String(8))
    disclosure_url: Mapped[str | None] = mapped_column(String(1024))
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    dcm_no: Mapped[str | None] = mapped_column(String(32))
    document_name: Mapped[str | None] = mapped_column(String(255))
    section_name: Mapped[str | None] = mapped_column(String(255))
    section_original_name: Mapped[str | None] = mapped_column(String(255))
    depth: Mapped[int | None] = mapped_column(Integer)
    is_leaf: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    parent_ele_id: Mapped[str | None] = mapped_column(String(32))
    ele_id: Mapped[str | None] = mapped_column(String(32))
    offset: Mapped[str | None] = mapped_column(String(32))
    length: Mapped[str | None] = mapped_column(String(32))
    dtd: Mapped[str | None] = mapped_column(String(64))
    path: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    viewer_url: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
```

- [ ] **Step 5: 수집 작업 모델 구현**

`packages/web-api/app/models/catalog_job.py`:

```python
"""Admin 카탈로그 수집 작업과 진행 로그 테이블."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    """UTC 기준 현재 시각."""
    return datetime.now(timezone.utc)


class CatalogJob(Base):
    """수집 작업 단위. 상태와 진행 수치를 보관한다."""

    __tablename__ = "catalog_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    params_key: Mapped[str] = mapped_column(String(512), index=True, nullable=False)
    total_entries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    saved_entries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CatalogJobLog(Base):
    """수집 작업 진행 로그 한 줄."""

    __tablename__ = "catalog_job_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("catalog_jobs.job_id"), index=True, nullable=False
    )
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
```

- [ ] **Step 6: EntryRecord 스키마 구현**

`packages/web-api/app/schemas/__init__.py`: 빈 파일.

`packages/web-api/app/schemas/entry.py`:

```python
"""entry-extractor 출력과 DB 사이를 잇는 엔트리 스키마."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EntryRecord(BaseModel):
    """Node entry-extractor가 만든 flat leaf 엔트리 1건.

    Node 쪽 camelCase 필드(reportType, dcmNo)는 alias로 받는다.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    entry_id: str
    rcept_no: str
    report_type: str | None = Field(default=None, alias="reportType")
    correction_type: str | None = None
    report_nm: str | None = None
    year_end: str | None = None
    corp_code: str | None = None
    corp_name: str | None = None
    submitter: str | None = None
    rcept_dt: str | None = None
    bsns_year: str | None = None
    disclosure_url: str | None = None
    source: str
    dcm_no: str | None = Field(default=None, alias="dcmNo")
    document_name: str | None = None
    section_name: str | None = None
    section_original_name: str | None = None
    depth: int | None = None
    is_leaf: bool = True
    parent_ele_id: str | None = None
    ele_id: str | None = None
    offset: str | None = None
    length: str | None = None
    dtd: str | None = None
    path: list[str] = Field(default_factory=list)
    viewer_url: str | None = None
```

- [ ] **Step 7: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 8: 커밋**

```bash
git add packages/web-api
git commit -m "feat(web-api): add catalog entry and job models with async session factory"
```

---

## Task 4: EntryRepository

**Files:**
- Create: `packages/web-api/app/repositories/__init__.py`
- Create: `packages/web-api/app/repositories/entry_repository.py`
- Test: `packages/web-api/tests/test_entry_repository.py`

**Interfaces:**
- Consumes: `app.models.entry.Entry`, `app.schemas.entry.EntryRecord`, `app.db.session.*`
- Produces:
  - `app.repositories.entry_repository.EntryRepository(session: AsyncSession)`
  - `async upsert_many(records: Sequence[EntryRecord]) -> int` — 저장/갱신 건수 반환
  - `async list_by_rcept_no(rcept_no: str) -> list[Entry]` — `entry_id` 오름차순
  - `async get_by_entry_id(entry_id: str) -> Entry | None`

- [ ] **Step 1: 실패하는 테스트 작성**

`packages/web-api/tests/test_entry_repository.py`:

```python
"""EntryRepository upsert·조회 테스트."""

from __future__ import annotations

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.repositories.entry_repository import EntryRepository
from app.schemas.entry import EntryRecord


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def _record(entry_id: str, section_name: str) -> EntryRecord:
    return EntryRecord(
        entry_id=entry_id,
        rcept_no="20260724000650",
        source="body",
        dcm_no="11495035",
        ele_id=entry_id.rsplit("_", 1)[-1],
        section_name=section_name,
        path=["감사보고서", section_name],
        viewer_url=f"https://dart.fss.or.kr/report/viewer.do?rcpNo={entry_id}",
    )


async def test_upsert_many_inserts_then_updates(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = EntryRepository(session)
        saved = await repository.upsert_many([_record("a_1", "재무상태표")])
        await session.commit()

    assert saved == 1

    async with sessionmaker_fixture() as session:
        repository = EntryRepository(session)
        saved = await repository.upsert_many([_record("a_1", "손익계산서")])
        await session.commit()

    async with sessionmaker_fixture() as session:
        repository = EntryRepository(session)
        entries = await repository.list_by_rcept_no("20260724000650")

    assert saved == 1
    assert len(entries) == 1
    assert entries[0].section_name == "손익계산서"


async def test_list_by_rcept_no_and_get_by_entry_id(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = EntryRepository(session)
        await repository.upsert_many([_record("a_2", "주석"), _record("a_1", "재무상태표")])
        await session.commit()

    async with sessionmaker_fixture() as session:
        repository = EntryRepository(session)
        entries = await repository.list_by_rcept_no("20260724000650")
        found = await repository.get_by_entry_id("a_2")
        missing = await repository.get_by_entry_id("없는값")

    assert [entry.entry_id for entry in entries] == ["a_1", "a_2"]
    assert found is not None and found.section_name == "주석"
    assert missing is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_entry_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.repositories'`

- [ ] **Step 3: 구현**

`packages/web-api/app/repositories/__init__.py`: 빈 파일.

`packages/web-api/app/repositories/entry_repository.py`:

```python
"""엔트리 카탈로그 영속화. DB 종류에 의존하지 않는 방식으로 구현한다."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entry import Entry
from app.schemas.entry import EntryRecord


class EntryRepository:
    """flat leaf 엔트리 저장·조회 담당."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_many(self, records: Sequence[EntryRecord]) -> int:
        """entry_id 기준으로 병합 저장한다. 재실행 시 중복이 생기지 않는다.

        SQLite/PostgreSQL 모두에서 같은 코드로 동작하도록 세션 merge를 사용한다.
        """
        for record in records:
            await self._session.merge(Entry(**record.model_dump()))
        return len(records)

    async def list_by_rcept_no(self, rcept_no: str) -> list[Entry]:
        """해당 접수번호의 모든 엔트리를 entry_id 순으로 반환한다."""
        statement = select(Entry).where(Entry.rcept_no == rcept_no).order_by(Entry.entry_id)
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def get_by_entry_id(self, entry_id: str) -> Entry | None:
        """entry_id로 단일 엔트리를 조회한다. 없으면 None."""
        return await self._session.get(Entry, entry_id)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_entry_repository.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add packages/web-api
git commit -m "feat(web-api): add EntryRepository with portable upsert"
```

---

## Task 5: JobRepository

**Files:**
- Create: `packages/web-api/app/repositories/job_repository.py`
- Test: `packages/web-api/tests/test_job_repository.py`

**Interfaces:**
- Consumes: `app.models.catalog_job.CatalogJob`, `CatalogJobLog`
- Produces:
  - `app.repositories.job_repository.JobRepository(session: AsyncSession)`
  - `async create(job_id: str, params: dict[str, Any], params_key: str) -> CatalogJob`
  - `async find_active(params_key: str) -> CatalogJob | None` — `status in ("pending", "running")`
  - `async get(job_id: str) -> CatalogJob | None`
  - `async mark_running(job_id: str) -> None`
  - `async mark_succeeded(job_id: str, total_entries: int, saved_entries: int) -> None`
  - `async mark_failed(job_id: str, error_message: str) -> None`
  - `async add_log(job_id: str, level: str, message: str) -> None`
  - `async recent_logs(job_id: str, limit: int = 50) -> list[CatalogJobLog]` — 최신순

- [ ] **Step 1: 실패하는 테스트 작성**

`packages/web-api/tests/test_job_repository.py`:

```python
"""JobRepository 상태 전이·로그 테스트."""

from __future__ import annotations

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.repositories.job_repository import JobRepository


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


async def test_create_and_find_active(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        await repository.create("job-1", {"report_type": "F001"}, "key-1")
        await session.commit()

    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        active = await repository.find_active("key-1")
        other = await repository.find_active("key-2")

    assert active is not None and active.job_id == "job-1"
    assert active.status == "pending"
    assert other is None


async def test_status_transitions_and_logs(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        await repository.create("job-2", {}, "key-2")
        await repository.mark_running("job-2")
        await repository.add_log("job-2", "info", "수집을 시작합니다.")
        await repository.mark_succeeded("job-2", total_entries=12, saved_entries=12)
        await session.commit()

    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        job = await repository.get("job-2")
        logs = await repository.recent_logs("job-2")
        active = await repository.find_active("key-2")

    assert job is not None
    assert job.status == "succeeded"
    assert (job.total_entries, job.saved_entries) == (12, 12)
    assert job.started_at is not None and job.finished_at is not None
    assert [log.message for log in logs] == ["수집을 시작합니다."]
    assert active is None


async def test_mark_failed_records_message(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        repository = JobRepository(session)
        await repository.create("job-3", {}, "key-3")
        await repository.mark_failed("job-3", "수집 프로세스가 비정상 종료되었습니다.")
        await session.commit()

    async with sessionmaker_fixture() as session:
        job = await JobRepository(session).get("job-3")

    assert job is not None
    assert job.status == "failed"
    assert job.error_message == "수집 프로세스가 비정상 종료되었습니다."
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_job_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.repositories.job_repository'`

- [ ] **Step 3: 구현**

`packages/web-api/app/repositories/job_repository.py`:

```python
"""수집 작업(job)과 진행 로그 영속화."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog_job import CatalogJob, CatalogJobLog

ACTIVE_STATUSES = ("pending", "running")


def _now() -> datetime:
    """UTC 기준 현재 시각."""
    return datetime.now(timezone.utc)


class JobRepository:
    """수집 작업 상태 전이와 로그 기록을 담당한다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, job_id: str, params: dict[str, Any], params_key: str) -> CatalogJob:
        """대기 상태의 새 작업을 만든다."""
        job = CatalogJob(job_id=job_id, params=params, params_key=params_key, status="pending")
        self._session.add(job)
        await self._session.flush()
        return job

    async def find_active(self, params_key: str) -> CatalogJob | None:
        """같은 파라미터로 진행 중인 작업이 있으면 반환한다."""
        statement = (
            select(CatalogJob)
            .where(CatalogJob.params_key == params_key)
            .where(CatalogJob.status.in_(ACTIVE_STATUSES))
            .order_by(CatalogJob.created_at.desc())
        )
        result = await self._session.execute(statement)
        return result.scalars().first()

    async def get(self, job_id: str) -> CatalogJob | None:
        """작업을 조회한다. 없으면 None."""
        return await self._session.get(CatalogJob, job_id)

    async def mark_running(self, job_id: str) -> None:
        """작업을 실행 중으로 전환한다."""
        job = await self._require(job_id)
        job.status = "running"
        job.started_at = _now()

    async def mark_succeeded(self, job_id: str, total_entries: int, saved_entries: int) -> None:
        """작업을 성공으로 마감하고 수집 수치를 기록한다."""
        job = await self._require(job_id)
        job.status = "succeeded"
        job.total_entries = total_entries
        job.saved_entries = saved_entries
        job.finished_at = _now()

    async def mark_failed(self, job_id: str, error_message: str) -> None:
        """작업을 실패로 마감하고 원인을 기록한다."""
        job = await self._require(job_id)
        job.status = "failed"
        job.error_message = error_message
        job.finished_at = _now()

    async def add_log(self, job_id: str, level: str, message: str) -> None:
        """작업 진행 로그를 한 줄 남긴다."""
        self._session.add(CatalogJobLog(job_id=job_id, level=level, message=message))
        await self._session.flush()

    async def recent_logs(self, job_id: str, limit: int = 50) -> list[CatalogJobLog]:
        """최근 로그를 최신순으로 반환한다."""
        statement = (
            select(CatalogJobLog)
            .where(CatalogJobLog.job_id == job_id)
            .order_by(CatalogJobLog.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def _require(self, job_id: str) -> CatalogJob:
        """작업을 조회하고 없으면 예외를 발생시킨다."""
        job = await self.get(job_id)
        if job is None:
            raise ValueError(f"수집 작업을 찾을 수 없습니다: {job_id}")
        return job
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_job_repository.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add packages/web-api
git commit -m "feat(web-api): add JobRepository for catalog job state and logs"
```

---

## Task 6: 본문 텍스트 정제기

**Files:**
- Create: `packages/web-api/app/parsing/__init__.py`
- Create: `packages/web-api/app/parsing/cleaner.py`
- Test: `packages/web-api/tests/test_cleaner.py`

**Interfaces:**
- Consumes: 없음
- Produces: `app.parsing.cleaner.extract_text(html: str) -> str`

- [ ] **Step 1: 실패하는 테스트 작성**

`packages/web-api/tests/test_cleaner.py`:

```python
"""본문 텍스트 정제 테스트."""

from __future__ import annotations

from app.parsing.cleaner import extract_text

SAMPLE_HTML = """
<html>
  <head>
    <style>.a { color: red; }</style>
    <script>var x = 1;</script>
  </head>
  <body>
    <!-- 주석은 제외된다 -->
    <p>재무상태표</p>
    <p>자산총계&nbsp;&nbsp;1,000</p>
    <div>

    </div>
    <noscript>스크립트 비활성</noscript>
    <p>부채총계   400</p>
  </body>
</html>
"""


def test_extract_text_removes_noise_and_blank_lines() -> None:
    text = extract_text(SAMPLE_HTML)

    assert "재무상태표" in text
    assert "자산총계 1,000" in text
    assert "부채총계 400" in text
    assert "var x" not in text
    assert "color: red" not in text
    assert "주석은 제외된다" not in text
    assert "스크립트 비활성" not in text
    assert "\n\n" not in text


def test_extract_text_returns_empty_string_for_blank_html() -> None:
    assert extract_text("<html><body>   </body></html>") == ""
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cleaner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.parsing'`

- [ ] **Step 3: 구현**

`packages/web-api/app/parsing/__init__.py`: 빈 파일.

`packages/web-api/app/parsing/cleaner.py`:

```python
"""DART 원문 HTML에서 읽을 수 있는 본문 텍스트를 추출한다."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment

from app.errors import ParseError

# 본문과 무관한 태그는 통째로 제거한다.
_NOISE_TAGS = ("script", "style", "noscript", "iframe", "link", "meta")
_SPACES = re.compile(r"[ \t\u00a0\u3000]+")


def extract_text(html: str) -> str:
    """script/style/주석을 제거하고 공백을 정리한 본문 텍스트를 반환한다.

    :param html: 디코딩이 끝난 원문 HTML 문자열
    :return: 빈 줄이 없는 본문 텍스트
    :raises ParseError: HTML 파싱에 실패한 경우
    """
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:  # pragma: no cover - lxml 내부 오류 방어
        raise ParseError(f"본문 HTML을 파싱하지 못했습니다: {exc}") from exc

    for tag in soup(list(_NOISE_TAGS)):
        tag.decompose()
    for comment in soup.find_all(string=lambda node: isinstance(node, Comment)):
        comment.extract()

    raw_text = soup.get_text("\n")
    lines = (_SPACES.sub(" ", line).strip() for line in raw_text.splitlines())
    return "\n".join(line for line in lines if line)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cleaner.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add packages/web-api
git commit -m "feat(web-api): add HTML body text cleaner"
```

---

## Task 7: 표 파서

**Files:**
- Create: `packages/web-api/app/parsing/tables.py`
- Test: `packages/web-api/tests/test_tables.py`

**Interfaces:**
- Consumes: `app.errors.ParseError`
- Produces: `app.parsing.tables.extract_tables(html: str) -> list[dict[str, list]]`
  - 각 요소: `{"headers": list[str], "rows": list[list[str]]}`
  - `th`로 시작하는 첫 행은 `headers`, 없으면 `headers`는 빈 리스트

- [ ] **Step 1: 실패하는 테스트 작성**

`packages/web-api/tests/test_tables.py`:

```python
"""HTML 표 → JSON 변환 테스트."""

from __future__ import annotations

from app.parsing.tables import extract_tables

TABLE_HTML = """
<body>
  <table>
    <tr><th>과목</th><th>당기</th></tr>
    <tr><td>자산총계</td><td>1,000</td></tr>
    <tr><td>부채총계</td><td>400</td></tr>
  </table>
  <table>
    <tr><td>비고</td><td>단위: 백만원&nbsp;</td></tr>
  </table>
  <table></table>
</body>
"""


def test_extract_tables_splits_headers_and_rows() -> None:
    tables = extract_tables(TABLE_HTML)

    assert len(tables) == 2
    assert tables[0] == {
        "headers": ["과목", "당기"],
        "rows": [["자산총계", "1,000"], ["부채총계", "400"]],
    }


def test_extract_tables_keeps_all_rows_when_no_header() -> None:
    tables = extract_tables(TABLE_HTML)

    assert tables[1] == {"headers": [], "rows": [["비고", "단위: 백만원"]]}


def test_extract_tables_returns_empty_list_without_tables() -> None:
    assert extract_tables("<body><p>표 없음</p></body>") == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tables.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.parsing.tables'`

- [ ] **Step 3: 구현**

`packages/web-api/app/parsing/tables.py`:

```python
"""DART 원문 HTML의 표를 JSON 구조로 변환한다."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.errors import ParseError

_SPACES = re.compile(r"[\s\u00a0\u3000]+")


def _cell_text(cell: Tag) -> str:
    """셀 안의 공백·개행을 한 칸으로 정리한 문자열을 반환한다."""
    return _SPACES.sub(" ", cell.get_text(" ")).strip()


def extract_tables(html: str) -> list[dict[str, list]]:
    """HTML의 모든 표를 headers/rows 구조로 변환한다.

    :param html: 디코딩이 끝난 원문 HTML 문자열
    :return: 표별 {"headers": [...], "rows": [[...]]} 목록
    :raises ParseError: HTML 파싱에 실패한 경우
    """
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:  # pragma: no cover - lxml 내부 오류 방어
        raise ParseError(f"표 HTML을 파싱하지 못했습니다: {exc}") from exc

    for tag in soup(["script", "style"]):
        tag.decompose()

    tables: list[dict[str, list]] = []
    for table in soup.find_all("table"):
        parsed_rows: list[list[str]] = []
        for row in table.find_all("tr"):
            cells = [_cell_text(cell) for cell in row.find_all(["th", "td"])]
            if cells:
                parsed_rows.append(cells)

        if not parsed_rows:
            continue

        first_row = table.find("tr")
        has_header = bool(first_row and first_row.find("th"))
        headers = parsed_rows[0] if has_header else []
        rows = parsed_rows[1:] if has_header else parsed_rows
        tables.append({"headers": headers, "rows": rows})

    return tables
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tables.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add packages/web-api
git commit -m "feat(web-api): add HTML table to JSON parser"
```

---

## Task 8: DART HTTP 어댑터 (인코딩 자동 처리)

**Files:**
- Create: `packages/web-api/app/adapters/__init__.py`
- Create: `packages/web-api/app/adapters/dart_http.py`
- Test: `packages/web-api/tests/test_dart_http.py`

**Interfaces:**
- Consumes: `app.errors.SourceFetchError`
- Produces:
  - `app.adapters.dart_http.decode_html(content: bytes, content_type: str | None = None) -> str`
  - `app.adapters.dart_http.DartHttpClient(client: httpx.AsyncClient, timeout_seconds: float = 15.0, max_retries: int = 2, retry_backoff_seconds: float = 0.5)`
  - `async fetch_html(url: str) -> str` — 실패 시 `SourceFetchError`

- [ ] **Step 1: 실패하는 테스트 작성**

`packages/web-api/tests/test_dart_http.py`:

```python
"""인코딩 자동 처리와 원문 fetch 테스트."""

from __future__ import annotations

import httpx
import pytest

from app.adapters.dart_http import DartHttpClient, decode_html
from app.errors import SourceFetchError

EUC_KR_HTML = '<html><head><meta charset="euc-kr"></head><body>재무상태표</body></html>'


def test_decode_html_uses_meta_charset() -> None:
    content = EUC_KR_HTML.encode("euc-kr")

    assert "재무상태표" in decode_html(content, content_type="text/html")


def test_decode_html_uses_header_charset() -> None:
    content = "<html><body>손익계산서</body></html>".encode("utf-8")

    assert "손익계산서" in decode_html(content, content_type="text/html; charset=utf-8")


def test_decode_html_falls_back_to_korean_codec() -> None:
    content = "<html><body>현금흐름표</body></html>".encode("cp949")

    assert "현금흐름표" in decode_html(content, content_type=None)


async def test_fetch_html_decodes_euc_kr_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=EUC_KR_HTML.encode("euc-kr"),
            headers={"Content-Type": "text/html"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        html = await DartHttpClient(client).fetch_html("https://dart.fss.or.kr/report/viewer.do")

    assert "재무상태표" in html


async def test_fetch_html_retries_then_raises_on_server_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500, content=b"error")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = DartHttpClient(client, max_retries=1, retry_backoff_seconds=0.0)
        with pytest.raises(SourceFetchError):
            await fetcher.fetch_html("https://dart.fss.or.kr/report/viewer.do")

    assert attempts == 2
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dart_http.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.adapters'`

- [ ] **Step 3: 구현**

`packages/web-api/app/adapters/__init__.py`: 빈 파일.

`packages/web-api/app/adapters/dart_http.py`:

```python
"""DART 원문 HTML 수집기. 한국어 인코딩을 자동 판별한다."""

from __future__ import annotations

import asyncio
import re

import httpx

from app.errors import SourceFetchError

_CHARSET_IN_HEADER = re.compile(r"charset=([\w\-]+)", re.IGNORECASE)
_CHARSET_IN_META = re.compile(rb"charset=[\"']?\s*([\w\-]+)", re.IGNORECASE)
# EUC-KR로 표기된 문서에도 확장 한글이 들어오므로 상위 호환 코덱으로 읽는다.
_KOREAN_ALIASES = {"euc-kr", "euckr", "ks_c_5601-1987", "ksc5601", "korean"}


def _normalize_charset(charset: str | None) -> str | None:
    """문자셋 이름을 파이썬 코덱 이름으로 정규화한다."""
    if charset is None:
        return None
    lowered = charset.strip().lower()
    return "cp949" if lowered in _KOREAN_ALIASES else lowered


def decode_html(content: bytes, content_type: str | None = None) -> str:
    """응답 헤더 → meta charset → 한국어 코덱 순으로 디코딩을 시도한다.

    :param content: 원문 바이트
    :param content_type: 응답의 Content-Type 헤더 값
    :return: 디코딩된 HTML 문자열
    """
    declared = None
    if content_type:
        matched = _CHARSET_IN_HEADER.search(content_type)
        declared = matched.group(1) if matched else None

    if declared is None:
        matched_meta = _CHARSET_IN_META.search(content[:4096])
        declared = matched_meta.group(1).decode("ascii", "ignore") if matched_meta else None

    candidates = [_normalize_charset(declared), "utf-8", "cp949"]
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return content.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue

    # 어떤 코덱으로도 완전히 읽히지 않으면 손실을 허용해서라도 본문을 반환한다.
    return content.decode("cp949", errors="replace")


class DartHttpClient:
    """공용 httpx 클라이언트로 DART 원문을 가져온다."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds

    async def fetch_html(self, url: str) -> str:
        """원문 HTML을 가져와 문자열로 반환한다.

        일시적 오류는 지수 백오프로 재시도하고, 끝까지 실패하면 예외를 던진다.

        :raises SourceFetchError: 재시도 후에도 원문을 가져오지 못한 경우
        """
        last_reason = "알 수 없는 오류"

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(url, timeout=self._timeout_seconds)
                if response.status_code >= 500:
                    last_reason = f"DART 서버 오류(HTTP {response.status_code})"
                elif response.status_code >= 400:
                    raise SourceFetchError(
                        f"원문을 가져오지 못했습니다(HTTP {response.status_code}): {url}"
                    )
                else:
                    return decode_html(response.content, response.headers.get("Content-Type"))
            except httpx.HTTPError as exc:
                last_reason = f"네트워크 오류({exc})"

            if attempt < self._max_retries:
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))

        raise SourceFetchError(f"원문을 가져오지 못했습니다({last_reason}): {url}")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dart_http.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add packages/web-api
git commit -m "feat(web-api): add DART HTTP client with EUC-KR/UTF-8 detection"
```

---

## Task 9: EntryCollector 포트 · Node 브릿지

**Files:**
- Create: `packages/entry-extractor/bin/collect-entries.js`
- Modify: `packages/entry-extractor/README.md` (CLI 브릿지 절 추가)
- Create: `packages/web-api/app/ports/__init__.py`
- Create: `packages/web-api/app/ports/entry_collector.py`
- Create: `packages/web-api/app/adapters/node_entry_collector.py`
- Test: `packages/web-api/tests/test_node_entry_collector.py`

**Interfaces:**
- Consumes: `app.schemas.entry.EntryRecord`
- Produces:
  - `app.ports.entry_collector.CollectRequest` (Pydantic): `report_type: str`, `start_date: str`, `end_date: str`, `corp_code: str | None = None`, `max_total: int | None = None`, `include_attachments: bool = True`
  - `app.ports.entry_collector.EntryCollector` (Protocol): `async collect(request: CollectRequest) -> list[EntryRecord]`
  - `app.adapters.node_entry_collector.NodeEntryCollector(node_executable: str, script_path: Path, timeout_seconds: int = 900)`
  - Node CLI: stdin으로 JSON 파라미터, stdout으로 엔트리 배열 JSON, 진행 로그는 stderr

- [ ] **Step 1: 실패하는 테스트 작성**

`packages/web-api/tests/test_node_entry_collector.py`:

```python
"""Node 수집 브릿지 어댑터 테스트. 실제 node 대신 파이썬 가짜 스크립트를 실행한다."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.adapters.node_entry_collector import NodeEntryCollector
from app.errors import SourceFetchError
from app.ports.entry_collector import CollectRequest

FAKE_ENTRIES = [
    {
        "entry_id": "r1_d1_5",
        "rcept_no": "r1",
        "reportType": "F001",
        "dcmNo": "d1",
        "corp_code": "00224628",
        "source": "body",
        "section_name": "재무상태표",
        "path": ["감사보고서", "재무상태표"],
        "viewer_url": "https://dart.fss.or.kr/report/viewer.do?rcpNo=r1",
    },
    {
        "entry_id": "r2_d2_att",
        "rcept_no": "r2",
        "reportType": "F001",
        "dcmNo": "d2",
        "corp_code": "99999999",
        "source": "attachment",
        "section_name": "감사보고서",
        "path": ["감사보고서"],
        "viewer_url": "https://dart.fss.or.kr/report/viewer.do?rcpNo=r2",
    },
]


@pytest.fixture
def fake_script(tmp_path: Path) -> Path:
    """stdin JSON을 확인하고 고정 엔트리를 출력하는 가짜 수집 스크립트.

    Windows에서 파이프 기본 인코딩이 cp949이므로, 어댑터와 동일하게 UTF-8 바이트로 출력한다.
    """
    data_file = tmp_path / "entries.json"
    data_file.write_text(json.dumps(FAKE_ENTRIES, ensure_ascii=False), encoding="utf-8")

    script = tmp_path / "fake_collector.py"
    script.write_text(
        "import json, sys\n"
        "payload = json.loads(sys.stdin.read())\n"
        "assert payload['report_type'] == 'F001'\n"
        "sys.stderr.write('진행 로그\\n')\n"
        f"data = open(r'{data_file}', 'rb').read()\n"
        "sys.stdout.buffer.write(data)\n",
        encoding="utf-8",
    )
    return script


@pytest.fixture
def failing_script(tmp_path: Path) -> Path:
    """비정상 종료하는 가짜 수집 스크립트."""
    script = tmp_path / "failing_collector.py"
    script.write_text(
        "import sys\n"
        "sys.stderr.buffer.write('수집 실패: 목록 요청 오류\\n'.encode('utf-8'))\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    return script


async def test_collect_parses_entries(fake_script: Path) -> None:
    collector = NodeEntryCollector(sys.executable, fake_script)

    records = await collector.collect(
        CollectRequest(report_type="F001", start_date="20260701", end_date="20260724")
    )

    assert [record.entry_id for record in records] == ["r1_d1_5", "r2_d2_att"]
    assert records[0].report_type == "F001"
    assert records[0].dcm_no == "d1"


async def test_collect_filters_by_corp_code(fake_script: Path) -> None:
    collector = NodeEntryCollector(sys.executable, fake_script)

    records = await collector.collect(
        CollectRequest(
            report_type="F001",
            start_date="20260701",
            end_date="20260724",
            corp_code="00224628",
        )
    )

    assert [record.entry_id for record in records] == ["r1_d1_5"]


async def test_collect_raises_when_process_fails(failing_script: Path) -> None:
    collector = NodeEntryCollector(sys.executable, failing_script)

    with pytest.raises(SourceFetchError) as error:
        await collector.collect(
            CollectRequest(report_type="F001", start_date="20260701", end_date="20260724")
        )

    assert "수집 실패" in str(error.value)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_node_entry_collector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ports'`

- [ ] **Step 3: 포트 정의**

`packages/web-api/app/ports/__init__.py`: 빈 파일.

`packages/web-api/app/ports/entry_collector.py`:

```python
"""엔트리 수집 포트. 구현체(Node 브릿지 등)를 교체할 수 있게 한다."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from app.schemas.entry import EntryRecord


class CollectRequest(BaseModel):
    """수집 범위 요청. 날짜는 YYYYMMDD 형식이다."""

    report_type: str
    start_date: str = Field(pattern=r"^\d{8}$")
    end_date: str = Field(pattern=r"^\d{8}$")
    corp_code: str | None = None
    max_total: int | None = Field(default=None, ge=1)
    include_attachments: bool = True


class EntryCollector(Protocol):
    """공시 목록·상세를 훑어 flat leaf 엔트리를 만드는 수집기."""

    async def collect(self, request: CollectRequest) -> list[EntryRecord]:
        """요청 범위의 엔트리를 모두 수집해 반환한다."""
        ...
```

- [ ] **Step 4: Node 어댑터 구현**

`packages/web-api/app/adapters/node_entry_collector.py`:

```python
"""Node @dart-wrapper/entry-extractor를 서브프로세스로 호출하는 수집 어댑터."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from app.errors import SourceFetchError
from app.ports.entry_collector import CollectRequest
from app.schemas.entry import EntryRecord

logger = logging.getLogger(__name__)


class NodeEntryCollector:
    """CLI 브릿지 스크립트를 실행해 엔트리 JSON을 받아온다.

    stdout은 엔트리 배열 JSON 전용이고, 진행 로그는 stderr로 들어온다.
    """

    def __init__(
        self,
        node_executable: str,
        script_path: Path,
        timeout_seconds: int = 900,
    ) -> None:
        self._node_executable = node_executable
        self._script_path = Path(script_path)
        self._timeout_seconds = timeout_seconds

    async def collect(self, request: CollectRequest) -> list[EntryRecord]:
        """수집 스크립트를 실행하고 엔트리 목록으로 변환한다.

        :raises SourceFetchError: 프로세스 실패, 시간 초과, 출력 파싱 실패
        """
        payload = json.dumps(request.model_dump(), ensure_ascii=False)
        process = await asyncio.create_subprocess_exec(
            self._node_executable,
            str(self._script_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(payload.encode("utf-8")),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            raise SourceFetchError(
                f"엔트리 수집이 {self._timeout_seconds}초 안에 끝나지 않아 중단했습니다."
            ) from exc

        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if stderr_text:
            logger.info("수집기 진행 로그: %s", stderr_text)

        if process.returncode != 0:
            raise SourceFetchError(
                f"엔트리 수집 프로세스가 비정상 종료했습니다(코드 {process.returncode}): "
                f"{stderr_text or '추가 정보 없음'}"
            )

        try:
            raw_entries = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceFetchError(f"수집 결과 JSON을 해석하지 못했습니다: {exc}") from exc

        records = [EntryRecord.model_validate(item) for item in raw_entries]
        if request.corp_code:
            # 상세검색 목록은 기업 필터를 지원하지 않아 수집 후 걸러낸다.
            records = [record for record in records if record.corp_code == request.corp_code]
        return records
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_node_entry_collector.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Node CLI 브릿지 작성**

`packages/entry-extractor/bin/collect-entries.js`:

```javascript
#!/usr/bin/env node
// Python Admin 수집기가 호출하는 CLI 브릿지.
// stdin으로 JSON 파라미터를 받고, stdout에는 엔트리 배열 JSON만 출력한다.
// 진행 로그는 stdout을 오염시키지 않도록 stderr로 보낸다.
const { collectEntries } = require('../src');

function readStdin() {
  return new Promise((resolve, reject) => {
    let buffer = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      buffer += chunk;
    });
    process.stdin.on('end', () => resolve(buffer));
    process.stdin.on('error', reject);
  });
}

async function main() {
  const raw = await readStdin();
  const params = raw.trim() ? JSON.parse(raw) : {};

  if (!params.report_type) throw new Error('report_type은 필수입니다.');
  if (!params.start_date || !params.end_date) {
    throw new Error('start_date/end_date는 필수입니다 (YYYYMMDD).');
  }

  const entries = await collectEntries({
    reportType: params.report_type,
    startDate: params.start_date,
    endDate: params.end_date,
    maxTotal: params.max_total ?? null,
    includeAttachments: params.include_attachments ?? true,
    onEntry: (info) => {
      process.stderr.write(
        `[수집] ${info.disclosure.corp_name} ${info.disclosure.report_nm} → ${info.entryCount}건\n`
      );
    },
  });

  process.stdout.write(JSON.stringify(entries));
}

main().catch((err) => {
  process.stderr.write(`수집 실패: ${err.message}\n`);
  process.exit(1);
});
```

- [ ] **Step 7: 브릿지 문법 검사**

Run (모노레포 루트):

```bash
node --check packages/entry-extractor/bin/collect-entries.js
```

Expected: 출력 없음, 종료 코드 0

- [ ] **Step 8: entry-extractor README에 브릿지 절 추가**

`packages/entry-extractor/README.md`의 `## 예제 실행` 절 바로 앞에 다음 내용을 추가한다.

```markdown
## CLI 브릿지 (Python 연동)

`bin/collect-entries.js`는 Python Admin 수집기가 호출하는 브릿지입니다.
stdin으로 JSON 파라미터를 받고, stdout에는 엔트리 배열 JSON만 출력합니다(진행 로그는 stderr).

```bash
echo '{"report_type":"F001","start_date":"20260724","end_date":"20260724","max_total":2}' | node bin/collect-entries.js
```

| 파라미터 | 설명 |
|----------|------|
| `report_type` | 공시 유형 (필수) |
| `start_date` / `end_date` | YYYYMMDD (필수) |
| `max_total` | 최대 수집 건수 (옵션) |
| `include_attachments` | 첨부 포함 여부 (기본 true) |
```

- [ ] **Step 9: 커밋**

```bash
git add packages/entry-extractor packages/web-api
git commit -m "feat: add Node collect-entries CLI bridge and Python collector adapter"
```

---

## Task 10: ViewerService (Lazy Retrieval)

**Files:**
- Create: `packages/web-api/app/schemas/viewer.py`
- Create: `packages/web-api/app/services/__init__.py`
- Create: `packages/web-api/app/services/viewer_service.py`
- Test: `packages/web-api/tests/test_viewer_service.py`

**Interfaces:**
- Consumes: `EntryRepository`, `DartHttpClient`, `extract_text`, `extract_tables`, `CatalogNotFound`, `SourceFetchError`
- Produces:
  - `app.schemas.viewer.TableData`: `headers: list[str]`, `rows: list[list[str]]`
  - `app.schemas.viewer.SectionContent`: `entry_id`, `source`, `dcm_no`, `ele_id`, `path`, `document_name`, `section_name`, `text: str | None`, `tables: list[TableData]`, `error: str | None`
  - `app.schemas.viewer.DisclosureMeta`: `corp_name`, `corp_code`, `report_nm`, `rcept_dt`
  - `app.schemas.viewer.DisclosureContent`: `rcp_no: str`, `meta: DisclosureMeta`, `sections: list[SectionContent]`
  - `app.services.viewer_service.ViewerService(entries: EntryRepository, http: DartHttpClient, concurrency: int = 4)`
  - `async get_disclosure(rcept_no: str) -> DisclosureContent` — 모든 leaf 파싱, 전부 실패 시 `SourceFetchError`
  - `async get_section(rcept_no: str, entry_id: str) -> SectionContent` — 실패 시 예외 전파

- [ ] **Step 1: 실패하는 테스트 작성**

`packages/web-api/tests/test_viewer_service.py`:

```python
"""ViewerService 전체/단일 조회와 부분 실패 처리 테스트."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import pytest

from app.adapters.dart_http import DartHttpClient
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import CatalogNotFound, SourceFetchError
from app.repositories.entry_repository import EntryRepository
from app.schemas.entry import EntryRecord
from app.services.viewer_service import ViewerService

BODY_HTML = (
    "<html><body><p>재무상태표</p>"
    "<table><tr><th>과목</th><th>당기</th></tr>"
    "<tr><td>자산총계</td><td>1,000</td></tr></table></body></html>"
)


def _record(entry_id: str, path: str) -> EntryRecord:
    return EntryRecord(
        entry_id=entry_id,
        rcept_no="20260724000650",
        corp_code="00224628",
        corp_name="제이에스어소시에이츠",
        report_nm="감사보고서",
        rcept_dt="2026.07.24",
        source="body",
        dcm_no="11495035",
        ele_id=entry_id.rsplit("_", 1)[-1],
        document_name="감사보고서",
        section_name="재무상태표",
        path=["감사보고서", "재무상태표"],
        viewer_url=f"https://dart.fss.or.kr/report/viewer.do?{path}",
    )


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        await EntryRepository(session).upsert_many(
            [_record("e_1", "ok=1"), _record("e_2", "fail=1")]
        )
        await session.commit()
    yield sessionmaker
    await engine.dispose()


def _transport(fail_query: str | None = "fail=1") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if fail_query and fail_query in str(request.url):
            return httpx.Response(500, content=b"error")
        return httpx.Response(
            200, content=BODY_HTML.encode("euc-kr"), headers={"Content-Type": "text/html"}
        )

    return httpx.MockTransport(handler)


@asynccontextmanager
async def _service(sessionmaker, transport: httpx.MockTransport):
    """세션과 httpx 클라이언트를 정리하는 ViewerService 컨텍스트."""
    async with sessionmaker() as session, httpx.AsyncClient(transport=transport) as client:
        fetcher = DartHttpClient(client, max_retries=0, retry_backoff_seconds=0.0)
        yield ViewerService(EntryRepository(session), fetcher, concurrency=2)


async def test_get_disclosure_returns_all_leaf_sections(sessionmaker_fixture) -> None:
    async with _service(sessionmaker_fixture, _transport(fail_query=None)) as service:
        content = await service.get_disclosure("20260724000650")

    assert content.rcp_no == "20260724000650"
    assert content.meta.corp_name == "제이에스어소시에이츠"
    assert [section.entry_id for section in content.sections] == ["e_1", "e_2"]
    assert "재무상태표" in (content.sections[0].text or "")
    assert content.sections[0].tables[0].headers == ["과목", "당기"]
    assert all(section.error is None for section in content.sections)


async def test_get_disclosure_reports_partial_failure(sessionmaker_fixture) -> None:
    async with _service(sessionmaker_fixture, _transport()) as service:
        content = await service.get_disclosure("20260724000650")

    assert content.sections[0].error is None
    assert content.sections[1].error is not None
    assert content.sections[1].text is None


async def test_get_disclosure_raises_when_all_sections_fail(sessionmaker_fixture) -> None:
    async with _service(sessionmaker_fixture, _transport(fail_query="viewer.do")) as service:
        with pytest.raises(SourceFetchError):
            await service.get_disclosure("20260724000650")


async def test_get_disclosure_raises_for_unknown_rcept_no(sessionmaker_fixture) -> None:
    async with _service(sessionmaker_fixture, _transport(fail_query=None)) as service:
        with pytest.raises(CatalogNotFound):
            await service.get_disclosure("99999999999999")


async def test_get_section_returns_single_leaf(sessionmaker_fixture) -> None:
    async with _service(sessionmaker_fixture, _transport(fail_query=None)) as service:
        section = await service.get_section("20260724000650", "e_1")

    assert section.entry_id == "e_1"
    assert "재무상태표" in (section.text or "")


async def test_get_section_rejects_entry_from_other_disclosure(sessionmaker_fixture) -> None:
    async with _service(sessionmaker_fixture, _transport(fail_query=None)) as service:
        with pytest.raises(CatalogNotFound):
            await service.get_section("11111111111111", "e_1")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_viewer_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services'`

- [ ] **Step 3: Viewer 응답 스키마 구현**

`packages/web-api/app/schemas/viewer.py`:

```python
"""Viewer 응답 스키마. 원문 정제 결과를 담는다."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TableData(BaseModel):
    """표 하나를 헤더와 행으로 표현한다."""

    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class SectionContent(BaseModel):
    """leaf 섹션 1건의 정제 결과."""

    entry_id: str
    source: str
    dcm_no: str | None = None
    ele_id: str | None = None
    path: list[str] = Field(default_factory=list)
    document_name: str | None = None
    section_name: str | None = None
    text: str | None = None
    tables: list[TableData] = Field(default_factory=list)
    error: str | None = None


class DisclosureMeta(BaseModel):
    """공시 단위 메타데이터."""

    corp_name: str | None = None
    corp_code: str | None = None
    report_nm: str | None = None
    rcept_dt: str | None = None


class DisclosureContent(BaseModel):
    """접수번호 하나에 속한 모든 leaf 섹션의 정제 결과."""

    rcp_no: str
    meta: DisclosureMeta
    sections: list[SectionContent] = Field(default_factory=list)
```

- [ ] **Step 4: ViewerService 구현**

`packages/web-api/app/services/__init__.py`: 빈 파일.

`packages/web-api/app/services/viewer_service.py`:

```python
"""Lazy Retrieval Viewer 서비스. 조회 시점에 원문을 가져와 정제한다."""

from __future__ import annotations

import asyncio
import logging

from app.adapters.dart_http import DartHttpClient
from app.errors import CatalogNotFound, DartWrapperError, SourceFetchError
from app.models.entry import Entry
from app.parsing.cleaner import extract_text
from app.parsing.tables import extract_tables
from app.repositories.entry_repository import EntryRepository
from app.schemas.viewer import DisclosureContent, DisclosureMeta, SectionContent, TableData

logger = logging.getLogger(__name__)


class ViewerService:
    """카탈로그 엔트리의 viewer_url로 원문을 수집·정제한다."""

    def __init__(
        self,
        entries: EntryRepository,
        http: DartHttpClient,
        concurrency: int = 4,
    ) -> None:
        self._entries = entries
        self._http = http
        self._concurrency = concurrency

    async def get_disclosure(self, rcept_no: str) -> DisclosureContent:
        """접수번호에 속한 모든 leaf 섹션을 정제해 반환한다.

        일부 섹션이 실패하면 해당 섹션에만 error를 담고 나머지는 정상 반환한다.

        :raises CatalogNotFound: 카탈로그에 해당 접수번호가 없는 경우
        :raises SourceFetchError: 모든 섹션의 원문 수집이 실패한 경우
        """
        entries = await self._entries.list_by_rcept_no(rcept_no)
        if not entries:
            raise CatalogNotFound(
                f"접수번호 {rcept_no}에 해당하는 카탈로그 항목이 없습니다. "
                "먼저 Admin 수집을 실행해 주세요."
            )

        semaphore = asyncio.Semaphore(self._concurrency)
        sections = await asyncio.gather(
            *(self._load_section(entry, semaphore) for entry in entries)
        )

        if all(section.error is not None for section in sections):
            raise SourceFetchError(
                f"접수번호 {rcept_no}의 모든 구성 문서 원문을 가져오지 못했습니다."
            )

        return DisclosureContent(
            rcp_no=rcept_no,
            meta=DisclosureMeta(
                corp_name=entries[0].corp_name,
                corp_code=entries[0].corp_code,
                report_nm=entries[0].report_nm,
                rcept_dt=entries[0].rcept_dt,
            ),
            sections=list(sections),
        )

    async def get_section(self, rcept_no: str, entry_id: str) -> SectionContent:
        """특정 leaf 섹션 하나만 정제해 반환한다.

        :raises CatalogNotFound: 엔트리가 없거나 해당 접수번호에 속하지 않는 경우
        :raises SourceFetchError: 원문 수집이 실패한 경우
        """
        entry = await self._entries.get_by_entry_id(entry_id)
        if entry is None or entry.rcept_no != rcept_no:
            raise CatalogNotFound(
                f"접수번호 {rcept_no}에서 섹션 {entry_id}을(를) 찾을 수 없습니다."
            )

        html = await self._fetch_html(entry)
        return self._to_section(entry, html=html)

    async def _load_section(self, entry: Entry, semaphore: asyncio.Semaphore) -> SectionContent:
        """동시 요청 수를 제한하며 섹션 하나를 정제한다. 실패는 error로 담는다."""
        async with semaphore:
            try:
                html = await self._fetch_html(entry)
            except DartWrapperError as exc:
                logger.warning("섹션 원문 수집 실패(%s): %s", entry.entry_id, exc)
                return self._to_section(entry, error=str(exc))

            try:
                return self._to_section(entry, html=html)
            except DartWrapperError as exc:
                logger.warning("섹션 정제 실패(%s): %s", entry.entry_id, exc)
                return self._to_section(entry, error=str(exc))

    async def _fetch_html(self, entry: Entry) -> str:
        """엔트리의 viewer_url로 원문 HTML을 가져온다."""
        if not entry.viewer_url:
            raise SourceFetchError(f"섹션 {entry.entry_id}에 원문 주소가 없습니다.")
        return await self._http.fetch_html(entry.viewer_url)

    def _to_section(
        self,
        entry: Entry,
        html: str | None = None,
        error: str | None = None,
    ) -> SectionContent:
        """엔트리 메타와 정제 결과를 합쳐 응답 모델을 만든다."""
        text = extract_text(html) if html is not None else None
        tables = (
            [TableData(**table) for table in extract_tables(html)] if html is not None else []
        )
        return SectionContent(
            entry_id=entry.entry_id,
            source=entry.source,
            dcm_no=entry.dcm_no,
            ele_id=entry.ele_id,
            path=list(entry.path or []),
            document_name=entry.document_name,
            section_name=entry.section_name,
            text=text,
            tables=tables,
            error=error,
        )
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_viewer_service.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: 커밋**

```bash
git add packages/web-api
git commit -m "feat(web-api): add ViewerService with lazy retrieval and partial failure handling"
```

---

## Task 11: Viewer 라우터 · 의존성 주입 · 앱 lifespan

**Files:**
- Create: `packages/web-api/app/api/__init__.py`
- Create: `packages/web-api/app/api/deps.py`
- Create: `packages/web-api/app/api/v1/__init__.py`
- Create: `packages/web-api/app/api/v1/viewer.py`
- Modify: `packages/web-api/app/main.py`
- Test: `packages/web-api/tests/test_viewer_api.py`

**Interfaces:**
- Consumes: `ViewerService`, `DisclosureContent`, `SectionContent`, `CatalogNotFound`, `SourceFetchError`, `Settings`
- Produces:
  - `app.api.deps.get_settings_dep() -> Settings`
  - `app.api.deps.get_session(request: Request) -> AsyncIterator[AsyncSession]`
  - `app.api.deps.get_viewer_service(...) -> ViewerService`
  - `app.api.v1.viewer.router` — prefix `/api/v1/viewer`
  - `GET /api/v1/viewer/{rcp_no}` → `DisclosureContent`
  - `GET /api/v1/viewer/{rcp_no}/sections/{entry_id}` → `SectionContent`
  - `app.main.create_app()` lifespan: `app.state.engine`, `app.state.sessionmaker`, `app.state.http_client`, `app.state.entry_collector`

- [ ] **Step 1: 실패하는 테스트 작성**

`packages/web-api/tests/test_viewer_api.py`:

```python
"""Viewer 라우터 테스트. 서비스는 가짜 구현으로 대체한다."""

from __future__ import annotations

import pytest

from app.api.deps import get_viewer_service
from app.errors import CatalogNotFound, SourceFetchError
from app.main import create_app
from app.schemas.viewer import DisclosureContent, DisclosureMeta, SectionContent, TableData

SECTION = SectionContent(
    entry_id="e_1",
    source="body",
    dcm_no="11495035",
    ele_id="5",
    path=["감사보고서", "재무상태표"],
    document_name="감사보고서",
    section_name="재무상태표",
    text="재무상태표\n자산총계 1,000",
    tables=[TableData(headers=["과목", "당기"], rows=[["자산총계", "1,000"]])],
)


class FakeViewerService:
    """정상 응답을 돌려주는 가짜 서비스."""

    async def get_disclosure(self, rcept_no: str) -> DisclosureContent:
        return DisclosureContent(
            rcp_no=rcept_no,
            meta=DisclosureMeta(corp_name="제이에스어소시에이츠", report_nm="감사보고서"),
            sections=[SECTION],
        )

    async def get_section(self, rcept_no: str, entry_id: str) -> SectionContent:
        return SECTION


class RaisingViewerService:
    """지정한 예외를 던지는 가짜 서비스."""

    def __init__(self, exception: Exception) -> None:
        self._exception = exception

    async def get_disclosure(self, rcept_no: str) -> DisclosureContent:
        raise self._exception

    async def get_section(self, rcept_no: str, entry_id: str) -> SectionContent:
        raise self._exception


def _app_with(service: object):
    app = create_app()
    app.dependency_overrides[get_viewer_service] = lambda: service
    return app


async def test_get_disclosure_returns_all_sections(client_factory) -> None:
    async with client_factory(_app_with(FakeViewerService())) as client:
        response = await client.get("/api/v1/viewer/20260724000650")

    body = response.json()
    assert response.status_code == 200
    assert body["rcp_no"] == "20260724000650"
    assert body["meta"]["corp_name"] == "제이에스어소시에이츠"
    assert body["sections"][0]["tables"][0]["headers"] == ["과목", "당기"]


async def test_get_section_returns_single_section(client_factory) -> None:
    async with client_factory(_app_with(FakeViewerService())) as client:
        response = await client.get("/api/v1/viewer/20260724000650/sections/e_1")

    assert response.status_code == 200
    assert response.json()["entry_id"] == "e_1"


@pytest.mark.parametrize(
    ("exception", "expected_status"),
    [
        (CatalogNotFound("카탈로그에 없습니다."), 404),
        (SourceFetchError("원문을 가져오지 못했습니다."), 502),
    ],
)
async def test_viewer_errors_map_to_status(
    client_factory, exception: Exception, expected_status: int
) -> None:
    async with client_factory(_app_with(RaisingViewerService(exception))) as client:
        response = await client.get("/api/v1/viewer/20260724000650")

    assert response.status_code == expected_status
    assert response.json() == {"detail": str(exception)}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_viewer_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api'`

- [ ] **Step 3: 의존성 모듈 구현**

`packages/web-api/app/api/__init__.py`: 빈 파일.

`packages/web-api/app/api/deps.py`:

```python
"""FastAPI 의존성 정의. 앱 상태(state)에 있는 자원을 요청 단위로 꺼내 쓴다."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.dart_http import DartHttpClient
from app.config import Settings, get_settings
from app.repositories.entry_repository import EntryRepository
from app.services.viewer_service import ViewerService


def get_settings_dep() -> Settings:
    """설정 객체를 반환한다."""
    return get_settings()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """요청 단위 DB 세션을 제공한다."""
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


def get_entry_repository(session: AsyncSession = Depends(get_session)) -> EntryRepository:
    """엔트리 저장소를 제공한다."""
    return EntryRepository(session)


def get_viewer_service(
    request: Request,
    entries: EntryRepository = Depends(get_entry_repository),
    settings: Settings = Depends(get_settings_dep),
) -> ViewerService:
    """Viewer 서비스를 제공한다. httpx 클라이언트는 앱 전체에서 재사용한다."""
    http = DartHttpClient(
        request.app.state.http_client,
        timeout_seconds=settings.dart_fetch_timeout_seconds,
        max_retries=settings.dart_fetch_max_retries,
    )
    return ViewerService(entries, http, concurrency=settings.dart_fetch_concurrency)
```

- [ ] **Step 4: Viewer 라우터 구현**

`packages/web-api/app/api/v1/__init__.py`: 빈 파일.

`packages/web-api/app/api/v1/viewer.py`:

```python
"""Public Viewer 라우터. 조회 시점에 원문을 정제해 반환한다."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_viewer_service
from app.schemas.viewer import DisclosureContent, SectionContent
from app.services.viewer_service import ViewerService

router = APIRouter(prefix="/api/v1/viewer", tags=["Viewer"])


@router.get("/{rcp_no}", response_model=DisclosureContent, summary="공시 전체 원문 조회")
async def read_disclosure(
    rcp_no: str,
    service: ViewerService = Depends(get_viewer_service),
) -> DisclosureContent:
    """접수번호에 속한 모든 leaf 섹션의 정제 결과를 반환한다(종합 분석용)."""
    return await service.get_disclosure(rcp_no)


@router.get(
    "/{rcp_no}/sections/{entry_id}",
    response_model=SectionContent,
    summary="특정 leaf 섹션 원문 조회",
)
async def read_section(
    rcp_no: str,
    entry_id: str,
    service: ViewerService = Depends(get_viewer_service),
) -> SectionContent:
    """특정 leaf 섹션 하나의 정제 결과를 반환한다(빠른 단건 조회)."""
    return await service.get_section(rcp_no, entry_id)
```

- [ ] **Step 5: main.py에 lifespan과 라우터 등록**

`packages/web-api/app/main.py` 전체를 다음으로 교체한다.

```python
"""FastAPI 앱 생성, 자원 수명주기 관리, 라우터 등록."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.adapters.node_entry_collector import NodeEntryCollector
from app.api.v1 import viewer
from app.config import get_settings
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import register_exception_handlers

# DART는 일반 브라우저 요청과 유사한 헤더를 기대한다.
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://dart.fss.or.kr/",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """DB 엔진, HTTP 클라이언트, 수집 어댑터를 앱 수명 동안 공유한다."""
    settings = get_settings()

    engine = create_db_engine(settings.database_url)
    await create_all(engine)

    http_client = httpx.AsyncClient(headers=_DEFAULT_HEADERS, follow_redirects=True)

    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.http_client = http_client
    app.state.entry_collector = NodeEntryCollector(
        settings.node_executable,
        settings.entry_collector_script,
        timeout_seconds=settings.collector_timeout_seconds,
    )

    try:
        yield
    finally:
        await http_client.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    """DART 공시 파이프라인 API 앱을 생성한다."""
    app = FastAPI(
        title="DART 공시 파이프라인 API",
        description="Admin 카탈로그 수집과 Public Viewer(Lazy Retrieval)를 제공합니다.",
        version="0.1.0",
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.include_router(viewer.router)

    @app.get("/health", tags=["시스템"])
    async def health() -> dict[str, str]:
        """서비스 생존 여부를 반환한다."""
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -v`
Expected: PASS (전체 통과, 실패 0)

- [ ] **Step 7: 커밋**

```bash
git add packages/web-api
git commit -m "feat(web-api): add viewer routes with shared HTTP client and DB lifespan"
```

---

## Task 12: CatalogService · Admin 라우터

**Files:**
- Create: `packages/web-api/app/schemas/catalog.py`
- Create: `packages/web-api/app/services/catalog_service.py`
- Create: `packages/web-api/app/api/admin/__init__.py`
- Create: `packages/web-api/app/api/admin/catalog.py`
- Modify: `packages/web-api/app/api/deps.py`
- Modify: `packages/web-api/app/main.py`
- Test: `packages/web-api/tests/test_catalog_service.py`
- Test: `packages/web-api/tests/test_catalog_api.py`

**Interfaces:**
- Consumes: `EntryCollector`, `CollectRequest`, `EntryRepository`, `JobRepository`
- Produces:
  - `app.schemas.catalog.ExtractRequest` — `CollectRequest`와 동일 필드
  - `app.schemas.catalog.ExtractResponse`: `job_id: str`, `status: str`
  - `app.schemas.catalog.JobLogItem`: `level: str`, `message: str`, `created_at: datetime`
  - `app.schemas.catalog.JobStatusResponse`: `job_id`, `status`, `params: dict`, `total_entries: int`, `saved_entries: int`, `error_message: str | None`, `started_at`, `finished_at`, `logs: list[JobLogItem]`
  - `app.services.catalog_service.CatalogService(sessionmaker, collector)`
  - `async start_extract(request: ExtractRequest) -> ExtractResponse`
  - `async run_job(job_id: str, request: ExtractRequest) -> None`
  - `async get_status(job_id: str) -> JobStatusResponse`
  - `app.api.deps.get_catalog_service(request: Request) -> CatalogService`
  - `app.api.admin.catalog.router` — prefix `/admin/catalog`

- [ ] **Step 1: 서비스 실패 테스트 작성**

`packages/web-api/tests/test_catalog_service.py`:

```python
"""CatalogService 수집 실행·상태 조회 테스트."""

from __future__ import annotations

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.errors import CatalogNotFound, SourceFetchError
from app.ports.entry_collector import CollectRequest
from app.schemas.catalog import ExtractRequest
from app.schemas.entry import EntryRecord
from app.services.catalog_service import CatalogService

REQUEST = ExtractRequest(report_type="F001", start_date="20260724", end_date="20260724")


class FakeCollector:
    """고정 엔트리를 반환하는 가짜 수집기."""

    def __init__(self) -> None:
        self.calls: list[CollectRequest] = []

    async def collect(self, request: CollectRequest) -> list[EntryRecord]:
        self.calls.append(request)
        return [
            EntryRecord(
                entry_id="e_1",
                rcept_no="20260724000650",
                source="body",
                section_name="재무상태표",
                path=["감사보고서", "재무상태표"],
                viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=1",
            )
        ]


class FailingCollector:
    """항상 실패하는 가짜 수집기."""

    async def collect(self, request: CollectRequest) -> list[EntryRecord]:
        raise SourceFetchError("엔트리 수집 프로세스가 비정상 종료했습니다(코드 1)")


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


async def test_start_extract_creates_pending_job(sessionmaker_fixture) -> None:
    service = CatalogService(sessionmaker_fixture, FakeCollector())

    response = await service.start_extract(REQUEST)

    assert response.status == "pending"
    assert response.job_id


async def test_start_extract_reuses_active_job(sessionmaker_fixture) -> None:
    service = CatalogService(sessionmaker_fixture, FakeCollector())

    first = await service.start_extract(REQUEST)
    second = await service.start_extract(REQUEST)

    assert first.job_id == second.job_id


async def test_run_job_saves_entries_and_marks_success(sessionmaker_fixture) -> None:
    collector = FakeCollector()
    service = CatalogService(sessionmaker_fixture, collector)
    response = await service.start_extract(REQUEST)

    await service.run_job(response.job_id, REQUEST)
    status = await service.get_status(response.job_id)

    assert status.status == "succeeded"
    assert (status.total_entries, status.saved_entries) == (1, 1)
    assert collector.calls[0].report_type == "F001"
    assert any("수집" in log.message for log in status.logs)


async def test_run_job_marks_failure_with_message(sessionmaker_fixture) -> None:
    service = CatalogService(sessionmaker_fixture, FailingCollector())
    response = await service.start_extract(REQUEST)

    await service.run_job(response.job_id, REQUEST)
    status = await service.get_status(response.job_id)

    assert status.status == "failed"
    assert status.error_message is not None
    assert any(log.level == "error" for log in status.logs)


async def test_get_status_raises_for_unknown_job(sessionmaker_fixture) -> None:
    service = CatalogService(sessionmaker_fixture, FakeCollector())

    with pytest.raises(CatalogNotFound):
        await service.get_status("없는-작업")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_catalog_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.schemas.catalog'`

- [ ] **Step 3: Admin 스키마 구현**

`packages/web-api/app/schemas/catalog.py`:

```python
"""Admin 카탈로그 수집 요청·응답 스키마."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.ports.entry_collector import CollectRequest


class ExtractRequest(CollectRequest):
    """수집 트리거 요청. 수집 포트 요청과 동일한 범위를 받는다."""


class ExtractResponse(BaseModel):
    """수집 트리거 응답. 즉시 반환된다."""

    job_id: str
    status: str


class JobLogItem(BaseModel):
    """수집 진행 로그 한 줄."""

    model_config = ConfigDict(from_attributes=True)

    level: str
    message: str
    created_at: datetime


class JobStatusResponse(BaseModel):
    """수집 작업 현황과 최근 로그."""

    job_id: str
    status: str
    params: dict[str, Any] = Field(default_factory=dict)
    total_entries: int = 0
    saved_entries: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    logs: list[JobLogItem] = Field(default_factory=list)
```

- [ ] **Step 4: CatalogService 구현**

`packages/web-api/app/services/catalog_service.py`:

```python
"""Admin 카탈로그 수집 서비스. 백그라운드 실행과 상태 추적을 담당한다."""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.errors import CatalogNotFound
from app.ports.entry_collector import EntryCollector
from app.repositories.entry_repository import EntryRepository
from app.repositories.job_repository import JobRepository
from app.schemas.catalog import ExtractRequest, ExtractResponse, JobLogItem, JobStatusResponse

logger = logging.getLogger(__name__)


def _params_key(request: ExtractRequest) -> str:
    """같은 범위의 중복 수집을 판별하기 위한 정규화 키를 만든다."""
    return json.dumps(request.model_dump(), sort_keys=True, ensure_ascii=False)


class CatalogService:
    """수집 작업을 만들고, 백그라운드에서 실행하며, 현황을 조회한다."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        collector: EntryCollector,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._collector = collector

    async def start_extract(self, request: ExtractRequest) -> ExtractResponse:
        """수집 작업을 등록한다. 같은 범위가 진행 중이면 기존 작업을 돌려준다."""
        params_key = _params_key(request)

        async with self._sessionmaker() as session:
            jobs = JobRepository(session)
            existing = await jobs.find_active(params_key)
            if existing is not None:
                logger.info("이미 진행 중인 수집 작업을 재사용합니다: %s", existing.job_id)
                return ExtractResponse(job_id=existing.job_id, status=existing.status)

            job_id = uuid.uuid4().hex
            await jobs.create(job_id, request.model_dump(mode="json"), params_key)
            await jobs.add_log(job_id, "info", "수집 작업을 등록했습니다.")
            await session.commit()

        return ExtractResponse(job_id=job_id, status="pending")

    async def run_job(self, job_id: str, request: ExtractRequest) -> None:
        """백그라운드에서 실제 수집을 수행한다. 예외는 작업 상태로 기록한다."""
        async with self._sessionmaker() as session:
            jobs = JobRepository(session)
            await jobs.mark_running(job_id)
            await jobs.add_log(job_id, "info", "엔트리 수집을 시작합니다.")
            await session.commit()

        try:
            records = await self._collector.collect(request)
        except Exception as exc:  # 수집 실패는 작업 실패로 남기고 서버는 계속 동작한다.
            logger.exception("수집 작업 실패: %s", job_id)
            async with self._sessionmaker() as session:
                jobs = JobRepository(session)
                await jobs.mark_failed(job_id, str(exc))
                await jobs.add_log(job_id, "error", f"수집에 실패했습니다: {exc}")
                await session.commit()
            return

        async with self._sessionmaker() as session:
            jobs = JobRepository(session)
            saved = await EntryRepository(session).upsert_many(records)
            await jobs.mark_succeeded(job_id, total_entries=len(records), saved_entries=saved)
            await jobs.add_log(job_id, "info", f"엔트리 {saved}건을 카탈로그에 저장했습니다.")
            await session.commit()

    async def get_status(self, job_id: str) -> JobStatusResponse:
        """작업 현황과 최근 로그를 반환한다.

        :raises CatalogNotFound: 해당 작업이 없는 경우
        """
        async with self._sessionmaker() as session:
            jobs = JobRepository(session)
            job = await jobs.get(job_id)
            if job is None:
                raise CatalogNotFound(f"수집 작업을 찾을 수 없습니다: {job_id}")
            logs = await jobs.recent_logs(job_id)

        return JobStatusResponse(
            job_id=job.job_id,
            status=job.status,
            params=job.params,
            total_entries=job.total_entries,
            saved_entries=job.saved_entries,
            error_message=job.error_message,
            started_at=job.started_at,
            finished_at=job.finished_at,
            logs=[JobLogItem.model_validate(log) for log in logs],
        )
```

- [ ] **Step 5: 서비스 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_catalog_service.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: 라우터 실패 테스트 작성**

`packages/web-api/tests/test_catalog_api.py`:

```python
"""Admin 카탈로그 라우터 테스트. 서비스는 가짜 구현으로 대체한다."""

from __future__ import annotations

from app.api.deps import get_catalog_service
from app.errors import CatalogNotFound
from app.main import create_app
from app.schemas.catalog import ExtractRequest, ExtractResponse, JobStatusResponse

PAYLOAD = {"report_type": "F001", "start_date": "20260724", "end_date": "20260724"}


class FakeCatalogService:
    """작업 등록과 실행 호출을 기록하는 가짜 서비스."""

    def __init__(self, status: str = "pending") -> None:
        self._status = status
        self.executed: list[str] = []

    async def start_extract(self, request: ExtractRequest) -> ExtractResponse:
        return ExtractResponse(job_id="job-1", status=self._status)

    async def run_job(self, job_id: str, request: ExtractRequest) -> None:
        self.executed.append(job_id)

    async def get_status(self, job_id: str) -> JobStatusResponse:
        if job_id != "job-1":
            raise CatalogNotFound(f"수집 작업을 찾을 수 없습니다: {job_id}")
        return JobStatusResponse(job_id=job_id, status="succeeded", total_entries=3, saved_entries=3)


def _app_with(service: object):
    app = create_app()
    app.dependency_overrides[get_catalog_service] = lambda: service
    return app


async def test_extract_accepts_request_and_schedules_job(client_factory) -> None:
    service = FakeCatalogService()

    async with client_factory(_app_with(service)) as client:
        response = await client.post("/admin/catalog/extract", json=PAYLOAD)

    assert response.status_code == 202
    assert response.json() == {"job_id": "job-1", "status": "pending"}
    assert service.executed == ["job-1"]


async def test_extract_does_not_reschedule_running_job(client_factory) -> None:
    service = FakeCatalogService(status="running")

    async with client_factory(_app_with(service)) as client:
        response = await client.post("/admin/catalog/extract", json=PAYLOAD)

    assert response.status_code == 202
    assert response.json()["status"] == "running"
    assert service.executed == []


async def test_extract_rejects_invalid_date(client_factory) -> None:
    async with client_factory(_app_with(FakeCatalogService())) as client:
        response = await client.post(
            "/admin/catalog/extract", json={**PAYLOAD, "start_date": "2026-07-24"}
        )

    assert response.status_code == 422


async def test_status_returns_job_progress(client_factory) -> None:
    async with client_factory(_app_with(FakeCatalogService())) as client:
        response = await client.get("/admin/catalog/status", params={"job_id": "job-1"})

    assert response.status_code == 200
    assert response.json()["saved_entries"] == 3


async def test_status_returns_404_for_unknown_job(client_factory) -> None:
    async with client_factory(_app_with(FakeCatalogService())) as client:
        response = await client.get("/admin/catalog/status", params={"job_id": "job-9"})

    assert response.status_code == 404
```

- [ ] **Step 7: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_catalog_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_catalog_service' from 'app.api.deps'`

- [ ] **Step 8: deps에 CatalogService 의존성 추가**

`packages/web-api/app/api/deps.py`의 import 절에 다음을 추가한다.

```python
from app.services.catalog_service import CatalogService
```

파일 끝에 다음 함수를 추가한다.

```python
def get_catalog_service(request: Request) -> CatalogService:
    """Admin 카탈로그 서비스를 제공한다.

    백그라운드 작업이 요청 세션 수명에 묶이지 않도록 세션메이커를 직접 넘긴다.
    """
    return CatalogService(
        request.app.state.sessionmaker,
        request.app.state.entry_collector,
    )
```

- [ ] **Step 9: Admin 라우터 구현**

`packages/web-api/app/api/admin/__init__.py`: 빈 파일.

`packages/web-api/app/api/admin/catalog.py`:

```python
"""Admin 카탈로그 수집 라우터."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.api.deps import get_catalog_service
from app.schemas.catalog import ExtractRequest, ExtractResponse, JobStatusResponse
from app.services.catalog_service import CatalogService

router = APIRouter(prefix="/admin/catalog", tags=["Admin"])


@router.post(
    "/extract",
    response_model=ExtractResponse,
    status_code=202,
    summary="기간/기업별 공시 수집 트리거",
)
async def extract_catalog(
    payload: ExtractRequest,
    background_tasks: BackgroundTasks,
    service: CatalogService = Depends(get_catalog_service),
) -> ExtractResponse:
    """수집 작업을 등록하고 즉시 job_id를 반환한다. 실제 수집은 백그라운드에서 진행된다."""
    response = await service.start_extract(payload)
    if response.status == "pending":
        background_tasks.add_task(service.run_job, response.job_id, payload)
    return response


@router.get("/status", response_model=JobStatusResponse, summary="수집 현황 및 로그 조회")
async def read_catalog_status(
    job_id: str = Query(description="수집 작업 식별자"),
    service: CatalogService = Depends(get_catalog_service),
) -> JobStatusResponse:
    """수집 작업의 상태·진행 수치·최근 로그를 반환한다."""
    return await service.get_status(job_id)
```

- [ ] **Step 10: main.py에 Admin 라우터 등록**

`packages/web-api/app/main.py`의 import를 수정한다.

```python
from app.api.admin import catalog
from app.api.v1 import viewer
```

`app.include_router(viewer.router)` 위에 다음 줄을 추가한다.

```python
    app.include_router(catalog.router)
```

- [ ] **Step 11: 전체 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -v`
Expected: PASS (전체 통과, 실패 0)

- [ ] **Step 12: 커밋**

```bash
git add packages/web-api
git commit -m "feat(web-api): add admin catalog extract and status endpoints"
```

---

## Task 13: 문서 정리 · 스타일 검증

**Files:**
- Create: `packages/web-api/README.md`
- Create: `packages/web-api/.env.example`
- Create: `packages/web-api/setup.cfg`
- Modify: `README.md` (루트, 구조·모듈 표)
- Modify: `.gitignore` (Python 가상환경·캐시 추가)

**Interfaces:**
- Consumes: 앞선 모든 작업의 결과
- Produces: 실행·배포 문서, lint 설정

- [ ] **Step 1: flake8 설정과 .gitignore 갱신**

`packages/web-api/setup.cfg`:

```ini
[flake8]
max-line-length = 100
extend-ignore = E203
exclude = .venv,__pycache__,.pytest_cache
```

루트 `.gitignore` 끝에 다음을 추가한다.

```gitignore
# Python (web-api)
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
*.egg-info/
packages/web-api/dart_catalog.db
```

- [ ] **Step 2: 스타일 검증 실행**

Run (in `packages/web-api`):

```bash
.venv\Scripts\python.exe -m black --check app tests
.venv\Scripts\python.exe -m flake8 app tests
```

Expected: black은 `All done!`, flake8은 출력 없음. 위반이 있으면 `black app tests`로 정리하고 flake8 지적을 직접 수정한다.

- [ ] **Step 3: 환경변수 예시 작성**

`packages/web-api/.env.example`:

```dotenv
# 개발: 로컬 SQLite
DATABASE_URL=sqlite+aiosqlite:///./dart_catalog.db
# 웹 배포: Neon PostgreSQL (asyncpg extra 설치 필요)
# DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST/DBNAME

NODE_EXECUTABLE=node
COLLECTOR_TIMEOUT_SECONDS=900
DART_FETCH_CONCURRENCY=4
DART_FETCH_TIMEOUT_SECONDS=15
DART_FETCH_MAX_RETRIES=2
```

- [ ] **Step 4: 패키지 README 작성**

`packages/web-api/README.md`:

```markdown
# web-api

DART 공시 파이프라인의 FastAPI 서비스입니다. Admin 카탈로그 수집과 Public Viewer(Lazy Retrieval)를 제공합니다.

## 구조

| 레이어 | 위치 | 역할 |
|--------|------|------|
| API | `app/api` | 라우터·의존성 |
| Service | `app/services` | 수집 오케스트레이션, Viewer 파이프라인 |
| Port/Adapter | `app/ports`, `app/adapters` | 엔트리 수집기, DART HTTP |
| Parsing | `app/parsing` | 본문 정제, 표 → JSON |
| DB | `app/models`, `app/repositories`, `app/db` | 엔트리·작업 메타데이터 |

DB에는 entry 메타데이터만 저장하고, 본문·표는 조회 시점에 `viewer_url`로 가져옵니다.

## 설치

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

PostgreSQL로 배포할 때는 `.venv\Scripts\python.exe -m pip install -e ".[postgres]"`를 추가합니다.

## 실행

```bash
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

문서: http://127.0.0.1:8000/docs

## 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/admin/catalog/extract` | 기간/기업별 수집 트리거 (202, `job_id` 반환) |
| GET | `/admin/catalog/status?job_id=` | 수집 현황·로그 |
| GET | `/api/v1/viewer/{rcp_no}` | 접수번호의 모든 leaf 섹션 원문 (종합 분석용) |
| GET | `/api/v1/viewer/{rcp_no}/sections/{entry_id}` | 특정 leaf 섹션 원문 (단건 조회) |

전체 조회는 일부 섹션이 실패하면 해당 섹션에만 `error`를 담고 나머지는 정상 반환합니다. 모든 섹션이 실패하면 502입니다.

## 엔트리 수집 경로

수집은 Node `@dart-wrapper/entry-extractor`의 CLI 브릿지를 서브프로세스로 호출합니다.
사전에 모노레포 루트에서 `npm install`이 완료되어 있어야 합니다.

## 테스트

```bash
.venv\Scripts\python.exe -m pytest -v
```

테스트는 실제 DART 서버를 호출하지 않습니다(인메모리 SQLite + httpx MockTransport).

## 설정

`.env.example`을 참고해 `.env`를 만듭니다. 개발은 SQLite, 배포는 Neon PostgreSQL을 쓰며 `DATABASE_URL`만 교체하면 됩니다.
```

- [ ] **Step 5: 루트 README 갱신**

루트 `README.md`의 `## 구조` 코드블록을 다음으로 교체한다.

```text
dart-wrapper/
└── packages/
    ├── entry-extractor/   # 공시 컨테이너 → 구성 문서 leaf entry 추출 (Node)
    └── web-api/           # Admin 카탈로그 수집 + Public Viewer API (FastAPI)
```

`## 현재 모듈` 표에 다음 행을 추가한다.

```markdown
| [`web-api`](./packages/web-api) | Admin 수집 트리거·현황 및 Viewer 원문 정제 API |
```

- [ ] **Step 6: 전체 테스트 재확인**

Run (in `packages/web-api`): `.venv\Scripts\python.exe -m pytest -v`
Expected: PASS (전체 통과)

- [ ] **Step 7: 커밋**

```bash
git add README.md packages/web-api
git commit -m "docs(web-api): add package README, env example, and lint config"
```

---

## 검증 체크리스트 (전체 완료 후)

- [ ] `packages/web-api`에서 `python -m pytest -v` 전체 통과
- [ ] `python -m black --check app tests`, `python -m flake8 app tests` 통과
- [ ] `node --check packages/entry-extractor/bin/collect-entries.js` 통과
- [ ] `uvicorn app.main:app` 실행 후 `/docs`에서 네 엔드포인트 노출 확인
- [ ] `.env`의 `DATABASE_URL`을 PostgreSQL로 바꿔도 앱이 기동되는지 확인(선택, Neon 계정 필요)
