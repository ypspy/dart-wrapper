# 추출 진단 Admin 검토 화면 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin `/admin/reviews`에서 진단을 실행하고, 기본 검토 집합에서 한 건을 골라 원문 링크와 함께 판정을 저장한다.

**Architecture:** 포함 규칙과 폼 저장은 `extraction_review_service`에 둔다. 화면은 기존 Admin HTML·htmx·토큰 쿠키를 쓰고, 진단은 기존 `diagnose`를 호출만 한다. 선택 묶음 쿼리는 `key_bundle`이다. 필터 `bundle`과 자연키 묶음이 한 파라미터로 섞이지 않게 한다.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, htmx, SQLAlchemy 2, SQLite, pytest, httpx.

## Global Constraints

- 패키지: `packages/web-api`만. 작업 디렉터리는 `packages/web-api`.
- 테스트: `.\.venv\Scripts\python.exe -m pytest <파일> -q --tb=short`. Windows에서 pytest가 통과 후 hang하면 해당 파일 테스트가 모두 통과한 뒤 hang으로 본다.
- 주석·Docstring·로그·사용자 메시지는 한국어.
- 파서·`EXTRACTOR_VERSION`·후보 규칙·연구 패널 규칙은 바꾸지 않는다. 원문 HTML은 저장하지 않고 DART를 호출하지 않는다.
- `audit_report_facts`, `disclosures`, `entries`, `corps`는 읽기만 한다. 이 화면은 `extraction_reviews`의 `verdict`, `tag`, `note`만 쓰고, 진단 저장은 기존 `diagnose`가 한다.
- 목록 포함 규칙은 `export_tsv(..., next_slice=False)`와 같다. 금지 신호 전부, IQR 순번 1–5, `rare_code`·`auditor_invalid`·`fail`. `active=false`와 순번 6 이상은 열지도 저장하지도 않는다.
- 태그 허용값: `as_written`, `real_magnitude`, `rare_but_valid`, `other`. 빈 태그는 빈 문자열로 저장한다. 폼은 `-`를 보내지 않고, `-`가 오면 허용 밖 태그로 거부한다.
- 한 페이지는 50건. `page`가 1보다 작으면 1. 마지막 페이지를 넘으면 빈 목록.
- 필터 `bundle`은 `BUNDLE_KEYS`만, `verdict`는 `hold`·`source`·`logic`만. 그 밖은 필터 없음.
- 정렬: 연구 패널 먼저, `queue_order`가 있는 행, 없는 행, `queue_order` 오름차순, `stratum`, `signal`, `rcept_no`, `dcm_no`.
- 스펙: `docs/superpowers/specs/2026-09-28-extraction-review-admin-design.md`.

## File map

| 파일 | 책임 |
|------|------|
| `app/services/extraction_review_service.py` | 기본 집합 조회, 폼 저장. 포함 규칙은 export와 공유 |
| `app/api/admin/reviews.py` | 조회·진단·판정 HTML |
| `app/main.py` | 라우터 등록 |
| `app/templates/admin/base.html` | 검토 메뉴 |
| `app/templates/admin/reviews.html` | 진단 버튼, 목록, 상세 칸 |
| `app/templates/admin/partials/review_detail.html` | 오른쪽 상세·폼 |
| `tests/test_extraction_review_service.py` | 조회·저장 |
| `tests/test_admin_reviews_ui.py` | 화면 |

---

### Task 1: 기본 집합 조회와 폼 저장

**Files:**
- Modify: `packages/web-api/app/services/extraction_review_service.py`
- Test: `packages/web-api/tests/test_extraction_review_service.py`

**Interfaces:**
- Consumes: `_load_active_reviews`, `_in_default_slice`, `ExtractionReview`, `ExtractionReviewError`, `BUNDLE_KEYS`
- Produces:
  - `REVIEW_PAGE_SIZE: int = 50`
  - `async def list_default_reviews(session: AsyncSession, *, bundle: str, verdict: str, page: int) -> tuple[list[ExtractionReview], int]`
  - `async def save_review_form(session: AsyncSession, *, rcept_no: str, dcm_no: str, bundle: str, signal: str, subject: str, verdict: str, tag: str, note: str) -> ExtractionReview`
  - commit은 호출자. 실패 시 세션의 그 행은 바꾸지 않는다.

- [ ] **Step 1: Write the failing test**

`tests/test_extraction_review_service.py`에 이 테스트를 추가한다. 파일에 있는 `_review`와 `sessionmaker_fixture`를 쓴다.

