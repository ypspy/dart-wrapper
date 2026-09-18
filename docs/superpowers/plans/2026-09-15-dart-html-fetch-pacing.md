# DART HTML 요청 간격 공유 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 추출과 Viewer가 같은 `DartHttpClient`로 DART HTML GET을 보내, 기본 1초 간격·Viewer 동시성 1로 집 IP 차단을 줄인다.

**Architecture:** `lifespan`이 `app.state.dart_http`를 하나 만든다. `get_extraction_service`와 `get_viewer_service`는 새 클라이언트를 만들지 않고 이 인스턴스만 쓴다. Viewer `concurrency`는 1. `DartHttpClient` 클래스 기본 간격은 0으로 두고(단위 테스트), 앱 배선만 설정값 1초를 넣는다.

**Tech Stack:** FastAPI, httpx, Pydantic Settings, pytest. 주석·Docstring·로그·사용자 메시지는 한국어.

## Global Constraints

- 패키지: `packages/web-api`만. 새 npm 패키지 없음. Node 수집기 User-Agent·`safeGet`은 변경하지 않음.
- 게이트: `app.state`의 `DartHttpClient` **하나**. 추출·Viewer가 공유.
- 간격: `DART_FETCH_MIN_INTERVAL_SECONDS`, 기본 `1.0`. 클래스 기본값 `min_interval_seconds=0.0`은 유지.
- Viewer 동시성: `1`. `settings.dart_fetch_concurrency`(기본 4)는 Viewer에 쓰지 않음.
- 정책: 연결 끊김·`fetch_failed`로 잡을 멈추지 않음. 403/429·캡차 연속 5회 중단은 기존 유지.
- 테스트는 `packages/web-api`에서 `.\.venv\Scripts\python.exe -m pytest …` (작업 디렉터리 `packages/web-api`).
- TDD: 실패하는 테스트 → 구현 → 통과 → 커밋. Live DART 호출 테스트 없음.

## File map

| 파일 | 책임 |
|------|------|
| `packages/web-api/app/main.py` | `lifespan`에서 `app.state.dart_http` 생성 |
| `packages/web-api/app/api/deps.py` | 추출·Viewer가 `app.state.dart_http` 사용, Viewer `concurrency=1` |
| `packages/web-api/app/adapters/dart_http.py` | 기존 `fetch_html` 간격 락. 클래스 기본 0초 유지 |
| `packages/web-api/app/config.py` | `dart_fetch_min_interval_seconds` 기본 1.0 (이미 있으면 유지) |
| `packages/web-api/.env.example` | `DART_FETCH_MIN_INTERVAL_SECONDS=1` (이미 있으면 유지) |
| `packages/web-api/tests/test_dart_http_wiring.py` | 공유 인스턴스·간격·Viewer 동시성 |
| `packages/web-api/README.md` | 추출·Viewer가 같은 1초 줄을 쓴다고 한 줄 |

---

### Task 1: 공유 `dart_http` 배선

**Files:**
- Modify: `packages/web-api/app/main.py`
- Modify: `packages/web-api/app/api/deps.py`
- Create: `packages/web-api/tests/test_dart_http_wiring.py`
- Modify (이미 워킹 트리에 1초 배선이 있으면 커밋에 포함): `packages/web-api/app/adapters/dart_http.py`, `packages/web-api/app/config.py`, `packages/web-api/.env.example`

**Interfaces:**
- Consumes: `DartHttpClient(client, timeout_seconds, max_retries, min_interval_seconds=0.0)`, `Settings.dart_fetch_min_interval_seconds`, `Settings.dart_fetch_timeout_seconds`, `Settings.dart_fetch_max_retries`
- Produces: `app.state.dart_http: DartHttpClient`. `get_extraction_service`와 `get_viewer_service`가 같은 인스턴스를 `ExtractionService._http` / `ViewerService._http`에 넣음. `ViewerService(..., concurrency=1)`

- [ ] **Step 1: Write the failing tests**

`packages/web-api/tests/test_dart_http_wiring.py`:

```python
"""추출과 Viewer가 같은 DART HTML 클라이언트를 쓰는지."""

from __future__ import annotations

from unittest.mock import MagicMock

from starlette.requests import Request

from app.adapters.dart_http import DartHttpClient
from app.api.deps import get_extraction_service, get_viewer_service
from app.config import Settings, get_settings
from app.main import create_app


def _http_request(app) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("test", 50000),
            "server": ("test", 80),
            "app": app,
        }
    )


def test_extract_and_viewer_share_dart_http_and_viewer_is_serial() -> None:
    """deps가 같은 dart_http를 쓰고 Viewer 동시성은 1이다."""
    app = create_app()
    settings = Settings()
    dart_http = DartHttpClient(
        MagicMock(),
        min_interval_seconds=settings.dart_fetch_min_interval_seconds,
    )
    app.state.dart_http = dart_http
    app.state.sessionmaker = MagicMock()
    app.state.extraction_service = None
    request = _http_request(app)

    extraction = get_extraction_service(request, settings)
    viewer = get_viewer_service(request, entries=MagicMock())

    assert extraction._http is dart_http
    assert viewer._http is dart_http
    assert viewer._concurrency == 1
    assert dart_http._min_interval_seconds == settings.dart_fetch_min_interval_seconds


async def test_lifespan_attaches_paced_dart_http(monkeypatch) -> None:
    """기동 시 app.state.dart_http가 설정 간격으로 붙는다."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        http = app.state.dart_http
        assert isinstance(http, DartHttpClient)
        assert http._min_interval_seconds == get_settings().dart_fetch_min_interval_seconds
    get_settings.cache_clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run (cwd `packages/web-api`):

```text
.\.venv\Scripts\python.exe -m pytest tests/test_dart_http_wiring.py -q
```

Expected: FAIL (`AttributeError: dart_http` 또는 `get_viewer_service`가 새 `DartHttpClient`를 만들어 `is` 단언 실패, Viewer `_concurrency == 4`)

- [ ] **Step 3: Write minimal implementation**

`packages/web-api/app/main.py` — `from app.adapters.dart_http import DartHttpClient`를 추가하고, `http_client` 생성 직후에:

```python
    dart_http = DartHttpClient(
        http_client,
        timeout_seconds=settings.dart_fetch_timeout_seconds,
        max_retries=settings.dart_fetch_max_retries,
        min_interval_seconds=settings.dart_fetch_min_interval_seconds,
    )
    app.state.http_client = http_client
    app.state.dart_http = dart_http
