# 수집·열람과 연구 흐름 분리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `packages/web-api`의 실행 앱을 로컬 수집·열람과 공개 카탈로그·Viewer 둘로 한정하고, 추출·검토·사이클·업종·Facts는 `packages/research`로 옮겨 어느 앱도 import하지 않게 한다.

**Architecture:** 카탈로그 의존성은 `app.api.catalog_deps`에 두고 공개·로컬 앱만 그 모듈을 쓴다. 연구 라우트는 파일이 옮겨지기 전까지 기존 `create_app()`에만 남는다. 마지막 태스크에서 `create_app()`을 로컬 앱으로 바꾸고 연구 코드와 테스트를 패키지 밖으로 옮긴다. 운영 DB는 공유 PostgreSQL이고, 기동 스키마는 카탈로그 테이블만 만든다.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, SQLAlchemy 2, aiosqlite, asyncpg, httpx, pytest. 수집기는 기존 Node `packages/entry-extractor`. 공개 배포는 Render 웹 서비스.

스펙: `docs/superpowers/specs/2026-10-10-collect-view-split-design.md`

## Global Constraints

- 저장소는 하나다. 패키지는 `packages/web-api`, `packages/entry-extractor`, `packages/research`다.
- 로컬 진입점은 `uvicorn app.local:app`이다. 라우트는 `/admin`, `/admin/catalog`, `/catalog`, `/catalog/{rcp_no}`, `/api/v1/catalog/disclosures`와 그 단건·entry 목록, `/api/v1/viewer/{rcp_no}`와 섹션 단건, `/health`다.
- 공개 진입점은 `uvicorn app.public:app`이다. 라우트는 카탈로그 HTML, 공개 목록 API, Viewer, `/health`만이다. `/admin`, `/admin/extract`, `/admin/reviews`, `/admin/cycle`, `/admin/corps`, `/facts`, `/api/v1/facts`는 없다.
- `app.public:app`는 `DATABASE_URL`이 `postgresql+asyncpg://`로 시작하지 않으면 프로세스를 시작하지 않는다. `create_public_app(settings)`는 테스트용 SQLite URL을 받는다.
- research가 web-api를 import할 수 있다. web-api는 research를 import하지 않는다. 연구 라우트까지 올리는 세 번째 앱은 두지 않는다.
- 운영 `DATABASE_URL`은 로컬 수집과 공개 열람이 같은 PostgreSQL이다. 테스트 DB는 임시 SQLite다. 원문 HTML은 저장하지 않는다.
- DART 간격은 프로세스 안이다. Viewer는 섹션을 한 번에 하나씩, `DartHttpClient` 최소 간격 1초로 가져온다. Node `safeGet`의 1초는 그대로 둔다. 두 프로세스는 시계를 공유하지 않는다.
- `ensure_schema`는 카탈로그 모델만 `create_all`한다. 열 보정은 `catalog_jobs.mode`와 `entries.ordinal`만이다. `audit_report_facts` 열 보정은 research로 옮기고 두 앱은 호출하지 않는다. 연구 테이블과 카탈로그는 지우지 않는다.
- 주석·Docstring·로그·사용자 메시지는 한국어다.
- 기본 통과 명령은 `packages/web-api`에서 `.\.venv\Scripts\python.exe -m pytest -q --tb=short`다. DART와 Node에는 접속하지 않는다. research pytest는 이 명령에 넣지 않는다. `entry-extractor` 테스트는 바꾸지 않는다.
- 추출 칸의 수집·조립·집계를 다시 묶지 않는다. 공용 카탈로그 라이브러리 패키지를 새로 만들지 않는다. 공개 Viewer가 정제 결과를 저장하게 바꾸지 않는다.

## File map

| 파일 | 책임 |
|------|------|
| `packages/web-api/app/api/catalog_deps.py` | 수집·카탈로그·Viewer 의존성. 연구 모듈을 import하지 않는다 |
| `packages/web-api/app/api/admin/collect_ui.py` | 수집 Admin HTML. 연구 서비스를 import하지 않는다 |
| `packages/web-api/app/local.py` | `create_local_app`, 로컬 lifespan, `app` |
| `packages/web-api/app/public.py` | Postgres 가드와 `app` |
| `packages/web-api/app/apps.py` | `create_public_app`, `require_postgres_url` |
| `packages/research/research/` | 옮겨 온 연구 코드. import 접두사는 `research.` |
| `packages/research/research/schema.py` | `audit_report_facts` 열 보정. web-api 기동은 호출하지 않는다 |
| `packages/web-api/app/db/session.py` | 카탈로그 `create_all`과 카탈로그 열 보정만 |

---

### Task 1: 카탈로그 의존성 분리

**Files:**
- Create: `packages/web-api/app/api/catalog_deps.py`
- Modify: `packages/web-api/app/api/deps.py`
- Modify: `packages/web-api/app/api/admin/catalog.py`
- Modify: `packages/web-api/app/api/catalog/ui.py`
- Modify: `packages/web-api/app/api/v1/catalog.py`
- Modify: `packages/web-api/app/api/v1/viewer.py`
- Test: `packages/web-api/tests/test_catalog_deps_import.py`

