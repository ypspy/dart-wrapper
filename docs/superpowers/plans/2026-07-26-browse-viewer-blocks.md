# Browse UI · Viewer Blocks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Viewer 정제를 문서 순서 `blocks[]`로 올리고, Public `/browse` HTMX UI(목록 → 목차|본문 2열)로 탐색·열람한다.

**Architecture:** `extract_blocks`가 HTML을 한 번 순회해 heading/paragraph/table을 만든다. `ViewerService`는 그 결과로 `blocks`·`text`(표 제외)·`tables`를 조립한다. Browse UI는 `CatalogQueryService`/`ViewerService`를 서버에서 직접 호출하며, 공시 상세는 왼쪽 목차·오른쪽 본문(HTMX partial)이다.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, Jinja2, HTMX, BeautifulSoup4/lxml, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-07-26-browse-viewer-blocks-design.md`

## Global Constraints

- Python 3.11+, 모든 함수 입·출력 타입 힌트
- 주석·Docstring·로그·예외/사용자 메시지는 **한국어**
- I/O는 `async`/`await`
- Black / Flake8 (line length 100)
- DB에는 메타만 저장. 원문·정제 텍스트·표 저장 금지
- 테스트는 실제 DART를 호출하지 않는다
- Browse는 인증 없음. Admin 템플릿·CSS와 섞지 않음
- 작업 디렉터리: `packages/web-api` (명령은 이 디렉터리 기준)
- URL/`rcp_no`와 DB/`rcept_no`는 같은 접수번호

## File Structure

| Path | Responsibility |
|------|----------------|
| `app/schemas/viewer.py` | `HeadingBlock`/`ParagraphBlock`/`TableBlock`, `SectionContent.blocks` |
| `app/parsing/blocks.py` | `extract_blocks`, `blocks_to_text`, `blocks_to_tables` |
| `app/parsing/cleaner.py` | `extract_text` → blocks 유도 래퍼 |
| `app/parsing/tables.py` | `extract_tables` → blocks 유도 래퍼 (기존 dict 형태 유지) |
| `app/services/viewer_service.py` | `_to_section`에서 blocks 한 번 파싱 |
| `app/api/browse/__init__.py` | 패키지 |
| `app/api/browse/ui.py` | `/browse` 라우터 |
| `app/main.py` | Browse 라우터 + `/static` StaticFiles |
| `app/static/browse.css` | Browse 전용 스타일 |
| `app/templates/browse/*.html` | 목록·2열·partial |
| `tests/test_blocks.py` | 블록 파서 |
| `tests/test_cleaner.py` | text에 표 미포함 등 갱신 |
| `tests/test_viewer_api.py` / `test_viewer_service.py` | blocks 필드 |
| `tests/test_browse_ui.py` | Browse HTML |
| `README.md` (web-api + 루트) | `/browse` 문서 |

---

### Task 1: Viewer Block 스키마

**Files:**
- Modify: `packages/web-api/app/schemas/viewer.py`
- Test: `packages/web-api/tests/test_viewer_schema.py` (신규)

**Interfaces:**
- Consumes: 기존 `TableData`, `SectionContent`
- Produces:
  - `HeadingBlock(type="heading", level: int, text: str)`
  - `ParagraphBlock(type="paragraph", text: str)`
  - `TableBlock(type="table", headers: list[str], rows: list[list[str]])`
  - `ContentBlock = Annotated[HeadingBlock | ParagraphBlock | TableBlock, Field(discriminator="type")]`
  - `SectionContent.blocks: list[ContentBlock]` (기본 `[]`)

- [ ] **Step 1: Write the failing test**

```python
"""Viewer 블록 스키마 테스트."""

from __future__ import annotations

from app.schemas.viewer import ContentBlock, HeadingBlock, SectionContent, TableBlock


def test_section_content_accepts_discriminated_blocks() -> None:
    section = SectionContent(
        entry_id="e_1",
        source="body",
        blocks=[
            {"type": "heading", "level": 2, "text": "재무상태표"},
            {"type": "paragraph", "text": "자산총계는 다음과 같다."},
            {
                "type": "table",
                "headers": ["과목", "당기"],
                "rows": [["자산총계", "1,000"]],
            },
        ],
    )

    assert isinstance(section.blocks[0], HeadingBlock)
    assert section.blocks[0].level == 2
    assert section.blocks[1].text == "자산총계는 다음과 같다."
    assert isinstance(section.blocks[2], TableBlock)
    assert section.blocks[2].rows[0][1] == "1,000"


def test_content_block_union_roundtrip() -> None:
    raw = {"type": "heading", "level": 1, "text": "제목"}
    block: ContentBlock = HeadingBlock.model_validate(raw)
    assert block.model_dump() == raw
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_viewer_schema.py -v`  
Expected: FAIL (`ContentBlock` / `HeadingBlock` import 실패)

- [ ] **Step 3: Implement schema**

`app/schemas/viewer.py`에 추가·수정:

```python
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class HeadingBlock(BaseModel):
    """제목 블록."""

    type: Literal["heading"] = "heading"
    level: int = Field(ge=1, le=3)
    text: str


class ParagraphBlock(BaseModel):
    """문단 블록."""

    type: Literal["paragraph"] = "paragraph"
    text: str


class TableBlock(BaseModel):
    """표 블록. TableData와 동일 구조에 type만 붙인다."""

    type: Literal["table"] = "table"
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


ContentBlock = Annotated[
    HeadingBlock | ParagraphBlock | TableBlock,
    Field(discriminator="type"),
]


class SectionContent(BaseModel):
    """leaf 섹션 1건의 정제 결과."""

    entry_id: str
    source: str
    dcm_no: str | None = None
    ele_id: str | None = None
    path: list[str] = Field(default_factory=list)
    document_name: str | None = None
    section_name: str | None = None
    blocks: list[ContentBlock] = Field(default_factory=list)
    text: str | None = None
    tables: list[TableData] = Field(default_factory=list)
    error: str | None = None
```

기존 `TableData`·`DisclosureMeta`·`DisclosureContent`는 유지한다.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_viewer_schema.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/schemas/viewer.py packages/web-api/tests/test_viewer_schema.py
git commit -m "feat(web-api): Viewer ContentBlock 스키마 추가"
```

---

### Task 2: `extract_blocks` 파서

**Files:**
- Create: `packages/web-api/app/parsing/blocks.py`
- Test: `packages/web-api/tests/test_blocks.py`

**Interfaces:**
- Consumes: Task 1의 `HeadingBlock`/`ParagraphBlock`/`TableBlock`/`ContentBlock`
- Produces:
  - `extract_blocks(html: str) -> list[ContentBlock]`
  - `blocks_to_text(blocks: list[ContentBlock]) -> str` — heading+paragraph만, 표 제외, `\n` 연결
  - `blocks_to_tables(blocks: list[ContentBlock]) -> list[TableData]`
  - 실패 시 `ParseError` (기존 `cleaner`와 동일)

- [ ] **Step 1: Write the failing test**

```python
"""문서 순서 블록 추출 테스트."""

from __future__ import annotations

from app.parsing.blocks import blocks_to_tables, blocks_to_text, extract_blocks

SAMPLE = """
<html><body>
  <script>bad()</script>
  <h2>재무상태표</h2>
  <p>자산총계는 다음과 같다.</p>
  <table>
    <tr><th>과목</th><th>당기</th></tr>
    <tr><td>자산총계</td><td>1,000</td></td></tr>
  </table>
  <p>주석을 참고한다.</p>
  <table></table>
</body></html>
"""


def test_extract_blocks_preserves_order_and_skips_table_text_in_paragraphs() -> None:
    blocks = extract_blocks(SAMPLE)

    assert [b.type for b in blocks] == [
        "heading",
        "paragraph",
        "table",
        "paragraph",
    ]
    assert blocks[0].text == "재무상태표"
    assert blocks[0].level == 2
    assert blocks[1].text == "자산총계는 다음과 같다."
    assert blocks[2].headers == ["과목", "당기"]
    assert blocks[2].rows == [["자산총계", "1,000"]]
    assert blocks[3].text == "주석을 참고한다."
    # 표 안 텍스트가 paragraph로 중복되지 않는다
    joined = " ".join(b.text for b in blocks if b.type == "paragraph")
    assert "1,000" not in joined


def test_blocks_to_text_excludes_tables() -> None:
    blocks = extract_blocks(SAMPLE)
    text = blocks_to_text(blocks)
    assert "재무상태표" in text
    assert "주석을 참고한다" in text
    assert "1,000" not in text
    assert "과목" not in text


def test_blocks_to_tables_matches_table_blocks() -> None:
    blocks = extract_blocks(SAMPLE)
    tables = blocks_to_tables(blocks)
    assert len(tables) == 1
    assert tables[0].headers == ["과목", "당기"]


def test_extract_blocks_removes_noise() -> None:
    blocks = extract_blocks(SAMPLE)
    dumped = " ".join(str(b) for b in blocks)
    assert "bad()" not in dumped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_blocks.py -v`  
Expected: FAIL (`app.parsing.blocks` 없음)

- [ ] **Step 3: Implement `app/parsing/blocks.py`**

핵심 로직 (한국어 Docstring 포함):

```python
"""DART 원문 HTML을 문서 순서 블록으로 변환한다."""

from __future__ import annotations

import re
from typing import Iterable

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from app.errors import ParseError
from app.schemas.viewer import (
    ContentBlock,
    HeadingBlock,
    ParagraphBlock,
    TableBlock,
    TableData,
)

_NOISE_TAGS = ("script", "style", "noscript", "iframe", "link", "meta")
_SPACES = re.compile(r"[ \t\u00a0\u3000]+")
_WS = re.compile(r"[\s\u00a0\u3000]+")


def extract_blocks(html: str) -> list[ContentBlock]:
    """noise를 제거하고 heading/paragraph/table 블록을 문서 순서로 반환한다."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:  # pragma: no cover
        raise ParseError(f"본문 HTML을 파싱하지 못했습니다: {exc}") from exc

    for tag in soup(list(_NOISE_TAGS)):
        tag.decompose()
    for comment in soup.find_all(string=lambda n: isinstance(n, Comment)):
        comment.extract()

    root = soup.body or soup
    blocks: list[ContentBlock] = []
    _walk(root, blocks)
    return blocks


def blocks_to_text(blocks: Iterable[ContentBlock]) -> str:
    """heading·paragraph만 이어 붙인다. 표 텍스트는 제외한다."""
    lines: list[str] = []
    for block in blocks:
        if block.type in ("heading", "paragraph") and block.text.strip():
            lines.append(block.text.strip())
    return "\n".join(lines)


def blocks_to_tables(blocks: Iterable[ContentBlock]) -> list[TableData]:
    """table 블록만 TableData 목록으로 변환한다."""
    return [
        TableData(headers=list(b.headers), rows=[list(r) for r in b.rows])
        for b in blocks
        if b.type == "table"
    ]


def _walk(node: Tag, blocks: list[ContentBlock]) -> None:
    for child in list(node.children):
        if isinstance(child, NavigableString):
            text = _norm_inline(str(child))
            if text:
                _append_paragraph(blocks, text)
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            text = _norm_inline(child.get_text(" "))
            if text:
                level = min(int(name[1]), 3)
                blocks.append(HeadingBlock(level=level, text=text))
            continue
        if name == "table":
            table = _parse_table(child)
            if table is not None:
                blocks.append(table)
            continue
        # 블록성 컨테이너는 재귀, 인라인 위주는 텍스트로
        if name in {"p", "div", "section", "article", "li", "td", "th", "span", "a"}:
            # table 안의 td/th는 table 파서에서만 처리되므로 여기 도달 시 표 밖
            if name in {"td", "th"}:
                text = _norm_inline(child.get_text(" "))
                if text:
                    _append_paragraph(blocks, text)
                continue
            if name in {"p"}:
                text = _norm_inline(child.get_text(" "))
                if text:
                    _append_paragraph(blocks, text)
                continue
            _walk(child, blocks)
            continue
        _walk(child, blocks)


def _append_paragraph(blocks: list[ContentBlock], text: str) -> None:
    if blocks and blocks[-1].type == "paragraph":
        blocks[-1] = ParagraphBlock(text=f"{blocks[-1].text} {text}".strip())
    else:
        blocks.append(ParagraphBlock(text=text))


def _parse_table(table: Tag) -> TableBlock | None:
    parsed_rows: list[list[str]] = []
    for row in table.find_all("tr"):
        cells = [_cell_text(c) for c in row.find_all(["th", "td"])]
        if cells:
            parsed_rows.append(cells)
    if not parsed_rows:
        return None
    first_row = table.find("tr")
    has_header = bool(first_row and first_row.find("th"))
    headers = parsed_rows[0] if has_header else []
    rows = parsed_rows[1:] if has_header else parsed_rows
    return TableBlock(headers=headers, rows=rows)


def _cell_text(cell: Tag) -> str:
    return _WS.sub(" ", cell.get_text(" ")).strip()


def _norm_inline(value: str) -> str:
    return _SPACES.sub(" ", value).strip()
```

**구현 주의:** `table` 노드에서는 자손을 `_walk`로 재귀하지 않는다(표 안 텍스트가 paragraph로 새지 않게). 빈 표는 `None` → drop. 네비성 링크만 있는 줄 drop은 보수적으로: 텍스트가 비면 skip 정도만.

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_blocks.py -v`  
Expected: PASS. 실패하면 walk 규칙(특히 `div` 재귀 vs `p` 텍스트)을 픽스처에 맞게 조정한다.

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/parsing/blocks.py packages/web-api/tests/test_blocks.py
git commit -m "feat(web-api): HTML 문서 순서 블록 파서 추가"
```

---

### Task 3: cleaner/tables 래퍼 + ViewerService 연동

**Files:**
- Modify: `packages/web-api/app/parsing/cleaner.py`
- Modify: `packages/web-api/app/parsing/tables.py`
- Modify: `packages/web-api/app/services/viewer_service.py`
- Modify: `packages/web-api/tests/test_cleaner.py`
- Modify: `packages/web-api/tests/test_viewer_api.py`
- Modify: `packages/web-api/tests/test_tables.py` (있으면)
- Test: `packages/web-api/tests/test_viewer_service.py` (없으면 서비스 단위 추가)

**Interfaces:**
- Consumes: `extract_blocks`, `blocks_to_text`, `blocks_to_tables`
- Produces: `SectionContent`에 `blocks` 채워짐. `text`는 표 제외. `tables` ≡ table blocks

- [ ] **Step 1: Write failing tests**

`test_cleaner.py`에 추가:

```python
TABLE_HTML = """
<html><body>
  <p>서문</p>
  <table><tr><th>A</th></tr><tr><td>1</td></tr></table>
</body></html>
"""


def test_extract_text_excludes_table_contents() -> None:
    text = extract_text(TABLE_HTML)
    assert "서문" in text
    assert "1" not in text
```

`test_viewer_api.py`의 `SECTION`에 `blocks`를 넣고, `test_get_section_returns_single_section`에서:

```python
assert response.json()["blocks"][0]["type"] == "heading"  # Fake에 맞게
```

서비스 통합(MockTransport 또는 fake HTML)이 이미 있으면 blocks 단언을 추가한다. 없으면:

```python
# tests/test_viewer_service.py
async def test_to_section_builds_blocks_without_duplicating_table_in_text(tmp_path):
    # Entry + DartHttp MockTransport로 위 TABLE_HTML 반환
    # get_section → blocks에 table, text에 "1" 없음
    ...
```

기존 `FakeViewerService`의 `SECTION`에 `blocks=[]` 또는 샘플 블록을 넣어 API 테스트가 깨지지 않게 한다.

- [ ] **Step 2: Run to verify fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cleaner.py::test_extract_text_excludes_table_contents -v`  
Expected: FAIL (`1`이 text에 포함)

- [ ] **Step 3: Implement wrappers + ViewerService**

`cleaner.py`:

```python
from app.parsing.blocks import blocks_to_text, extract_blocks

def extract_text(html: str) -> str:
    """blocks에서 표 제외 텍스트를 유도한다."""
    return blocks_to_text(extract_blocks(html))
```

`tables.py` — `extract_tables`가 blocks의 table을 dict로 반환하도록 바꾸되 **공개 시그니처는 `list[dict[str, list]]` 유지**:

```python
from app.parsing.blocks import blocks_to_tables, extract_blocks

def extract_tables(html: str) -> list[dict[str, list]]:
    return [t.model_dump() for t in blocks_to_tables(extract_blocks(html))]
```

`viewer_service.py`의 `_to_section`:

```python
from app.parsing.blocks import blocks_to_tables, blocks_to_text, extract_blocks

# html이 있을 때:
blocks = extract_blocks(html)
text = blocks_to_text(blocks)
tables = blocks_to_tables(blocks)
return SectionContent(..., blocks=list(blocks), text=text, tables=tables, error=error)
```

`extract_text`/`extract_tables`를 ViewerService에서 **직접 호출하지 않는다**(이중 파싱 방지).

- [ ] **Step 4: Run related tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cleaner.py tests/test_tables.py tests/test_blocks.py tests/test_viewer_api.py tests/test_viewer_service.py -v`  
Expected: PASS (`test_tables.py` 없으면 생략)

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/parsing/cleaner.py packages/web-api/app/parsing/tables.py \
  packages/web-api/app/services/viewer_service.py packages/web-api/tests/
git commit -m "feat(web-api): Viewer가 blocks 기반으로 text/tables 조립"
```

---

### Task 4: Browse 정적 파일 · base 템플릿 · 라우터 골격

**Files:**
- Create: `packages/web-api/app/api/browse/__init__.py` (빈 패키지 또는 `ui` re-export)
- Create: `packages/web-api/app/api/browse/ui.py`
- Create: `packages/web-api/app/static/browse.css`
- Create: `packages/web-api/app/templates/browse/base.html`
- Create: `packages/web-api/app/templates/browse/404.html`
- Modify: `packages/web-api/app/main.py`
- Test: `packages/web-api/tests/test_browse_ui.py`

**Interfaces:**
- Produces: `router = APIRouter(prefix="/browse", tags=["Browse UI"], include_in_schema=False)`
- `GET /browse` → 200 HTML (빈 목록이어도 페이지 렌더)
- Static: `/static/browse.css`
- Templates dir: Admin과 동일 `app/templates` (하위 `browse/`)

- [ ] **Step 1: Write failing test**

```python
"""Browse UI 테스트."""

from __future__ import annotations

from app.main import create_app


async def test_browse_list_page_renders(client_factory) -> None:
    async with client_factory(create_app()) as client:
        response = await client.get("/browse")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "공시" in response.text


async def test_browse_css_is_served(client_factory) -> None:
    async with client_factory(create_app()) as client:
        response = await client.get("/static/browse.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_browse_ui.py::test_browse_list_page_renders -v`  
Expected: FAIL (404)

- [ ] **Step 3: Implement skeleton**

`main.py`:

```python
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from app.api.browse import ui as browse_ui

STATIC_DIR = Path(__file__).resolve().parent / "static"

def create_app() -> FastAPI:
    ...
    app.include_router(browse_ui.router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
```

`ui.py` 최소:

```python
TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(prefix="/browse", tags=["Browse UI"], include_in_schema=False)

@router.get("", response_class=HTMLResponse)
async def browse_list(request: Request, ...) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "browse/list.html",
        {"items": [], "next_cursor": None, "filters": {}, "cursor_error": None},
    )
```

`base.html`: Pretendard + HTMX CDN (Admin과 유사하되 Browse 전용 클래스), `<link href="/static/browse.css">`.  
`list.html`: `{% extends "browse/base.html" %}` + 제목 "공시 탐색" + 빈 테이블 골격.  
`browse.css`: Admin 토큰 색을 참고한 최소 변수(`--text`, `--border`, `--accent`)와 `.browse-layout`, `.toc`, `.section-panel`.

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_browse_ui.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/api/browse packages/web-api/app/static \
  packages/web-api/app/templates/browse packages/web-api/app/main.py \
  packages/web-api/tests/test_browse_ui.py
git commit -m "feat(web-api): Browse UI 골격과 정적 파일 추가"
```

---

### Task 5: Browse 공시 목록 (필터 · cursor)

**Files:**
- Modify: `packages/web-api/app/api/browse/ui.py`
- Modify: `packages/web-api/app/templates/browse/list.html`
- Modify: `packages/web-api/tests/test_browse_ui.py`

**Interfaces:**
- Consumes: `get_catalog_query_service`, `CatalogQueryService.list_disclosures`, `BadRequest`, `report_type_options`/`report_type_label`, `get_settings_dep`
- Query params: `corp_code`, `corp_name`, `report_nm`, `report_type`, `start_date`, `end_date`, `limit`(기본 20), `cursor`
- `report_type_options(tuple(settings.heatmap_report_type_list))` — 시그니처가 `codes: tuple[str, ...]` 필수

- [ ] **Step 1: Write failing tests**

DB 시드 패턴은 `test_catalog_query_api.py` / conftest의 세션 픽스처를 따른다. disclosures 2건을 넣고:

```python
async def test_browse_list_shows_disclosure_rows(client_factory, seeded_app):
    async with client_factory(seeded_app) as client:
        r = await client.get("/browse")
    assert "테스트회사" in r.text
    assert "감사보고서" in r.text

async def test_browse_list_next_cursor_link(client_factory, seeded_app):
    async with client_factory(seeded_app) as client:
        r = await client.get("/browse", params={"limit": 1})
    assert "cursor=" in r.text or "다음" in r.text

async def test_browse_list_bad_cursor_shows_message(client_factory, seeded_app):
    async with client_factory(seeded_app) as client:
        r = await client.get("/browse", params={"cursor": "!!!"})
    assert r.status_code == 200
    assert "커서" in r.text
```

시드 헬퍼가 없으면 테스트 안에서 `Disclosure` upsert + `create_app` 의존성 오버라이드로 `CatalogQueryService` fake를 써도 된다 (Admin UI 테스트의 fake 패턴).

- [ ] **Step 2: Run to verify fail**

Expected: FAIL (목록에 회사명 없음)

- [ ] **Step 3: Implement list handler + template**

`ui.py`:

```python
@router.get("", response_class=HTMLResponse)
async def browse_list(
    request: Request,
    corp_code: str | None = None,
    corp_name: str | None = None,
    report_nm: str | None = None,
    report_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
    catalog: CatalogQueryService = Depends(get_catalog_query_service),
) -> HTMLResponse:
    cursor_error: str | None = None
    items = []
    next_cursor = None
    try:
        result = await catalog.list_disclosures(
            corp_code=corp_code or None,
            corp_name=corp_name or None,
            report_nm=report_nm or None,
            report_type=report_type or None,
            start_date=start_date or None,
            end_date=end_date or None,
            limit=min(max(limit, 1), 100),
            cursor=cursor,
        )
        items = result.items
        next_cursor = result.next_cursor
    except BadRequest as exc:
        cursor_error = str(exc)
        # 손상 cursor → 첫 페이지
        result = await catalog.list_disclosures(
            corp_code=corp_code or None,
            corp_name=corp_name or None,
            report_nm=report_nm or None,
            report_type=report_type or None,
            start_date=start_date or None,
            end_date=end_date or None,
            limit=min(max(limit, 1), 100),
            cursor=None,
        )
        items = result.items
        next_cursor = result.next_cursor

    return templates.TemplateResponse(
        request,
        "browse/list.html",
        {
            "items": items,
            "next_cursor": next_cursor,
            "cursor_error": cursor_error,
            "filters": {
                "corp_code": corp_code or "",
                "corp_name": corp_name or "",
                "report_nm": report_nm or "",
                "report_type": report_type or "",
                "start_date": start_date or "",
                "end_date": end_date or "",
                "limit": limit,
            },
            "report_type_options": report_type_options(
                tuple(settings.heatmap_report_type_list)
            ),
            "report_type_label": report_type_label,
        },
    )
```

핸들러에 `settings: Settings = Depends(get_settings_dep)`를 추가한다.

`list.html`: GET 폼(필터), 테이블 행 → `/browse/{{ item.rcp_no }}`, DART `disclosure_url` 외부 링크, `next_cursor`가 있으면 동일 필터 + `cursor`로 "다음" 링크.

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_browse_ui.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/api/browse/ui.py packages/web-api/app/templates/browse/list.html \
  packages/web-api/tests/test_browse_ui.py
git commit -m "feat(web-api): Browse 공시 목록 필터와 cursor"
```

---

### Task 6: Browse 공시 상세 2열 (목차)

**Files:**
- Create: `packages/web-api/app/templates/browse/disclosure.html`
- Create: `packages/web-api/app/templates/browse/partials/toc.html`
- Create: `packages/web-api/app/templates/browse/partials/section_placeholder.html`
- Modify: `packages/web-api/app/api/browse/ui.py`
- Modify: `packages/web-api/app/static/browse.css`
- Modify: `packages/web-api/tests/test_browse_ui.py`

**Interfaces:**
- `GET /browse/{rcp_no}` → 2열 HTML
- Consumes:
  - `CatalogQueryService.get_disclosure(rcp_no: str) -> DisclosureSummary`
  - `CatalogQueryService.list_entries(rcp_no: str) -> DisclosureEntriesResponse`
- primary 비면 `show_all=True`로 all_entries 표시
- 첫 primary가 있으면 오른쪽 패널을 그 섹션 URL로 HTMX 자동 로드 (`hx-get` + `hx-trigger="load"`)

- [ ] **Step 1: Write failing tests**

```python
async def test_browse_disclosure_shows_primary_toc(client_factory, seeded_with_entries):
    r = await client.get("/browse/20260724000650")
    assert r.status_code == 200
    assert "재무상태표" in r.text  # primary
    assert "browse-layout" in r.text or "toc" in r.text

async def test_browse_disclosure_404(client_factory, seeded_app):
    r = await client.get("/browse/99999999999999")
    assert r.status_code == 404
    assert "없" in r.text
```

- [ ] **Step 2: Implement**

```python
@router.get("/{rcp_no}", response_class=HTMLResponse)
async def browse_disclosure(
    request: Request,
    rcp_no: str,
    catalog: CatalogQueryService = Depends(get_catalog_query_service),
) -> HTMLResponse:
    try:
        summary = await catalog.get_disclosure(rcp_no)
        toc = await catalog.list_entries(rcp_no)
    except CatalogNotFound:
        return templates.TemplateResponse(
            request,
            "browse/404.html",
            {"message": f"접수번호 {rcp_no} 공시를 찾을 수 없습니다."},
            status_code=404,
        )

    use_all = len(toc.primary_entries) == 0
    entries = toc.all_entries if use_all else toc.primary_entries
    first_id = entries[0].entry_id if entries else None

    return templates.TemplateResponse(
        request,
        "browse/disclosure.html",
        {
            "rcp_no": rcp_no,
            "summary": summary,
            "toc": toc,
            "show_all": use_all,
            "first_entry_id": first_id,
        },
    )
```

템플릿: CSS grid 2열. 왼쪽 `partials/toc.html` — primary/all 토글은 클라이언트 쪽이면 `details`/버튼으로 `all_entries`를 숨김 해제(이미 HTML에 둘 다 렌더). 항목:

```html
<a hx-get="/browse/{{ rcp_no }}/sections/{{ entry.entry_id }}"
   hx-target="#section-panel"
   hx-swap="innerHTML"
   hx-indicator="#section-loading"
   hx-push-url="true">
  {{ entry.section_name or entry.document_name }}
</a>
```

오른쪽 `#section-panel`: `first_entry_id`가 있으면

```html
<div id="section-panel"
     hx-get="/browse/{{ rcp_no }}/sections/{{ first_entry_id }}"
     hx-trigger="load"
     hx-swap="innerHTML"
     hx-indicator="#section-loading">
  <p>목차에서 섹션을 선택하세요.</p>
</div>
```

없으면 안내만.

- [ ] **Step 3: Run tests**

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add packages/web-api/app/api/browse/ui.py packages/web-api/app/templates/browse \
  packages/web-api/app/static/browse.css packages/web-api/tests/test_browse_ui.py
git commit -m "feat(web-api): Browse 공시 목차 2열 레이아웃"
```

---

### Task 7: Browse 섹션 본문 partial · 오류 패널

**Files:**
- Create: `packages/web-api/app/templates/browse/partials/section.html`
- Create: `packages/web-api/app/templates/browse/partials/section_error.html`
- Modify: `packages/web-api/app/api/browse/ui.py`
- Modify: `packages/web-api/tests/test_browse_ui.py`

**Interfaces:**
- `GET /browse/{rcp_no}/sections/{entry_id}`
  - `HX-Request: true` → partial HTML (`section.html` 또는 `section_error.html`)
  - 아니면 → `disclosure.html` 전체 + 해당 섹션을 패널에 포함(또는 리다이렉트 후 load). **최소 구현:** non-HTMX도 partial을 단독 페이지로 `base` 확장해 보여 주거나, disclosure 셸 + 서버 사이드 렌더된 패널.
- Consumes: `ViewerService.get_section`, `EntryRepository.get_by_entry_id`(viewer_url용), `CatalogNotFound`→404, `SourceFetchError`/`ParseError`→오류 카드(200 partial, API와 달리 Browse는 패널 내 처리)

스펙: 단일 섹션 API는 502이지만 **Browse UI는 패널 오류 카드**. 따라서 Browse 핸들러에서 예외를 catch한다.

- [ ] **Step 1: Write failing tests**

```python
async def test_browse_section_partial_renders_blocks(client_factory, app_with_fake_viewer):
    r = await client.get(
        "/browse/20260724000650/sections/e_1",
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "재무상태표" in r.text  # heading/text

async def test_browse_section_error_panel(client_factory, app_with_failing_viewer):
    r = await client.get(
        "/browse/20260724000650/sections/e_1",
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "다시" in r.text or "실패" in r.text

async def test_browse_section_not_found(client_factory, seeded_app):
    r = await client.get("/browse/20260724000650/sections/missing")
    assert r.status_code == 404
```

Fake viewer는 `get_viewer_service` dependency_overrides. 성공 fake의 `SectionContent`에 heading/paragraph/table blocks 포함.

- [ ] **Step 2: Run to verify fail**

Expected: FAIL (라우트 없음)

- [ ] **Step 3: Implement section route**

```python
def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


@router.get("/{rcp_no}/sections/{entry_id}", response_class=HTMLResponse)
async def browse_section(
    request: Request,
    rcp_no: str,
    entry_id: str,
    viewer: ViewerService = Depends(get_viewer_service),
    entries: EntryRepository = Depends(get_entry_repository),
    catalog: CatalogQueryService = Depends(get_catalog_query_service),
) -> HTMLResponse:
    entry = await entries.get_by_entry_id(entry_id)
    viewer_url = entry.viewer_url if entry and entry.rcept_no == rcp_no else None

    try:
        section = await viewer.get_section(rcp_no, entry_id)
    except CatalogNotFound as exc:
        return templates.TemplateResponse(
            request, "browse/404.html",
            {"message": str(exc)},
            status_code=404,
        )
    except (SourceFetchError, ParseError) as exc:
        ctx = {
            "rcp_no": rcp_no,
            "entry_id": entry_id,
            "error": str(exc),
            "viewer_url": viewer_url,
        }
        template = "browse/partials/section_error.html"
        if not _is_htmx(request):
            # 전체 페이지: disclosure 셸 + 오류 패널 — 목차 로드 후 오류 partial 포함
            return await _disclosure_with_panel(request, rcp_no, catalog, panel_template=template, panel_ctx=ctx)
        return templates.TemplateResponse(request, template, ctx)

    ctx = {"rcp_no": rcp_no, "section": section, "viewer_url": viewer_url}
    if _is_htmx(request):
        return templates.TemplateResponse(request, "browse/partials/section.html", ctx)
    return await _disclosure_with_panel(...)
```

`section.html`: path 브레드크럼, 제목, DART 링크, `{% for block in section.blocks %}` 분기 렌더, `#section-loading`용 스피너는 base/disclosure에 둔다.  
`section_error.html`: 메시지, `hx-get` 같은 URL로 "다시 시도", `viewer_url` 외부 링크.

`_disclosure_with_panel`은 Task 6 핸들러와 중복을 피하도록 내부 헬퍼로 추출해도 된다.

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_browse_ui.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/api/browse/ui.py packages/web-api/app/templates/browse \
  packages/web-api/tests/test_browse_ui.py
git commit -m "feat(web-api): Browse 섹션 본문 partial과 오류 패널"
```

---

### Task 8: 문서화 · 스펙 상태 · 회귀

**Files:**
- Modify: `packages/web-api/README.md`
- Modify: `README.md` (루트 — Browse URL 한 줄)
- Modify: `docs/superpowers/specs/2026-07-26-browse-viewer-blocks-design.md` (상태 → 승인)

- [ ] **Step 1: README에 Browse·blocks 반영**

web-api README 엔드포인트 표에:

| GET | `/browse` | Public 공시 탐색 UI |
| GET | `/browse/{rcp_no}` | 목차 \| 본문 2열 |
| GET | `/browse/{rcp_no}/sections/{entry_id}` | 섹션 본문 (HTMX partial) |

Viewer 설명에 `blocks` 필드와 `text`가 표를 제외함을 한 문단 추가.

루트 README "주요 Public 경로" 또는 실행 절에 `http://127.0.0.1:8000/browse` 추가.

- [ ] **Step 2: 전체 테스트**

Run: `.venv\Scripts\python.exe -m pytest -v`  
Expected: PASS (전부)

- [ ] **Step 3: 스펙 상태를 `승인`으로 변경**

- [ ] **Step 4: Commit**

```bash
git add packages/web-api/README.md README.md \
  docs/superpowers/specs/2026-07-26-browse-viewer-blocks-design.md
git commit -m "docs: Browse UI와 Viewer blocks 사용법 반영"
```

---

## Self-Review (plan vs spec)

| Spec 요구 | Task |
|-----------|------|
| `blocks[]` heading/paragraph/table | 1–2 |
| `text` 표 제외, `tables` 하위호환 | 3 |
| ViewerService 단일 파싱 | 3 |
| `/browse` 목록·필터·cursor | 4–5 |
| 목차\|본문 2열, primary/전체, 첫 primary 자동 로드 | 6 |
| HTMX partial, 오류 카드, 404 | 7 |
| Admin 템플릿 분리, static/browse.css | 4 |
| 전 leaf UI 없음, 캐시 없음 | 범위 밖 유지 |
| 테스트·README | 2,3,5–8 |

**Placeholder scan:** Task 6은 `get_disclosure` / `list_entries`로 고정. Task 2 `_parse_table` 단일 루프. Task 5 `report_type_options(tuple(...))` 시그니처 반영.

**Type consistency:** `ContentBlock` / `HeadingBlock` / `ParagraphBlock` / `TableBlock` / `TableData` / `SectionContent.blocks` 명칭을 Task 1→7까지 동일하게 사용.