```

(`app.state.http_client = http_client`는 기존 한 줄을 이 블록과 맞춘다. `llm_http_client` / `opendart_http_client`는 그대로.)

`packages/web-api/app/api/deps.py` — `get_viewer_service`와 `get_extraction_service`:

```python
def get_viewer_service(
    request: Request,
    entries: EntryRepository = Depends(get_entry_repository),
) -> ViewerService:
    """Viewer 서비스를 제공한다. DART GET은 앱 공유 클라이언트를 쓴다."""
    return ViewerService(entries, request.app.state.dart_http, concurrency=1)


def get_extraction_service(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> ExtractionService:
    """Admin 감사 추출 서비스를 제공한다.

    백그라운드 작업이 요청 세션 수명에 묶이지 않도록 세션메이커를 직접 넘긴다.
    DART HTML 클라이언트는 앱 수명 동안 하나다.
    """
    service = getattr(request.app.state, "extraction_service", None)
    if service is None:
        service = ExtractionService(
            request.app.state.sessionmaker,
            request.app.state.dart_http,
            block_streak_threshold=settings.block_streak_threshold,
            block_wait_seconds=settings.block_wait_seconds,
        )
        request.app.state.extraction_service = service
    return service
```

`get_viewer_service`에서 쓰이지 않게 된 `settings` 매개변수와, 그 호출부에만 있던 `get_settings_dep` 사용은 제거한다. `DartHttpClient` import가 deps에서 더 이상 필요 없으면 제거한다.

`dart_http.py`의 `min_interval` 구현·`config.py` 기본 1.0·`.env.example`의 `DART_FETCH_MIN_INTERVAL_SECONDS=1`이 워킹 트리에만 있으면 이 커밋에 포함한다. 클래스 `__init__` 기본값은 `0.0`으로 둔다.

- [ ] **Step 4: Run tests to verify they pass**

```text
.\.venv\Scripts\python.exe -m pytest tests/test_dart_http_wiring.py tests/test_dart_http.py tests/test_viewer_api.py tests/test_app.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

Windows:

```text
git add packages/web-api/app/main.py packages/web-api/app/api/deps.py packages/web-api/tests/test_dart_http_wiring.py packages/web-api/app/adapters/dart_http.py packages/web-api/app/config.py packages/web-api/.env.example
git commit -m "feat: 추출과 Viewer가 같은 DART HTML 요청 줄을 쓰게 한다"
```

KSIC·OpenDART·다른 패키지는 스테이징하지 않는다. `git add -A` 금지.

---

### Task 2: README

**Files:**
- Modify: `packages/web-api/README.md`

**Interfaces:**
- Consumes: `DART_FETCH_MIN_INTERVAL_SECONDS` 기본 1초, Viewer 동시성 1
- Produces: 추출 절에 Viewer가 같은 줄을 쓴다는 문장

- [ ] **Step 1: Update the extract pacing sentence**

`packages/web-api/README.md`의 다음 문장:

```markdown
추출 원문 GET은 `DART_FETCH_MIN_INTERVAL_SECONDS`(기본 1초) 간격을 둡니다. 수집기 `safeGet`과 같습니다.
```

을 아래로 바꾼다:

```markdown
추출과 Viewer 원문 GET은 같은 DART 클라이언트를 쓰며 `DART_FETCH_MIN_INTERVAL_SECONDS`(기본 1초)
간격을 둡니다. Viewer는 섹션을 한 번에 하나 가져옵니다. 수집기 `safeGet`과 같은 간격입니다.
```

README에 KSIC 등 미커밋 다른 절이 있으면, HEAD README에만 위 문장을 넣고 커밋한 뒤 워킹 트리 내용을 복원한다 (필드 묶음 README Task 6과 같은 백업 절차).

- [ ] **Step 2: Commit**

```text
git add packages/web-api/README.md
git commit -m "docs: 추출·Viewer DART GET이 1초 줄을 공유한다고 적는다"
```

---

## Self-review

**Spec coverage**

| 스펙 | 태스크 |
|------|--------|
| `app.state.dart_http` 하나 | 1 |
| 간격 설정값 1초, 클래스 기본 0 | 1 |
| Viewer concurrency 1 | 1 |
| 추출·Viewer 같은 인스턴스 | 1 |
| `fetch_failed`로 잡 중단 안 함 | 코드 변경 없음 (기존 `_process_document`) |
| 수집기 UA 비목표 | 계획에 없음 |
| README | 2 |
| Live DART 없음 | Task 1 테스트가 Mock/lifespan만 |

**Placeholder scan:** TBD/`similar to Task N` 없음.

**Type consistency:** `app.state.dart_http`, `ExtractionService._http`, `ViewerService._http`, `concurrency=1`.