**Interfaces:**
- Consumes: 기존 `get_session`, `get_viewer_service`, `get_catalog_service`, `get_slice_query_service`, `get_catalog_query_service`, `require_admin`, `ADMIN_TOKEN_HEADER`, `ADMIN_TOKEN_COOKIE`
- Produces: 위 이름을 `app.api.catalog_deps`에서 제공한다. `get_viewer_service`는 `ViewerService(..., concurrency=1)`을 반환한다. `app.api.deps`는 이 이름들을 재수출하고, 연구용 `get_extraction_service`, `get_completeness_service`, `get_corp_industry_service`, `get_date_resolver_service`, `get_fact_repository`, `get_fact_query_service`는 태스크 5까지 deps에 남긴다.

- [ ] **Step 1: Write the failing test**

`packages/web-api/tests/test_catalog_deps_import.py`를 만든다.

```python
"""카탈로그 라우터 import가 연구 모듈을 불러오지 않는지."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_catalog_routers_do_not_import_research() -> None:
    """공개 읽기 라우터를 열어도 추출·OpenDART·LLM 모듈이 로드되지 않는다."""
    root = Path(__file__).resolve().parents[1]
    script = """
import sys
import app.api.v1.catalog
import app.api.v1.viewer
import app.api.catalog.ui
import app.api.admin.catalog
banned = (
    "app.extracting",
    "app.reviewing",
    "app.services.extraction_service",
    "app.adapters.opendart_company",
    "app.adapters.llm_date_resolver",
)
loaded = [name for name in sys.modules if name.startswith(banned)]
raise SystemExit(0 if not loaded else "loaded " + ",".join(loaded))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run from `packages/web-api`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_catalog_deps_import.py -q --tb=short
```

Expected: FAIL. `loaded app.extracting...` 또는 연구 모듈 이름이 stdout에 있다.

- [ ] **Step 3: Write minimal implementation**

`app/api/catalog_deps.py`를 다음 내용으로 만든다. 연구 서비스 import는 넣지 않는다.

```python
"""수집·카탈로그·Viewer 의존성. 연구 모듈을 불러오지 않는다."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.errors import Unauthorized
from app.repositories.disclosure_repository import DisclosureRepository
from app.repositories.entry_repository import EntryRepository
from app.repositories.slice_repository import SliceRepository
from app.services.catalog_query_service import CatalogQueryService
from app.services.catalog_service import CatalogService
from app.services.slice_query_service import SliceQueryService
from app.services.viewer_service import ViewerService

ADMIN_TOKEN_HEADER = "X-Admin-Token"
ADMIN_TOKEN_COOKIE = "admin_token"


def get_settings_dep() -> Settings:
    """설정 객체를 반환한다."""
    return get_settings()


def require_admin(request: Request, settings: Settings = Depends(get_settings_dep)) -> None:
    """Admin 요청을 공유 토큰으로 확인한다."""
    provided = request.headers.get(ADMIN_TOKEN_HEADER) or request.cookies.get(ADMIN_TOKEN_COOKIE)
    if not provided:
        raise Unauthorized("Admin 토큰이 필요합니다. X-Admin-Token 헤더를 확인해 주세요.")
    if provided != settings.admin_token:
        raise Unauthorized("Admin 토큰이 올바르지 않습니다.")


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
) -> ViewerService:
    """Viewer 서비스를 제공한다. 섹션은 한 번에 하나씩 가져온다."""
    return ViewerService(entries, request.app.state.dart_http, concurrency=1)


def get_catalog_service(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> CatalogService:
    """Admin 카탈로그 서비스를 제공한다."""
    service = getattr(request.app.state, "catalog_service", None)
    if service is None:
        service = CatalogService(
            request.app.state.sessionmaker,
            request.app.state.entry_collector,
            max_retries=settings.disclosure_max_retries,
            block_streak_threshold=settings.block_streak_threshold,
            block_wait_seconds=settings.block_wait_seconds,
        )
        request.app.state.catalog_service = service
    return service


def get_slice_query_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
) -> SliceQueryService:
    """슬라이스 완전성 조회 서비스를 제공한다."""
    return SliceQueryService(
        SliceRepository(session),
        settings.heatmap_report_type_list,
    )


def get_catalog_query_service(
    session: AsyncSession = Depends(get_session),
) -> CatalogQueryService:
    """Public 카탈로그 조회 서비스를 제공한다."""
    return CatalogQueryService(DisclosureRepository(session), EntryRepository(session))
```

`app/api/deps.py`에서는 그 함수 본문을 지우고 다음을 재수출한다.

```python
from app.api.catalog_deps import (
    ADMIN_TOKEN_COOKIE,
    ADMIN_TOKEN_HEADER,
    get_catalog_query_service,
    get_catalog_service,
    get_entry_repository,
    get_session,
    get_settings_dep,
    get_slice_query_service,
    get_viewer_service,
    require_admin,
)
```

연구 의존성 함수와 그 import는 `deps.py`에 남긴다.

`catalog.py`, `app/api/catalog/ui.py`, `app/api/v1/catalog.py`, `app/api/v1/viewer.py`의 의존성 import를 `app.api.deps`에서 `app.api.catalog_deps`로 바꾼다.