```python
from app.services.extraction_review_service import (
    REVIEW_PAGE_SIZE,
    list_default_reviews,
    save_review_form,
)


async def test_list_default_reviews_sorts_panel_and_drops_queue_six(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_review(rcept_no="20200331000003", in_research_panel=False, queue_order=1))
        session.add(
            _review(
                rcept_no="20200331000001",
                signal="hours_nonpositive",
                subject="audit_current_total",
                tail="",
                queue_order=None,
                in_research_panel=True,
            )
        )
        session.add(_review(rcept_no="20200331000002", in_research_panel=True, queue_order=2))
        session.add(
            _review(
                rcept_no="20200331000004",
                queue_order=6,
                subject="total_equity",
                in_research_panel=True,
            )
        )
        await session.commit()
        rows, total = await list_default_reviews(session, bundle="", verdict="", page=1)
    assert total == 3
    assert [row.rcept_no for row in rows] == [
        "20200331000002",
        "20200331000001",
        "20200331000003",
    ]


async def test_list_default_reviews_pages_and_filters(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        for index in range(REVIEW_PAGE_SIZE + 1):
            session.add(
                _review(
                    rcept_no=f"20200331{index:06d}",
                    signal="hours_nonpositive",
                    subject="audit_current_total",
                    tail="",
                    queue_order=None,
                    in_research_panel=False,
                    bundle="hours",
                )
            )
        await session.commit()
        first, total = await list_default_reviews(session, bundle="nope", verdict="nope", page=0)
        second, _ = await list_default_reviews(session, bundle="hours", verdict="hold", page=2)
        none, _ = await list_default_reviews(session, bundle="accounts", verdict="", page=1)
        past, _ = await list_default_reviews(session, bundle="", verdict="", page=99)
    assert total == REVIEW_PAGE_SIZE + 1
    assert len(first) == REVIEW_PAGE_SIZE
    assert first[0].rcept_no == "20200331000000"
    assert [row.rcept_no for row in second] == [f"20200331{REVIEW_PAGE_SIZE:06d}"]
    assert none == []
    assert past == []


async def test_save_review_form_writes_three_fields_and_clears_tag(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_review(tag="as_written", note="이전 판정=source\n유지"))
        await session.commit()
        saved = await save_review_form(
            session,
            rcept_no="20200331000001",
            dcm_no="11111",
            bundle="accounts",
            signal="iqr_high",
            subject="total_asset",
            verdict="source",
            tag="",
            note="이전 판정=source\n유지",
        )
        await session.commit()
    assert saved.verdict == "source"
    assert saved.tag == ""
    assert saved.note == "이전 판정=source\n유지"
    assert saved.raw_value == "10"
    assert saved.active is True


@pytest.mark.parametrize(
    ("verdict", "tag", "message"),
    [
        ("nope", "", "판정은 hold, source, logic만 적을 수 있습니다."),
        ("source", "nope", "태그는 as_written, real_magnitude, rare_but_valid, other만 적을 수 있습니다."),
        ("logic", "as_written", "logic 또는 hold 판정에는 태그를 적을 수 없습니다."),
        ("hold", "other", "logic 또는 hold 판정에는 태그를 적을 수 없습니다."),
    ],
)
async def test_save_review_form_rejects_without_write(
    sessionmaker_fixture, verdict: str, tag: str, message: str
) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_review())
        await session.commit()
        with pytest.raises(ExtractionReviewError, match=message):
            await save_review_form(
                session,
                rcept_no="20200331000001",
                dcm_no="11111",
                bundle="accounts",
                signal="iqr_high",
                subject="total_asset",
                verdict=verdict,
                tag=tag,
                note="그대로",
            )
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.verdict == "hold"
    assert row.tag == ""
    assert row.note == ""


async def test_save_review_form_rejects_outside_default_slice(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_review(queue_order=6))
        session.add(
            _review(
                rcept_no="20200331000009",
                active=False,
                signal="hours_nonpositive",
                subject="audit_current_total",
            )
        )
        await session.commit()
        for rcept_no, signal, subject in (
            ("20200331000001", "iqr_high", "total_asset"),
            ("20200331000009", "hours_nonpositive", "audit_current_total"),
            ("없는번호", "iqr_high", "total_asset"),
        ):
            with pytest.raises(ExtractionReviewError, match="해당하는 검토 행이 없습니다."):
                await save_review_form(
                    session,
                    rcept_no=rcept_no,
                    dcm_no="11111",
                    bundle="accounts",
                    signal=signal,
                    subject=subject,
                    verdict="logic",
                    tag="",
                    note="",
                )
        kept = (await session.execute(select(ExtractionReview))).scalars().all()
    assert {row.verdict for row in kept} == {"hold"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_review_service.py::test_list_default_reviews_sorts_panel_and_drops_queue_six -q --tb=short`

Expected: FAIL (`list_default_reviews` 없음)

- [ ] **Step 3: Write minimal implementation**

`extraction_review_service.py`에 `BUNDLE_KEYS` import를 추가한다. `_in_default_slice`는 그대로 두고 `list_default_reviews`와 `save_review_form`만 추가한다. `export_tsv`의 포함 조건은 계속 `_in_default_slice`를 호출한다.