- [ ] **Step 4: Run test to verify it passes**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_catalog_deps_import.py tests/test_catalog_api.py tests/test_catalog_query_api.py tests/test_viewer_api.py tests/test_admin_slices_api.py -q --tb=short
```

Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api/app/api/catalog_deps.py packages/web-api/app/api/deps.py packages/web-api/app/api/admin/catalog.py packages/web-api/app/api/catalog/ui.py packages/web-api/app/api/v1/catalog.py packages/web-api/app/api/v1/viewer.py packages/web-api/tests/test_catalog_deps_import.py
git commit -m "refactor(web-api): 카탈로그 의존성을 연구 import와 나눈다."
```

---

### Task 2: 수집 Admin 라우터 분리

**Files:**
- Create: `packages/web-api/app/api/admin/collect_ui.py`
- Modify: `packages/web-api/app/api/admin/ui.py`
- Modify: `packages/web-api/app/main.py`
- Test: `packages/web-api/tests/test_catalog_deps_import.py`

**Interfaces:**
- Consumes: `catalog_deps.require_admin`, `get_catalog_service`, `get_slice_query_service`, `get_settings_dep`
- Produces: `app.api.admin.collect_ui.router`. prefix는 `/admin`, `include_in_schema=False`. 수집 화면 경로는 지금 `ui.py`와 같다. `create_app()`은 `collect_ui.router`와 기존 `ui.router`를 둘 다 포함한다.

- [ ] **Step 1: Write the failing test**

`test_catalog_deps_import.py`에 다음을 추가한다.

```python
def test_collect_ui_does_not_import_research() -> None:
    """수집 화면 모듈은 추출·업종 서비스를 불러오지 않는다."""
    root = Path(__file__).resolve().parents[1]
    script = """
import sys
import app.api.admin.collect_ui
banned = (
    "app.services.extraction_service",
    "app.services.corp_industry_service",
    "app.services.completeness_service",
    "app.extracting",
)
loaded = [name for name in sys.modules if name.startswith(banned)]
raise SystemExit(0 if not loaded else "loaded " + ",".join(loaded))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_catalog_deps_import.py::test_collect_ui_does_not_import_research -q --tb=short
```

Expected: FAIL. `collect_ui`가 없다.

- [ ] **Step 3: Write minimal implementation**

`collect_ui.py`를 만들고 `ui.py`에서 수집 전용 함수를 본문 그대로 옮긴다. 연구 서비스 import는 넣지 않는다. 의존성은 `catalog_deps`만 쓴다.

옮길 함수: `_has_valid_token`, `_resolve_year`, `_resolve_report_type`, `_admin_dashboard_url`, `_report_type_from_job`, `_list_year_slices`, `_filter_logs`, `_log_levels_for`, `_job_busy`, `_default_range`, `_to_token_page`, `token_form`, `submit_token`, `dashboard`, `year_bar_partial`, `heatmap_partial`, `slices_chips_partial`, `slices_summary_partial`, `collect_form_partial`, `resume_controls_partial`, `job_status_partial`, `job_logs_partial`, `soft_stop_job`, `force_finish_job`, `slices_partial`, `slice_detail`, `start_collect`, `resume_all`, `retry_slice`.

`ui.py`에는 추출·업종 함수만 남긴다. `_extract_dashboard_url`, `_require_extract_dates`, `_extract_completeness_rows`, `_resolve_extract_window`, `_extract_completeness_page`, `_extract_ops_context`, `_corp_panel_context`, `extract_dashboard`부터 `finish_corps_job`까지다.

`main.py`의 `create_app()`에서 `admin_ui.router` 옆에 `collect_ui.router`를 포함한다.

```python
from app.api.admin import collect_ui as admin_collect_ui
# include_router(admin_ui.router) 바로 위에
app.include_router(admin_collect_ui.router)
```

- [ ] **Step 4: Run test to verify it passes**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_catalog_deps_import.py tests/test_admin_ui.py tests/test_admin_slices_api.py tests/test_extract_admin_ui.py -q --tb=short
```

Expected: PASS. 수집 화면과 추출 화면이 지금 URL 그대로다.

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api/app/api/admin/collect_ui.py packages/web-api/app/api/admin/ui.py packages/web-api/app/main.py packages/web-api/tests/test_catalog_deps_import.py
git commit -m "refactor(web-api): 수집 Admin 화면을 추출 화면과 나눈다."
```

---

### Task 3: 로컬·공개 앱 팩토리

**Files:**
- Create: `packages/web-api/app/apps.py`
- Create: `packages/web-api/app/local.py`
- Create: `packages/web-api/app/public.py`
- Test: `packages/web-api/tests/test_app_roles.py`

**Interfaces:**
- Consumes: `catalog_deps`, `admin.catalog.router`, `admin.collect_ui.router`, `catalog.ui.router`, `v1.catalog.router`, `v1.viewer.router`, `Settings`, `DartHttpClient`, `NodeEntryCollector`
- Produces:
  - `require_postgres_url(database_url: str) -> None`. `postgresql+asyncpg://`로 시작하지 않으면 `RuntimeError`.
  - `create_public_app(settings: Settings) -> FastAPI`. 라우터는 카탈로그 HTML, 공개 목록 API, Viewer, `/health`.
  - `create_local_app() -> FastAPI`. 공개 라우터에 수집 Admin을 더한다. `get_settings()`를 쓴다.
  - `app.public:app`는 가드를 통과한 뒤 `create_public_app` 결과다.
  - `app.local:app`는 `create_local_app()` 결과다.
  - 이 태스크의 `app.main:app`는 아직 연구 라우트를 포함한 기존 `create_app()`이다.