```python
from app.extracting.field_bundles import BUNDLE_KEYS, DART_DOCUMENT_VIEW

REVIEW_PAGE_SIZE = 50
_FORM_VERDICTS = frozenset({"hold", "source", "logic"})


def _review_sort_key(row: ExtractionReview) -> tuple[int, int, int, str, str, str, str]:
    """연구 패널, 순번 있는 행, 순번, 층, 신호, 접수번호, 문서번호."""
    queue_order = 0 if row.queue_order is None else row.queue_order
    return (
        0 if row.in_research_panel else 1,
        0 if row.queue_order is not None else 1,
        queue_order,
        row.stratum,
        row.signal,
        row.rcept_no,
        row.dcm_no,
    )


async def list_default_reviews(
    session: AsyncSession,
    *,
    bundle: str,
    verdict: str,
    page: int,
) -> tuple[list[ExtractionReview], int]:
    """기본 집합을 정렬·필터한 뒤 한 페이지와 전체 건수를 돌려준다."""
    rows = [row for row in await _load_active_reviews(session) if _in_default_slice(row)]
    if bundle in BUNDLE_KEYS:
        rows = [row for row in rows if row.bundle == bundle]
    if verdict in _FORM_VERDICTS:
        rows = [row for row in rows if row.verdict == verdict]
    rows.sort(key=_review_sort_key)
    total = len(rows)
    page_index = 1 if page < 1 else page
    start = (page_index - 1) * REVIEW_PAGE_SIZE
    return rows[start : start + REVIEW_PAGE_SIZE], total


async def save_review_form(
    session: AsyncSession,
    *,
    rcept_no: str,
    dcm_no: str,
    bundle: str,
    signal: str,
    subject: str,
    verdict: str,
    tag: str,
    note: str,
) -> ExtractionReview:
    """기본 집합의 판정·태그·메모만 바꾼다. commit은 호출자가 한다."""
    if verdict not in _FORM_VERDICTS:
        raise ExtractionReviewError("판정은 hold, source, logic만 적을 수 있습니다.")
    if tag != "" and tag not in _ALLOWED_TAGS:
        raise ExtractionReviewError(
            "태그는 as_written, real_magnitude, rare_but_valid, other만 적을 수 있습니다."
        )
    if verdict in _TAG_BLOCKING_VERDICTS and tag != "":
        raise ExtractionReviewError("logic 또는 hold 판정에는 태그를 적을 수 없습니다.")
    stored = await _load_active_reviews(session)
    row = next(
        (
            item
            for item in stored
            if _review_key(item) == (rcept_no, dcm_no, bundle, signal, subject)
            and _in_default_slice(item)
        ),
        None,
    )
    if row is None:
        raise ExtractionReviewError("해당하는 검토 행이 없습니다.")
    row.verdict = verdict
    row.tag = tag
    row.note = note
    return row
```

`_ALLOWED_TAGS`와 `_TAG_BLOCKING_VERDICTS`는 이 파일에 이미 있다. 검증을 통과하기 전에는 행을 찾지 않아도 되지만, 없는 키와 잘못된 판정이 함께면 판정 오류가 우선이다. 위 테스트는 그 순서와 같다.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_review_service.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/services/extraction_review_service.py packages/web-api/tests/test_extraction_review_service.py
git commit -m "feat(web-api): 검토 화면용 기본 집합 조회와 판정 저장을 둔다."
```

---

### Task 2: 검토 페이지 목록

**Files:**
- Create: `packages/web-api/app/api/admin/reviews.py`
- Create: `packages/web-api/app/templates/admin/reviews.html`
- Create: `packages/web-api/app/templates/admin/partials/review_detail.html`
- Modify: `packages/web-api/app/main.py`
- Modify: `packages/web-api/app/templates/admin/base.html`
- Test: `packages/web-api/tests/test_admin_reviews_ui.py`

**Interfaces:**
- Consumes: `list_default_reviews`, `get_session`, `Settings`, `ADMIN_TOKEN_COOKIE`
- Produces: `GET /admin/reviews`. 쿼리 `page`, `bundle`, `verdict`. 토큰 없으면 307 `/admin/token`.

- [ ] **Step 1: Write the failing test**

`tests/test_admin_reviews_ui.py`

```python
"""Admin 진단 검토 화면."""

from __future__ import annotations

from collections.abc import Callable

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_session
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.extracting.constants import EXTRACTOR_VERSION
from app.main import create_app
from app.models.extraction_review import ExtractionReview
from app.services.extraction_review_service import REVIEW_PAGE_SIZE

ClientFactory = Callable[[FastAPI], httpx.AsyncClient]


def _review(**overrides: object) -> ExtractionReview:
    values: dict[str, object] = {
        "rcept_no": "20200331000001",
        "dcm_no": "11111",
        "bundle": "accounts",
        "signal": "iqr_high",
        "subject": "total_asset",
        "extractor_version": EXTRACTOR_VERSION,
        "in_research_panel": True,
        "stratum": "F001|separate|total_asset",
        "tail": "high",
        "queue_order": 1,
        "raw_value": "10",
        "active": True,
        "verdict": "hold",
        "tag": "",
        "note": "",
    }
    values.update(overrides)
    return ExtractionReview(**values)  # type: ignore[arg-type]


async def _app() -> tuple[FastAPI, async_sessionmaker[AsyncSession]]:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)
    app = create_app()

    async def _session():
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    return app, sessionmaker


async def test_reviews_page_redirects_without_token(client_factory: ClientFactory) -> None:
    app, _sessionmaker = await _app()
    async with client_factory(app) as client:
        response = await client.get("/admin/reviews")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/admin/token")