- [ ] **Step 1: Write the failing test**

`packages/web-api/tests/test_app_roles.py`:

```python
"""로컬·공개 앱의 라우트와 Postgres 가드."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from app.apps import create_public_app, require_postgres_url
from app.config import Settings
from app.local import create_local_app

PUBLIC_PREFIXES = (
    "/health",
    "/catalog",
    "/api/v1/catalog/disclosures",
    "/api/v1/viewer/{rcp_no}",
)
FORBIDDEN = (
    "/admin",
    "/admin/extract",
    "/admin/reviews",
    "/admin/cycle",
    "/admin/corps",
    "/facts",
    "/api/v1/facts",
)


def _paths(app) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def test_require_postgres_url_rejects_sqlite() -> None:
    with pytest.raises(RuntimeError):
        require_postgres_url("sqlite+aiosqlite:///./dart_catalog.db")


def test_require_postgres_url_accepts_asyncpg() -> None:
    require_postgres_url("postgresql+asyncpg://user:pass@host/db")


def test_public_app_routes_are_read_only() -> None:
    app = create_public_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
    paths = _paths(app)
    assert "/health" in paths
    assert "/catalog" in paths
    assert "/api/v1/catalog/disclosures" in paths
    assert "/api/v1/viewer/{rcp_no}" in paths
    for path in paths:
        assert not path.startswith(FORBIDDEN)


def test_local_app_has_collect_and_read_routes() -> None:
    app = create_local_app()
    paths = _paths(app)
    assert "/admin" in paths
    assert "/admin/catalog/extract" in paths
    assert "/health" in paths
    assert "/api/v1/viewer/{rcp_no}" in paths
    assert "/admin/extract" not in paths
    assert "/admin/reviews" not in paths
    assert "/facts" not in paths


def test_role_apps_do_not_import_research_modules() -> None:
    root = Path(__file__).resolve().parents[1]
    script = """
import sys
from app.apps import create_public_app
from app.config import Settings
from app.local import create_local_app
create_local_app()
create_public_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
banned = (
    "app.extracting",
    "app.reviewing",
    "app.services.extraction_service",
    "app.adapters.opendart_company",
    "app.adapters.llm_date_resolver",
    "research",
)
loaded = [name for name in sys.modules if name == "research" or name.startswith(banned)]
raise SystemExit(0 if not loaded else "loaded " + ",".join(loaded))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
```

`/admin/catalog/extract`가 실제 경로와 다르면 `app/api/admin/catalog.py`의 collect POST 경로를 테스트에 그대로 쓴다.

- [ ] **Step 2: Run test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_app_roles.py -q --tb=short
```

Expected: FAIL. `app.apps` 또는 `app.local`이 없다.

- [ ] **Step 3: Write minimal implementation**

`app/apps.py`:

```python
"""로컬·공개 앱이 공유하는 팩토리."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.adapters.dart_http import DartHttpClient
from app.api.admin import catalog as admin_catalog
from app.api.admin import collect_ui
from app.api.catalog import ui as catalog_ui
from app.api.v1 import catalog as catalog_query
from app.api.v1 import viewer
from app.config import Settings, get_settings
from app.db.session import create_db_engine, create_sessionmaker, ensure_schema
from app.errors import register_exception_handlers

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://dart.fss.or.kr/",
}


def require_postgres_url(database_url: str) -> None:
    """공개 프로세스는 PostgreSQL URL만 받는다."""
    if not database_url.startswith("postgresql+asyncpg://"):
        raise RuntimeError(
            "공개 서버의 DATABASE_URL은 postgresql+asyncpg:// 로 시작해야 합니다."
        )


def _read_routers(app: FastAPI) -> None:
    app.include_router(catalog_ui.router)
    app.include_router(catalog_query.router)
    app.include_router(viewer.router)

    @app.get("/health", tags=["시스템"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}


def _dart_client(settings: Settings) -> tuple[httpx.AsyncClient, DartHttpClient]:
    http_client = httpx.AsyncClient(headers=_DEFAULT_HEADERS, follow_redirects=True)
    dart_http = DartHttpClient(
        http_client,
        timeout_seconds=settings.dart_fetch_timeout_seconds,
        max_retries=settings.dart_fetch_max_retries,
        min_interval_seconds=settings.dart_fetch_min_interval_seconds,
    )
    return http_client, dart_http


@asynccontextmanager
async def public_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """DB와 열람용 DART 클라이언트만 연다."""
    settings: Settings = app.state.settings
    engine = create_db_engine(settings.database_url)
    await ensure_schema(engine)
    http_client, dart_http = _dart_client(settings)
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.http_client = http_client
    app.state.dart_http = dart_http
    try:
        yield
    finally:
        await http_client.aclose()
        await engine.dispose()


@asynccontextmanager
async def local_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """수집용 Node 수집기와 열람용 DART 클라이언트를 연다."""
    from app.adapters.node_entry_collector import NodeEntryCollector
    from app.repositories.job_repository import JobRepository

    settings: Settings = app.state.settings
    engine = create_db_engine(settings.database_url)
    await ensure_schema(engine)
    http_client, dart_http = _dart_client(settings)
    sessionmaker = create_sessionmaker(engine)
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.http_client = http_client
    app.state.dart_http = dart_http
    app.state.entry_collector = NodeEntryCollector(
        settings.node_executable,
        settings.entry_collector_script,
        timeout_seconds=settings.collector_timeout_seconds,
    )
    async with sessionmaker() as session:
        await JobRepository(session).abandon_orphans()
        await session.commit()
    try:
        yield
    finally:
        await http_client.aclose()
        await engine.dispose()


def create_public_app(settings: Settings) -> FastAPI:
    """카탈로그 조회와 Viewer만 제공하는 앱을 만든다."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        async with public_lifespan(app):
            yield

    app = FastAPI(title="DART 공시 열람", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)
    _read_routers(app)
    return app


def create_local_app() -> FastAPI:
    """수집 Admin과 열람을 제공하는 앱을 만든다."""
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        async with local_lifespan(app):
            yield

    app = FastAPI(title="DART 공시 수집", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(admin_catalog.router)
    app.include_router(collect_ui.router)
    _read_routers(app)
    return app
```

`app/local.py`:

```python
"""로컬 수집·열람 진입점."""

from app.apps import create_local_app

app = create_local_app()
```

`app/public.py`:

```python
"""공개 카탈로그·Viewer 진입점."""

from app.apps import create_public_app, require_postgres_url
from app.config import get_settings

_settings = get_settings()
require_postgres_url(_settings.database_url)
app = create_public_app(_settings)
```

`create_app()`과 `app.main:app`는 이 태스크에서 그대로 둔다.

- [ ] **Step 4: Run test to verify it passes**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_app_roles.py tests/test_app.py tests/test_dart_http_wiring.py -q --tb=short
```

Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api/app/apps.py packages/web-api/app/local.py packages/web-api/app/public.py packages/web-api/tests/test_app_roles.py
git commit -m "feat(web-api): 로컬 수집 앱과 공개 열람 앱을 나눈다."
```

---

### Task 4: 카탈로그만 기동 스키마로

**Files:**
- Create: `packages/research/pyproject.toml`
- Create: `packages/research/research/__init__.py`
- Create: `packages/research/research/schema.py`
- Create: `packages/research/tests/test_research_schema.py`
- Modify: `packages/web-api/app/models/__init__.py`
- Modify: `packages/web-api/app/db/session.py`
- Modify: `packages/web-api/tests/test_ensure_schema.py`
- Test: `packages/web-api/tests/test_catalog_schema.py`

**Interfaces:**
- Consumes: 지금 `session.py`의 `_COLUMN_PATCHES` 중 `audit_report_facts` 항목, `app.models.base.Base`
- Produces: `research.schema.ensure_research_schema(engine) -> None`. web-api `ensure_schema`는 카탈로그 열만 보정한다. `app.models`의 `__all__`은 `Base`, `CatalogJob`, `CatalogJobLog`, `Disclosure`, `DisclosureAttempt`, `Entry`, `SliceProgress`만이다.

- [ ] **Step 1: Write the failing test**

`packages/web-api/tests/test_catalog_schema.py`:

```python
"""기동 스키마가 카탈로그 테이블만 다루는 지 확인한다."""

from __future__ import annotations

from app.db.session import _COLUMN_PATCHES, ensure_schema, create_db_engine
from app.models import Base


def test_metadata_tables_are_catalog_only() -> None:
    names = set(Base.metadata.tables)
    assert names == {
        "entries",
        "disclosures",
        "catalog_jobs",
        "catalog_job_logs",
        "slice_progress",
        "disclosure_attempts",
    }


def test_column_patches_are_catalog_only() -> None:
    tables = {table for table, _column, _sqlite, _postgres in _COLUMN_PATCHES}
    assert tables <= {"catalog_jobs", "entries"}
    assert "audit_report_facts" not in tables


async def test_ensure_schema_does_not_create_research_tables() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await ensure_schema(engine)
    async with engine.begin() as connection:
        rows = (
            await connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        ).fetchall()
    await engine.dispose()
    names = {row[0] for row in rows}
    assert "audit_report_facts" not in names
    assert "corps" not in names
    assert "entries" in names
```

`exec_driver_sql`이 이 SQLAlchemy 버전에서 없으면 `text("SELECT name FROM sqlite_master WHERE type = 'table'")`와 `connection.execute`를 쓴다.

- [ ] **Step 2: Run test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_catalog_schema.py -q --tb=short
```

Expected: FAIL. 메타데이터에 `audit_report_facts` 또는 `corps`가 있다.

- [ ] **Step 3: Write minimal implementation**

`app/models/__init__.py`에서 연구 모델 import와 `__all__` 항목을 뺀다. 모듈 파일 `audit_report_fact.py`, `extraction_job.py`, `extraction_review.py`, `failure_shape_judgment.py`, `corp.py`는 태스크 5까지 `app/models/`에 둔다. 다른 코드가 `from app.models import AuditReportFact`를 쓰면 `from app.models.audit_report_fact import AuditReportFact`로 고친다. `from app.models import Base`는 유지한다.

`session.py`의 `_COLUMN_PATCHES`에서 `audit_report_facts` 튜플을 지운다. `catalog_jobs.mode`와 `entries.ordinal`만 남긴다.

지운 튜플을 `packages/research/research/schema.py`의 `ensure_research_schema`로 옮긴다. 이 함수는 테이블이 있을 때만 빠진 열을 ALTER한다. web-api는 이 함수를 import하지 않는다. 보정 도우미는 `session._add_column_if_missing`을 호출하지 말고, research 안에 sqlite용 ALTER를 작게 둔다. 연구 테스트는 이 명령을 돌리지 않는다.

`tests/test_ensure_schema.py`에서 `audit_report_facts`와 `corps`를 만드는 테스트를 지우고, 그 본문을 `packages/research/tests/test_research_schema.py`로 옮겨 `ensure_research_schema`를 호출하게 한다. 카탈로그 `mode` 테스트는 web-api에 남긴다.

`packages/research/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "dart-wrapper-research"
version = "0.1.0"
description = "DART 감사 추출·검토·사이클. 기본 앱은 이 패키지를 실행하지 않는다."
requires-python = ">=3.11"
dependencies = ["dart-wrapper-web-api"]

[tool.setuptools.packages.find]
include = ["research*"]
```

`packages/research/research/__init__.py`는 빈 모듈 독스트링만 둔다.

- [ ] **Step 4: Run test to verify it passes**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_catalog_schema.py tests/test_ensure_schema.py tests/test_models.py -q --tb=short
```

Expected: PASS. `packages/research/tests`는 수집되지 않는다.

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api/app/models/__init__.py packages/web-api/app/db/session.py packages/web-api/tests/test_ensure_schema.py packages/web-api/tests/test_catalog_schema.py packages/research
git commit -m "refactor(web-api): 기동 스키마를 카탈로그 테이블로 한정한다."
```

---

### Task 5: 연구 패키지로 이동하고 기본 앱에서 떼기

**Files:**
- Modify: `packages/web-api/app/main.py`
- Modify: `packages/web-api/app/config.py`
- Modify: `packages/web-api/app/api/deps.py`
- Modify: `packages/web-api/app/templates/admin/base.html`
- Modify: 아래에 적힌 테스트 중 web-api에 남는 파일
- Move: 아래 목록
- Test: `packages/web-api/tests/test_app_roles.py`

**Interfaces:**
- Consumes: `create_local_app`, `create_public_app`, Task 4의 `research` 패키지
- Produces: `app.main.create_app`는 `create_local_app`와 같다. `app.main:app`는 `app.local:app`와 같은 앱이다. 연구 코드의 내부 import는 `research.*`이고, 카탈로그·DART·parsing·`rcept_dt`·`report_types`·`errors`는 `app.*`로 남는다. web-api `Settings`에는 OpenDART·날짜 LLM 필드가 없다.

- [ ] **Step 1: Write the failing test**

`test_app_roles.py`에 추가한다.

```python
def test_main_app_matches_local_routes() -> None:
    from app.main import create_app

    local_paths = _paths(create_local_app())
    main_paths = _paths(create_app())
    assert main_paths == local_paths
```

이 테스트는 지금 FAIL이다. `create_app()`에 `/admin/extract`가 있다.

- [ ] **Step 2: Run test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_app_roles.py::test_main_app_matches_local_routes -q --tb=short
```

Expected: FAIL. 경로 집합이 다르다.

- [ ] **Step 3: Move research files**

저장소 루트에서 디렉터리째 옮긴다. 대상이 없으면 `git mv`가 실패하므로 디렉터리를 먼저 만든다.

```powershell
New-Item -ItemType Directory -Force packages/research/research/adapters, packages/research/research/ports, packages/research/research/models, packages/research/research/repositories, packages/research/research/services, packages/research/research/api/admin, packages/research/research/api/v1, packages/research/research/schemas, packages/research/research/templates/admin/partials, packages/research/research/data, packages/research/scripts, packages/research/tests | Out-Null
git mv packages/web-api/app/extracting packages/research/research/extracting
git mv packages/web-api/app/reviewing packages/research/research/reviewing
git mv packages/web-api/app/ksic.py packages/research/research/ksic.py
git mv packages/web-api/app/data/ksic10.json packages/research/research/data/ksic10.json
git mv packages/web-api/app/data/ksic11.json packages/research/research/data/ksic11.json
git mv packages/web-api/app/adapters/llm_date_resolver.py packages/research/research/adapters/llm_date_resolver.py
git mv packages/web-api/app/adapters/opendart_company.py packages/research/research/adapters/opendart_company.py
git mv packages/web-api/app/ports/date_resolver.py packages/research/research/ports/date_resolver.py
git mv packages/web-api/app/models/audit_report_fact.py packages/research/research/models/audit_report_fact.py
git mv packages/web-api/app/models/extraction_job.py packages/research/research/models/extraction_job.py
git mv packages/web-api/app/models/extraction_review.py packages/research/research/models/extraction_review.py
git mv packages/web-api/app/models/failure_shape_judgment.py packages/research/research/models/failure_shape_judgment.py
git mv packages/web-api/app/models/corp.py packages/research/research/models/corp.py
git mv packages/web-api/app/repositories/fact_repository.py packages/research/research/repositories/fact_repository.py
git mv packages/web-api/app/repositories/corp_repository.py packages/research/research/repositories/corp_repository.py
git mv packages/web-api/app/repositories/extraction_job_repository.py packages/research/research/repositories/extraction_job_repository.py
git mv packages/web-api/app/services/extraction_service.py packages/research/research/services/extraction_service.py
git mv packages/web-api/app/services/completeness_service.py packages/research/research/services/completeness_service.py
git mv packages/web-api/app/services/extraction_review_service.py packages/research/research/services/extraction_review_service.py
git mv packages/web-api/app/services/collection_cycle_service.py packages/research/research/services/collection_cycle_service.py
git mv packages/web-api/app/services/corp_industry_service.py packages/research/research/services/corp_industry_service.py
git mv packages/web-api/app/services/date_resolver_service.py packages/research/research/services/date_resolver_service.py
git mv packages/web-api/app/services/fact_query_service.py packages/research/research/services/fact_query_service.py
git mv packages/web-api/app/api/admin/extract.py packages/research/research/api/admin/extract.py
git mv packages/web-api/app/api/admin/reviews.py packages/research/research/api/admin/reviews.py
git mv packages/web-api/app/api/admin/cycle.py packages/research/research/api/admin/cycle.py
git mv packages/web-api/app/api/admin/corps.py packages/research/research/api/admin/corps.py
git mv packages/web-api/app/api/admin/ui.py packages/research/research/api/admin/extract_ui.py
git mv packages/web-api/app/api/facts packages/research/research/api/facts
git mv packages/web-api/app/api/v1/facts.py packages/research/research/api/v1/facts.py
git mv packages/web-api/app/schemas/facts.py packages/research/research/schemas/facts.py
git mv packages/web-api/app/schemas/extract.py packages/research/research/schemas/extract.py
git mv packages/web-api/app/schemas/corps.py packages/research/research/schemas/corps.py
git mv packages/web-api/app/templates/admin/extract.html packages/research/research/templates/admin/extract.html
git mv packages/web-api/app/templates/admin/reviews.html packages/research/research/templates/admin/reviews.html
git mv packages/web-api/app/templates/admin/cycle.html packages/research/research/templates/admin/cycle.html
git mv packages/web-api/app/templates/facts packages/research/research/templates/facts
git mv packages/web-api/scripts/extraction_reviews.py packages/research/scripts/extraction_reviews.py
git mv packages/web-api/scripts/export_audit_report_facts.py packages/research/scripts/export_audit_report_facts.py
git mv packages/web-api/scripts/build_ksic10.py packages/research/scripts/build_ksic10.py
git mv packages/web-api/scripts/build_ksic11.py packages/research/scripts/build_ksic11.py
git mv packages/web-api/scripts/remap_corp_ksic_names.py packages/research/scripts/remap_corp_ksic_names.py
```

다음 부분 템플릿을 `packages/research/research/templates/admin/partials/`로 `git mv`한다. `extract_completeness.html`, `extract_completeness_items.html`, `extract_field_bundle_items.html`, `extract_form.html`, `extract_job.html`, `extract_logs.html`, `review_detail.html`, `review_list_row.html`, `corps_panel.html`. `scripts/backfill_disclosures.py`는 web-api에 남긴다.

연구 테스트 파일을 `packages/research/tests/`로 `git mv`한다. 대상은 `test_extracting_`, `test_extraction_`, `test_extract_admin`, `test_facts_`, `test_fact_`, `test_field_bundles`, `test_reviewing_`, `test_collection_cycle`, `test_date_resolver`, `test_corps_`, `test_corp_industry`, `test_opendart_`, `test_ksic`, `test_audit_report_fact`, `test_export_audit_report_facts`, `test_admin_reviews_ui`로 시작하는 파일이다.

옮긴 파일과 그 테스트에서만 다음 접두사를 `app.`에서 `research.`로 바꾼다. `app.models.entry`, `app.adapters.dart_http`, `app.parsing`, `app.rcept_dt`, `app.report_types`, `app.errors`, `app.db`, `app.config`의 카탈로그 필드는 바꾸지 않는다.

접두사: `app.extracting`, `app.reviewing`, `app.ksic`, `app.adapters.llm_date_resolver`, `app.adapters.opendart_company`, `app.ports.date_resolver`, `app.models.audit_report_fact`, `app.models.extraction_job`, `app.models.extraction_review`, `app.models.failure_shape_judgment`, `app.models.corp`, `app.repositories.fact_repository`, `app.repositories.corp_repository`, `app.repositories.extraction_job_repository`, `app.services.extraction_service`, `app.services.completeness_service`, `app.services.extraction_review_service`, `app.services.collection_cycle_service`, `app.services.corp_industry_service`, `app.services.date_resolver_service`, `app.services.fact_query_service`, `app.api.admin.extract`, `app.api.admin.reviews`, `app.api.admin.cycle`, `app.api.admin.corps`, `app.api.facts`, `app.api.v1.facts`, `app.schemas.facts`, `app.schemas.extract`, `app.schemas.corps`.

`extract_ui.py`로 옮긴 구 `ui.py`의 템플릿 디렉터리는 `packages/research/research/templates`를 먼저 보고, 없으면 `packages/web-api/app/templates`의 `admin/base.html`을 보게 한다. `jinja2.ChoiceLoader`와 `FileSystemLoader` 둘을 쓴다.

OpenDART·날짜 LLM 설정을 `research/config.py`의 `ResearchSettings`로 옮긴다. 필드는 지금 `Settings`의 `opendart_*`, `date_resolver_*`, `parse_opendart_api_keys`와 같다. web-api `Settings`에서 그 필드와 메서드를 지운다. 옮긴 서비스는 `ResearchSettings`를 읽는다. `extra="ignore"`는 web-api `Settings`에 유지한다.

`app/main.py`는 연구 라우터 include와 LLM·OpenDART 클라이언트를 지우고 `create_local_app`을 `create_app`으로 내보낸다.

```python
"""로컬 앱의 호환 진입점. 새 실행은 app.local:app 를 쓴다."""

from app.local import app, create_local_app as create_app

__all__ = ["app", "create_app"]
```

`app/api/deps.py`에서 연구 서비스 함수와 연구 import를 지운다. 카탈로그 재수출은 남긴다.

`templates/admin/base.html`의 운영 메뉴는 수집 링크만 남긴다.

```html
<nav class="ops-switch" aria-label="운영 화면">
  <a href="/admin" class="{% if ops_section == 'catalog' %}is-selected{% endif %}">수집</a>
</nav>
```

web-api에 남는 테스트의 `create_app` import가 `app.main`을 가리키면 그대로 둔다. `create_app`이 로컬 앱이 되기 때문이다.

`tests/test_admin_ui.py`에서 `CorpIndustrySummary`, `FakeCorpIndustryService`, `get_corp_industry_service` override를 지운다. `test_admin_index_has_extract_nav`는 수집 링크만 있는지 확인하고 추출·검토·사이클 링크가 없는지 확인하게 고친다.

`tests/test_dart_http_wiring.py`의 공유 클라이언트 테스트는 로컬 앱의 Viewer만 본다. `get_extraction_service` 단언은 지운다. `viewer._concurrency == 1`과 `dart_http._min_interval_seconds` 단언은 남긴다. lifespan 테스트는 `create_local_app`으로 바꾸고 `entry_collector`가 있으며 `opendart_http_client`와 `llm_http_client`가 없는지 확인한다.

- [ ] **Step 4: Run test to verify it passes**

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

Expected: PASS. 연구 테스트 파일은 `packages/web-api/tests`에 없다.

- [ ] **Step 5: Commit**

```powershell
git add packages/web-api packages/research
git commit -m "refactor: 추출·검토·사이클·업종·Facts를 research 패키지로 옮긴다."
```

---

### Task 6: 살아 있는 문서

**Files:**
- Modify: `README.md`
- Modify: `PRD.md`
- Modify: `packages/web-api/README.md`
- Modify: `docs/collection-cycle.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: 스펙 8절
- Produces: 루트 README, PRD, web-api README가 수집·카탈로그·Viewer와 두 진입점만 설명한다.

- [ ] **Step 1: Update the living docs**

루트 `README.md`의 기본 흐름은 수집, 카탈로그 탐색, Viewer 세 단계로 줄인다. 구조에 `packages/research`를 적고, 지금은 실행하지 않는다고 한 줄 적는다. 실행 명령은 `uvicorn app.local:app`이다. 공개 명령은 `uvicorn app.public:app`이고 `0.0.0.0`과 `$PORT`, Postgres `DATABASE_URL`이 필요하다고 적는다.

`PRD.md`의 기능 목록은 카탈로그 수집, 탐색, Viewer만 남긴다. 감사 추출과 회사 업종 항목은 빼고, 그 코드는 `packages/research`에 있으며 기본 앱이 실행하지 않는다고 한 줄 적는다.

`packages/web-api/README.md`의 엔드포인트 표에서 추출·업종·facts·resolve-dates 행을 지운다. 구조 표의 Extracting 행을 지운다. 실행 명령을 `app.local:app`와 `app.public:app`로 적는다.

`docs/collection-cycle.md` 맨 위에 다음을 넣고, `지금 앱에서 하는 일` 표는 지운다. 단계·분류 절차는 그대로 둔다.

```markdown
이 사이클의 구현은 `packages/research`에 있다. `app.local:app`와 `app.public:app`는 이 흐름을 제공하지 않는다. 로컬 앱은 수집과 열람만 하고, 공개 앱은 카탈로그 조회와 Viewer만 한다.
```

`AGENTS.md`의 수집 사이클 절 앞에 다음을 넣는다.

```markdown
기본 앱의 범위는 수집과 열람이다. 추출기 버전, 로직 메모, 팔로업 규칙은 `packages/research`를 다룰 때 적용한다.
```

`docs/superpowers/README.md` Plans 표에는 이 계획 링크가 이미 있다. 다시 넣지 않는다.

- [ ] **Step 2: Check the docs and the suite**

```powershell
cd packages/web-api
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

Expected: PASS.

루트 README에 `app.local:app`, `app.public:app`, `packages/research`가 있는지 확인한다. `uvicorn app.main:app`를 실행 방법으로 소개하지 않는다. `app.main`은 코드의 호환 별칭으로만 남는다.

- [ ] **Step 3: Commit**

```powershell
git add README.md PRD.md packages/web-api/README.md docs/collection-cycle.md AGENTS.md
git commit -m "docs: 실행 중인 앱의 범위를 수집과 열람으로 적는다."
```