async def test_reviews_page_lists_default_slice_and_nav(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_review(rcept_no="20200331000003", in_research_panel=False, queue_order=1))
        session.add(
            _review(
                rcept_no="20200331000001",
                signal="hours_nonpositive",
                subject="audit_current_total",
                tail="",
                queue_order=None,
            )
        )
        session.add(_review(rcept_no="20200331000002", queue_order=2, subject="total_equity"))
        session.add(_review(rcept_no="20200331000004", queue_order=6, subject="net_income"))
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/reviews")
    text = response.text
    assert response.status_code == 200
    assert 'href="/admin/reviews" class="is-selected"' in text
    assert "검토" in text
    assert "진단을 실행하면 요약이 나옵니다." in text
    assert "왼쪽에서 한 건을 고르세요." in text
    assert text.index("20200331000002") < text.index("20200331000001")
    assert text.index("20200331000001") < text.index("20200331000003")
    assert "20200331000004" not in text


async def test_reviews_page_filters_and_pages(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        for index in range(REVIEW_PAGE_SIZE + 1):
            session.add(
                _review(
                    rcept_no=f"20200331{index:06d}",
                    signal="hours_nonpositive",
                    subject="audit_current_total",
                    tail="",
                    queue_order=None,
                    in_research_panel=False,
                    bundle="hours",
                )
            )
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        page2 = await client.get("/admin/reviews", params={"page": 2, "bundle": "hours", "verdict": "hold"})
        ignored = await client.get("/admin/reviews", params={"bundle": "nope", "verdict": "nope"})
    assert f"20200331{REVIEW_PAGE_SIZE:06d}" in page2.text
    assert "20200331000000" not in page2.text
    assert "20200331000000" in ignored.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_admin_reviews_ui.py::test_reviews_page_redirects_without_token -q --tb=short`

Expected: FAIL (404)

- [ ] **Step 3: Write minimal implementation**

`app/main.py`의 admin import 옆에 `from app.api.admin import reviews as admin_reviews`를 추가하고, `admin_ui.router` 다음에 `app.include_router(admin_reviews.router)`를 둔다.

`app/templates/admin/base.html` 운영 메뉴의 추출 링크 다음에 한 줄을 넣는다.

```html
    <a href="/admin/reviews" class="{% if ops_section == 'reviews' %}is-selected{% endif %}">검토</a>
```

`app/templates/admin/partials/review_detail.html`

```html
<section id="review-detail">
  <p>왼쪽에서 한 건을 고르세요.</p>
</section>
```

`app/templates/admin/reviews.html`

```html
{% extends "admin/base.html" %}
{% block title %}추출 진단 검토{% endblock %}
{% block content %}
<header class="ops-topbar">
  <div>
    <h2>추출 진단 검토</h2>
    <p class="muted">진단을 실행하면 요약이 나옵니다.</p>
    <form method="post" action="/admin/reviews/diagnose?page={{ page }}&amp;bundle={{ bundle }}&amp;verdict={{ verdict }}">
      <button type="submit">진단 실행</button>
    </form>
  </div>
</header>
<div class="ops-grid">
  <section aria-label="검토 목록">
    <form method="get" action="/admin/reviews" class="inline">
      <label>묶음
        <input type="text" name="bundle" value="{{ bundle }}">
      </label>
      <label>판정
        <input type="text" name="verdict" value="{{ verdict }}">
      </label>
      <button type="submit">필터</button>
    </form>
    <table>
      <tbody>
        {% for row in rows %}
        <tr>
          <td>{{ "패널" if row.in_research_panel else "" }}</td>
          <td>{{ row.bundle }}</td>
          <td>{{ row.signal }}</td>
          <td>{{ row.stratum }}</td>
          <td>{{ row.queue_order if row.queue_order is not none else "" }}</td>
          <td>{{ row.verdict }}</td>
          <td>{{ row.rcept_no }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% if total > page_size %}
    <p>
      {% if page > 1 %}
      <a href="/admin/reviews?page={{ page - 1 }}&amp;bundle={{ bundle }}&amp;verdict={{ verdict }}">이전</a>
      {% endif %}
      <a href="/admin/reviews?page={{ page + 1 }}&amp;bundle={{ bundle }}&amp;verdict={{ verdict }}">다음</a>
    </p>
    {% endif %}
  </section>
  {% include "admin/partials/review_detail.html" %}
</div>
{% endblock %}
```

`app/api/admin/reviews.py`

```python
"""Admin 추출 진단 검토 화면."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ADMIN_TOKEN_COOKIE, get_session, get_settings_dep
from app.config import Settings
from app.services.extraction_review_service import REVIEW_PAGE_SIZE, list_default_reviews

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/admin", tags=["Admin UI"], include_in_schema=False)


def _has_valid_token(request: Request, settings: Settings) -> bool:
    """쿠키의 Admin 토큰이 설정과 같은지 확인한다."""
    return request.cookies.get(ADMIN_TOKEN_COOKIE) == settings.admin_token


@router.get("/reviews", response_class=HTMLResponse, summary="추출 진단 검토")
async def reviews_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
    page: int = Query(default=1),
    bundle: str = Query(default=""),
    verdict: str = Query(default=""),
) -> HTMLResponse | RedirectResponse:
    """기본 검토 집합을 보여 준다. 진단 요약은 이 조회에서 계산하지 않는다."""
    if not _has_valid_token(request, settings):
        return RedirectResponse("/admin/token")
    rows, total = await list_default_reviews(session, bundle=bundle, verdict=verdict, page=page)
    shown_page = 1 if page < 1 else page
    return templates.TemplateResponse(
        request,
        "admin/reviews.html",
        {
            "ops_section": "reviews",
            "rows": rows,
            "total": total,
            "page": shown_page,
            "page_size": REVIEW_PAGE_SIZE,
            "bundle": bundle,
            "verdict": verdict,
        },
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_admin_reviews_ui.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/api/admin/reviews.py packages/web-api/app/main.py packages/web-api/app/templates/admin/base.html packages/web-api/app/templates/admin/reviews.html packages/web-api/app/templates/admin/partials/review_detail.html packages/web-api/tests/test_admin_reviews_ui.py
git commit -m "feat(web-api): Admin 검토 목록을 보여 준다."
```

---

### Task 3: 한 건 상세와 원문 링크

**Files:**
- Modify: `packages/web-api/app/api/admin/reviews.py`
- Modify: `packages/web-api/app/templates/admin/reviews.html`
- Modify: `packages/web-api/app/templates/admin/partials/review_detail.html`
- Modify: `packages/web-api/app/services/extraction_review_service.py`
- Test: `packages/web-api/tests/test_admin_reviews_ui.py`

**Interfaces:**
- Consumes: `DART_DOCUMENT_VIEW`, `_in_default_slice`, `_load_active_reviews`, `_review_key`
- Produces: `async def get_default_review(session, *, rcept_no: str, dcm_no: str, bundle: str, signal: str, subject: str) -> ExtractionReview | None`. 없거나 비활성이거나 기본 집합 밖이면 `None`. `GET` 선택 쿼리는 `rcept_no`, `dcm_no`, `key_bundle`, `signal`, `subject`. `HX-Request`가 있으면 상세 partial만 반환한다.

- [ ] **Step 1: Write the failing test**

`tests/test_admin_reviews_ui.py`에 추가한다.

```python
async def test_reviews_page_opens_default_row_and_rejects_queue_six(
    client_factory: ClientFactory,
) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_review(raw_value="10", note="이전 판정=source\n유지"))
        session.add(_review(rcept_no="20200331000006", queue_order=6, subject="total_equity"))
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        opened = await client.get(
            "/admin/reviews",
            params={
                "rcept_no": "20200331000001",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_asset",
            },
        )
        partial = await client.get(
            "/admin/reviews",
            params={
                "rcept_no": "20200331000001",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_asset",
            },
            headers={"HX-Request": "true"},
        )
        missing = await client.get(
            "/admin/reviews",
            params={
                "rcept_no": "20200331000006",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_equity",
            },
        )
    assert "이전 판정=source" in opened.text
    assert "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20200331000001&amp;dcmNo=11111" in opened.text
    assert 'target="_blank"' in opened.text
    assert "DART 수집 운영" not in partial.text
    assert "10" in partial.text
    assert "이 행은 기본 검토 목록에 없습니다." in missing.text
    assert "20200331000006" not in missing.text
    assert "total_equity" not in missing.text
```

`queue_order=6` 행의 `signal`은 기본 `_review`의 `iqr_high`다. `missing` 요청의 `signal`도 `iqr_high`다.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_admin_reviews_ui.py::test_reviews_page_opens_default_row_and_rejects_queue_six -q --tb=short`

Expected: FAIL (원문 주소 또는 안내 문구 없음)

- [ ] **Step 3: Write minimal implementation**

`extraction_review_service.py`에 추가한다.

```python
async def get_default_review(
    session: AsyncSession,
    *,
    rcept_no: str,
    dcm_no: str,
    bundle: str,
    signal: str,
    subject: str,
) -> ExtractionReview | None:
    """활성 기본 집합의 한 행. 없으면 None."""
    stored = await _load_active_reviews(session)
    return next(
        (
            item
            for item in stored
            if _review_key(item) == (rcept_no, dcm_no, bundle, signal, subject)
            and _in_default_slice(item)
        ),
        None,
    )
```

`save_review_form`의 행 찾기는 이 함수로 바꾼다. 검증 오류는 여전히 행을 찾기 전에 던진다.

`reviews_page`에 쿼리 `rcept_no: str | None = None`, `dcm_no: str = ""`, `key_bundle: str = ""`, `signal: str = ""`, `subject: str = ""`를 추가한다. `rcept_no`가 `None`이면 선택 없음. 있으면 `get_default_review`를 호출한다.

템플릿 컨텍스트에 `selected`와 `viewer_url`을 넣는다. `viewer_url`은 `DART_DOCUMENT_VIEW.format(rcept_no=selected.rcept_no, dcm_no=selected.dcm_no)`다. 선택이 없으면 빈 문자열.

`HX-Request` 헤더가 있으면 `admin/partials/review_detail.html`만 반환한다. 없으면 전체 페이지다.

목록의 각 행 링크:

```html
<a
  href="/admin/reviews?page={{ page }}&amp;bundle={{ bundle }}&amp;verdict={{ verdict }}&amp;rcept_no={{ row.rcept_no }}&amp;dcm_no={{ row.dcm_no }}&amp;key_bundle={{ row.bundle }}&amp;signal={{ row.signal }}&amp;subject={{ row.subject }}"
  hx-get="/admin/reviews?page={{ page }}&amp;bundle={{ bundle }}&amp;verdict={{ verdict }}&amp;rcept_no={{ row.rcept_no }}&amp;dcm_no={{ row.dcm_no }}&amp;key_bundle={{ row.bundle }}&amp;signal={{ row.signal }}&amp;subject={{ row.subject }}"
  hx-target="#review-detail"
  hx-swap="outerHTML"
  hx-push-url="true"
>{{ row.rcept_no }}</a>
```

`review_detail.html`은 세 갈래다.

- `selected`가 있으면 자연키, 패널 여부, 층, 꼬리, 순번, `raw_value`, `extractor_version`, 새 탭 링크, `textarea name="note"`에 기존 메모 전체.
- `rcept_no` 쿼리가 있었는데 `selected`가 없으면 `이 행은 기본 검토 목록에 없습니다.`
- 그 외는 `왼쪽에서 한 건을 고르세요.`

원문 링크:

```html
<a href="{{ viewer_url }}" target="_blank" rel="noreferrer">원문</a>
```

Jinja가 `&`를 `&amp;`로 이스케이프한다. 폼의 저장 버튼은 Task 5에서 연결한다. 이 태스크의 폼은 보여 주기만 한다.

```html
<form id="review-verdict-form">
  <select name="verdict">
    <option value="hold" {% if selected.verdict == "hold" %}selected{% endif %}>hold</option>
    <option value="source" {% if selected.verdict == "source" %}selected{% endif %}>source</option>
    <option value="logic" {% if selected.verdict == "logic" %}selected{% endif %}>logic</option>
  </select>
  <select name="tag">
    <option value="" {% if selected.tag == "" %}selected{% endif %}></option>
    <option value="as_written" {% if selected.tag == "as_written" %}selected{% endif %}>as_written</option>
    <option value="real_magnitude" {% if selected.tag == "real_magnitude" %}selected{% endif %}>real_magnitude</option>
    <option value="rare_but_valid" {% if selected.tag == "rare_but_valid" %}selected{% endif %}>rare_but_valid</option>
    <option value="other" {% if selected.tag == "other" %}selected{% endif %}>other</option>
  </select>
  <textarea name="note">{{ selected.note }}</textarea>
</form>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_admin_reviews_ui.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/api/admin/reviews.py packages/web-api/app/services/extraction_review_service.py packages/web-api/app/templates/admin/reviews.html packages/web-api/app/templates/admin/partials/review_detail.html packages/web-api/tests/test_admin_reviews_ui.py
git commit -m "feat(web-api): 검토 한 건의 원문 링크와 판정 폼을 연다."
```

---

### Task 4: 진단 실행

**Files:**
- Modify: `packages/web-api/app/api/admin/reviews.py`
- Modify: `packages/web-api/app/templates/admin/reviews.html`
- Test: `packages/web-api/tests/test_admin_reviews_ui.py`

**Interfaces:**
- Consumes: `diagnose`, `ExtractionReviewError`, `format_summary`, `AuditReportFact`, `ExtractionJob`, `Disclosure`
- Produces: `POST /admin/reviews/diagnose`. 성공 시 commit하고 전체 페이지에 `format_summary` 줄을 그린다. 실패 시 commit하지 않고 문구만 보인다.

- [ ] **Step 1: Write the failing test**

```python
from sqlalchemy import select

from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
from app.models.extraction_job import ExtractionJob


def _fact() -> AuditReportFact:
    return AuditReportFact(
        rcept_no="20200331000001",
        dcm_no="11111",
        source_report_type="F001",
        fs_scope="separate",
        fetch_status="ok",
        extractor_version=EXTRACTOR_VERSION,
        hours_status="not_found",
        conflicts=[],
    )


async def test_diagnose_shows_summary_and_keeps_catalog(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_fact())
        session.add(Disclosure(rcept_no="20200331000001", corp_name="그대로", rcept_dt="20200331"))
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post("/admin/reviews/diagnose")
    assert response.status_code == 200
    assert "실패 " in response.text
    async with sessionmaker() as session:
        fact = (await session.execute(select(AuditReportFact))).scalar_one()
        disclosure = (await session.execute(select(Disclosure))).scalar_one()
        reviews = (await session.execute(select(ExtractionReview))).scalars().all()
    assert fact.hours_status == "not_found"
    assert disclosure.corp_name == "그대로"
    assert reviews


async def test_diagnose_running_job_does_not_change_reviews(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_fact())
        session.add(_review(verdict="logic", note="유지"))
        session.add(
            ExtractionJob(
                job_id="job-1",
                status="running",
                extractor_id="audit_opinion",
                mode="extract",
                params={},
            )
        )
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post("/admin/reviews/diagnose")
    assert "추출 잡이 진행 중이라 진단을 시작하지 않습니다." in response.text
    async with sessionmaker() as session:
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.verdict == "logic"
    assert row.note == "유지"


async def test_diagnose_empty_population_keeps_active(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_review(active=True, verdict="source", tag="as_written"))
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post("/admin/reviews/diagnose")
    assert "현재 추출기 ok 행이 없습니다." in response.text
    async with sessionmaker() as session:
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.active is True
    assert row.verdict == "source"
    assert row.tag == "as_written"


async def test_diagnose_requires_token(client_factory: ClientFactory) -> None:
    app, _sessionmaker = await _app()
    async with client_factory(app) as client:
        response = await client.post("/admin/reviews/diagnose")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/admin/token")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_admin_reviews_ui.py::test_diagnose_shows_summary_and_keeps_catalog -q --tb=short`

Expected: FAIL (405 또는 404)

- [ ] **Step 3: Write minimal implementation**

`reviews.py`에 `POST /reviews/diagnose`를 추가한다. 쿼리 `page`, `bundle`, `verdict`, `rcept_no`, `dcm_no`, `key_bundle`, `signal`, `subject`는 GET과 같다. 토큰이 없으면 `/admin/token`로 보낸다.

```python
from app.reviewing.candidates import format_summary
from app.services.extraction_review_service import (
    REVIEW_PAGE_SIZE,
    ExtractionReviewError,
    diagnose,
    get_default_review,
    list_default_reviews,
)


@router.post("/reviews/diagnose", response_class=HTMLResponse, summary="추출 진단 실행")
async def reviews_diagnose(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
    page: int = Query(default=1),
    bundle: str = Query(default=""),
    verdict: str = Query(default=""),
    rcept_no: str | None = Query(default=None),
    dcm_no: str = Query(default=""),
    key_bundle: str = Query(default=""),
    signal: str = Query(default=""),
    subject: str = Query(default=""),
) -> HTMLResponse | RedirectResponse:
    """진단을 저장하고 요약을 페이지 위에 그린다. 새로고침은 이 POST를 다시 보낼 수 있다."""
    if not _has_valid_token(request, settings):
        return RedirectResponse("/admin/token")
    notice = ""
    summary_lines: list[str] = []
    try:
        summary = await diagnose(session)
        await session.commit()
        summary_lines = [format_summary(row) for row in summary]
    except ExtractionReviewError as exc:
        notice = str(exc)
    return await _render_reviews(
        request,
        session,
        page=page,
        bundle=bundle,
        verdict=verdict,
        rcept_no=rcept_no,
        dcm_no=dcm_no,
        key_bundle=key_bundle,
        signal=signal,
        subject=subject,
        notice=notice,
        summary_lines=summary_lines,
    )
```

GET도 `_render_reviews`를 쓰게 바꾼다. `notice` 기본값은 `""`, `summary_lines` 기본값은 `[]`다. 템플릿은 `summary_lines`가 있으면 그 줄을 `<pre>` 또는 문단으로 모두 보여주고, 없으면 `진단을 실행하면 요약이 나옵니다.`를 보여 준다. `notice`가 있으면 `role="status"` 문단으로 보여 준다.

진단 폼의 `action`은 현재 필터와 선택 쿼리를 유지한다.

```html
<form method="post" action="/admin/reviews/diagnose?page={{ page }}&amp;bundle={{ bundle }}&amp;verdict={{ verdict }}{% if rcept_no %}&amp;rcept_no={{ rcept_no }}&amp;dcm_no={{ dcm_no }}&amp;key_bundle={{ key_bundle }}&amp;signal={{ signal }}&amp;subject={{ subject }}{% endif %}">
```

컨텍스트에 `rcept_no`, `dcm_no`, `key_bundle`, `signal`, `subject`를 넣는다. 선택이 없으면 `rcept_no`는 빈 문자열로 템플릿에 넘긴다.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_admin_reviews_ui.py tests/test_extraction_review_service.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/api/admin/reviews.py packages/web-api/app/templates/admin/reviews.html packages/web-api/tests/test_admin_reviews_ui.py
git commit -m "feat(web-api): 검토 화면에서 진단을 실행한다."
```

---

### Task 5: 판정 저장

**Files:**
- Modify: `packages/web-api/app/api/admin/reviews.py`
- Modify: `packages/web-api/app/templates/admin/partials/review_detail.html`
- Modify: `packages/web-api/app/templates/admin/reviews.html`
- Test: `packages/web-api/tests/test_admin_reviews_ui.py`

**Interfaces:**
- Consumes: `save_review_form`, `ExtractionReviewError`, Task 3의 상세 partial
- Produces: `POST /admin/reviews/verdict`. 폼 필드 `rcept_no`, `dcm_no`, `key_bundle`, `signal`, `subject`, `verdict`, `tag`, `note`. 성공 시 commit하고 상세를 바꾸며, 같은 응답에 목록 행을 `hx-swap-oob="outerHTML"`로 넣는다. 실패 시 commit하지 않고 상세에 오류를 보인다.

- [ ] **Step 1: Write the failing test**

```python
async def test_verdict_requires_token(client_factory: ClientFactory) -> None:
    app, _sessionmaker = await _app()
    async with client_factory(app) as client:
        response = await client.post(
            "/admin/reviews/verdict",
            data={
                "rcept_no": "20200331000001",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_asset",
                "verdict": "logic",
                "tag": "",
                "note": "",
            },
        )
    assert response.status_code == 307
    assert response.headers["location"].endswith("/admin/token")


async def test_verdict_saves_three_fields_and_empty_tag(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_fact())
        session.add(Disclosure(rcept_no="20200331000001", corp_name="그대로", rcept_dt="20200331"))
        session.add(_review(tag="as_written", note="이전 판정=source\n유지", raw_value="10"))
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post(
            "/admin/reviews/verdict",
            data={
                "rcept_no": "20200331000001",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_asset",
                "verdict": "source",
                "tag": "",
                "note": "이전 판정=source\n유지",
            },
        )
    assert response.status_code == 200
    assert "hx-swap-oob" in response.text
    assert 'value="source" selected' in response.text or 'value="source" selected="selected"' in response.text
    async with sessionmaker() as session:
        row = (await session.execute(select(ExtractionReview))).scalar_one()
        fact = (await session.execute(select(AuditReportFact))).scalar_one()
        disclosure = (await session.execute(select(Disclosure))).scalar_one()
    assert row.verdict == "source"
    assert row.tag == ""
    assert row.note == "이전 판정=source\n유지"
    assert row.raw_value == "10"
    assert fact.hours_status == "not_found"
    assert disclosure.corp_name == "그대로"


@pytest.mark.parametrize(
    ("verdict", "tag", "message"),
    [
        ("nope", "", "판정은 hold, source, logic만 적을 수 있습니다."),
        ("source", "-", "태그는 as_written, real_magnitude, rare_but_valid, other만 적을 수 있습니다."),
        ("logic", "as_written", "logic 또는 hold 판정에는 태그를 적을 수 없습니다."),
        ("hold", "other", "logic 또는 hold 판정에는 태그를 적을 수 없습니다."),
    ],
)
async def test_verdict_rejects_and_shows_reason(
    client_factory: ClientFactory, verdict: str, tag: str, message: str
) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_review())
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post(
            "/admin/reviews/verdict",
            data={
                "rcept_no": "20200331000001",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_asset",
                "verdict": verdict,
                "tag": tag,
                "note": "바꾸지마",
            },
        )
    assert message in response.text
    async with sessionmaker() as session:
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.verdict == "hold"
    assert row.tag == ""
    assert row.note == ""


async def test_verdict_rejects_queue_six(client_factory: ClientFactory) -> None:
    app, sessionmaker = await _app()
    async with sessionmaker() as session:
        session.add(_review(queue_order=6, verdict="hold"))
        await session.commit()
    async with client_factory(app) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post(
            "/admin/reviews/verdict",
            data={
                "rcept_no": "20200331000001",
                "dcm_no": "11111",
                "key_bundle": "accounts",
                "signal": "iqr_high",
                "subject": "total_asset",
                "verdict": "logic",
                "tag": "",
                "note": "",
            },
        )
    assert "해당하는 검토 행이 없습니다." in response.text
    async with sessionmaker() as session:
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.verdict == "hold"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_admin_reviews_ui.py::test_verdict_saves_three_fields_and_empty_tag -q --tb=short`

Expected: FAIL (405 또는 404)

- [ ] **Step 3: Write minimal implementation**

상세 폼을 `hx-post="/admin/reviews/verdict"` `hx-target="#review-detail"` `hx-swap="outerHTML"`로 바꾼다. 숨은 필드로 `rcept_no`, `dcm_no`, `key_bundle`, `signal`, `subject`를 넣는다. `verdict`와 `tag`는 셀렉트, `note`는 textarea다.

`POST` 핸들러는 토큰을 확인하고 `save_review_form`을 호출한다. 성공하면 `session.commit()`하고 상세 partial을 반환한다. 그 HTML 끝에 목록 행 하나를 붙인다.

```html
<tr hx-swap-oob="outerHTML" id="review-row-{{ selected.rcept_no }}-{{ selected.dcm_no }}-{{ selected.bundle }}-{{ selected.signal }}-{{ selected.subject }}">
```

목록의 `<tr>`도 같은 `id`를 가진다. 행 안에는 Task 2의 칸과 Task 3의 링크가 있다. 실패하면 commit하지 않고, 같은 상세 partial에 `error` 문구를 넣는다. 폼의 선택값은 요청으로 들어온 `verdict`·`tag`·`note`를 그대로 보여 준다. DB 값은 바꾸지 않는다.

`selected`가 거부로 없으면 상세에는 오류 문구와 `이 행은 기본 검토 목록에 없습니다.`를 함께 둔다. 잘못된 판정·태그는 행이 있으므로 기존 상세에 오류만 추가한다.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_admin_reviews_ui.py tests/test_extraction_review_service.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/api/admin/reviews.py packages/web-api/app/templates/admin/partials/review_detail.html packages/web-api/app/templates/admin/reviews.html packages/web-api/tests/test_admin_reviews_ui.py
git commit -m "feat(web-api): 검토 화면에서 판정·태그·메모를 저장한다."
```
