# Browse Viewer 계층 목차 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공시 leaf에 `ordinal`을 부여하고, Browse 목차를 원문 순서·path 기반 다단계 헤더·들여쓰기로 표시하며, 주요 섹션은 상단 바로가기로 분리한다.

**Architecture:** `entry-extractor`의 `buildEntries`가 공시 내 등장 순번 `ordinal`을 붙인다. web-api는 `entries.ordinal`에 저장하고 `ORDER BY ordinal`로 목차를 조회한다. Browse는 `build_toc_items`로 leaf의 `path` 접두사에서 헤더를 재구성해 렌더한다. Catalog JSON의 flat `primary_entries`/`all_entries`는 유지하고 `ordinal` 필드만 추가한다.

**Tech Stack:** Node.js (entry-extractor), Python 3.11+, FastAPI, SQLAlchemy, Jinja2, HTMX, pytest, `node --test`

**Spec:** `docs/superpowers/specs/2026-07-26-browse-toc-hierarchy-design.md`

## Global Constraints

- 주석·Docstring·로그·사용자 메시지는 **한국어**
- DB는 leaf-only 유지. 중간 노드를 entry로 저장하지 않음
- Catalog JSON nested tree 변경 금지. `ordinal` 필드만 추가
- “전체 보기” `<details>` 제거. 전체 계층 목차가 기본
- SQLite/PostgreSQL 공통: `NULLS LAST` 대신  
  `CASE WHEN ordinal IS NULL THEN 1 ELSE 0 END, ordinal, entry_id`
- 작업 디렉터리: 모노레포 루트. Node 테스트는  
  `npm test -w @dart-wrapper/entry-extractor`, Python은  
  `packages/web-api`에서 pytest
- `EntryRecord`는 Node camelCase를 alias로 받음 (`dcmNo` 등). `ordinal`은 동일 이름

## File Structure

| Path | Responsibility |
|------|----------------|
| `packages/entry-extractor/src/entries.js` | `buildEntries`에서 `ordinal` 부여 |
| `packages/entry-extractor/tests/test_build_entries_ordinal.js` | ordinal 연속성 테스트 |
| `packages/web-api/app/models/entry.py` | `ordinal` 컬럼 |
| `packages/web-api/app/schemas/entry.py` | `EntryRecord.ordinal` |
| `packages/web-api/app/schemas/catalog_query.py` | `EntrySummary.ordinal` |
| `packages/web-api/app/db/session.py` | `ensure_schema`에 ordinal ALTER |
| `packages/web-api/app/repositories/entry_repository.py` | toc 정렬을 ordinal 기준 |
| `packages/web-api/app/services/toc_items.py` | `build_toc_items` (신규) |
| `packages/web-api/app/api/browse/ui.py` | toc_items 전달, first_entry 선택 |
| `packages/web-api/app/templates/browse/partials/toc.html` | 바로가기 + 계층 목차 |
| `packages/web-api/app/static/browse.css` | 헤더·indent 스타일 |
| `packages/web-api/tests/test_toc_items.py` | 헤더 재구성 단위 테스트 |
| `packages/web-api/tests/test_browse_ui.py` | Browse 목차 UI |
| `packages/web-api/tests/test_entry_repository_toc.py` | ordinal 정렬 (신규 또는 기존에 추가) |
| `packages/entry-extractor/README.md` / `packages/web-api/README.md` | 문서 |

---

### Task 1: entry-extractor — `ordinal` 부여

**Files:**
- Modify: `packages/entry-extractor/src/entries.js`
- Test: `packages/entry-extractor/tests/test_build_entries_ordinal.js`

**Interfaces:**
- Consumes: 기존 `buildEntries(disclosure, detail, { leafOnly, includeAttachments, attachmentTrees })`
- Produces: 각 entry에 `ordinal: number` (공시 내 0부터 증가, 본문 leaf → 첨부 leaf/fallback 연속)

- [ ] **Step 1: Write the failing test**

`packages/entry-extractor/tests/test_build_entries_ordinal.js`:

```js
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { extractTree } = require('../src/documents');
const { buildEntries } = require('../src/entries');
const { treeDataHtml, sampleDisclosure } = require('./fixtures/html');

function leafTree(dcmNo, eleId, text) {
  return extractTree(
    treeDataHtml({
      rcpNo: sampleDisclosure.rcept_no,
      dcmNo,
      nodes: [{ depth: 1, text, eleId, offset: '10', length: '20' }],
    })
  );
}

describe('buildEntries ordinal', () => {
  it('본문 leaf 후 첨부 leaf에 0부터 연속 ordinal', () => {
    const bodyTree = leafTree('111', '1', '감사의견');
    const attTree = leafTree('999', '5', '재무상태표');
    const detail = {
      tree: bodyTree,
      documents: [
        { source: 'body', dcmNo: '111', name: '감사보고서', url: 'u1' },
        {
          source: 'attachment',
          dcmNo: '999',
          name: '첨부재무제표',
          originalName: '첨부재무제표',
          url: 'u999',
        },
      ],
    };

    const entries = buildEntries(sampleDisclosure, detail, {
      attachmentTrees: { 999: attTree },
    });

    assert.deepEqual(
      entries.map((e) => e.ordinal),
      [0, 1]
    );
    assert.equal(entries[0].source, 'body');
    assert.equal(entries[1].source, 'attachment');
  });

  it('첨부 fallback도 ordinal을 받는다', () => {
    const detail = {
      tree: leafTree('111', '1', '본문'),
      documents: [
        { source: 'body', dcmNo: '111', name: '본문', url: 'u1' },
        {
          source: 'attachment',
          dcmNo: '999',
          name: 'PDF',
          originalName: 'PDF',
          url: 'u9',
        },
      ],
    };
    const entries = buildEntries(sampleDisclosure, detail, {
      attachmentTrees: { 999: [] },
    });
    assert.deepEqual(
      entries.map((e) => e.ordinal),
      [0, 1]
    );
    assert.ok(entries[1].entry_id.endsWith('_att'));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -w @dart-wrapper/entry-extractor`  
Expected: FAIL — `ordinal` undefined / assert 실패

- [ ] **Step 3: Implement ordinal in `buildEntries`**

`packages/entry-extractor/src/entries.js`에서 `buildEntries` 시작부에 `let ordinal = 0`을 두고, body/attachment로 `entries.push`하기 직전에:

```js
entry.ordinal = ordinal++;
```

본문 `walk`와 첨부 `walkAtt`·fallback 모두 동일. body에 있어 skip되는 첨부 문서는 push하지 않으므로 ordinal도 증가하지 않음.

- [ ] **Step 4: Run tests — PASS**

Run: `npm test -w @dart-wrapper/entry-extractor`  
Expected: 기존 테스트 + ordinal 테스트 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/entry-extractor/src/entries.js packages/entry-extractor/tests/test_build_entries_ordinal.js
git commit -m "feat(entry-extractor): leaf entry에 공시 내 ordinal 부여"
```

---

### Task 2: web-api — `ordinal` 스키마·컬럼·저장

**Files:**
- Modify: `packages/web-api/app/models/entry.py`
- Modify: `packages/web-api/app/schemas/entry.py`
- Modify: `packages/web-api/app/schemas/catalog_query.py`
- Modify: `packages/web-api/app/db/session.py`
- Test: `packages/web-api/tests/test_entry_ordinal_schema.py` (신규)

**Interfaces:**
- Consumes: Node가 보내는 `ordinal` (동일 키)
- Produces:
  - `Entry.ordinal: Mapped[int | None]`
  - `EntryRecord.ordinal: int | None = None`
  - `EntrySummary.ordinal: int | None = None` (+ `from_model` 반영)
  - `_COLUMN_PATCHES`에 `("entries", "ordinal", "INTEGER", "INTEGER")`

- [ ] **Step 1: Write the failing test**

```python
"""Entry ordinal 스키마 테스트."""

from __future__ import annotations

from app.schemas.catalog_query import EntrySummary
from app.schemas.entry import EntryRecord


def test_entry_record_accepts_ordinal() -> None:
    record = EntryRecord.model_validate(
        {
            "entry_id": "20260724000650_1_1",
            "rcept_no": "20260724000650",
            "source": "body",
            "ordinal": 3,
            "path": ["감사보고서"],
        }
    )
    assert record.ordinal == 3


def test_entry_summary_includes_ordinal() -> None:
    class _Row:
        entry_id = "e1"
        source = "body"
        dcm_no = "1"
        ele_id = "1"
        document_name = "감사보고서"
        section_name = "재무상태표"
        path = ["감사보고서", "재무상태표"]
        depth = 2
        ordinal = 7

    summary = EntrySummary.from_model(_Row())
    assert summary.ordinal == 7
```

- [ ] **Step 2: Run — Expected FAIL** (`ordinal` 필드 없음 또는 from_model 누락)

Run (from `packages/web-api`):

```bash
.venv\Scripts\python.exe -m pytest tests/test_entry_ordinal_schema.py -v
```

- [ ] **Step 3: Implement**

`entry.py` (model) — `depth` 근처에:

```python
ordinal: Mapped[int | None] = mapped_column(Integer)
```

`schemas/entry.py`:

```python
ordinal: int | None = None
```

`schemas/catalog_query.py` — `EntrySummary`에 `ordinal: int | None = None`, `from_model`에 `ordinal=row.ordinal`.

`db/session.py` `_COLUMN_PATCHES`에 추가:

```python
(
    "entries",
    "ordinal",
    "INTEGER",
    "INTEGER",
),
```

- [ ] **Step 4: Run test — PASS**

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/models/entry.py packages/web-api/app/schemas/entry.py packages/web-api/app/schemas/catalog_query.py packages/web-api/app/db/session.py packages/web-api/tests/test_entry_ordinal_schema.py
git commit -m "feat(web-api): entries.ordinal 스키마와 컬럼 보강"
```

---

### Task 3: `list_toc_by_rcept_no` ordinal 정렬

**Files:**
- Modify: `packages/web-api/app/repositories/entry_repository.py`
- Test: `packages/web-api/tests/test_entry_repository_toc.py` (신규)

**Interfaces:**
- Consumes: `Entry.ordinal`
- Produces: `list_toc_by_rcept_no`가  
  `CASE WHEN ordinal IS NULL THEN 1 ELSE 0 END, ordinal, entry_id` 순

- [ ] **Step 1: Write the failing test**

기존 프로젝트의 async DB fixture 패턴을 따른다. `tests/conftest.py` 또는 `test_catalog_*`의 세션 fixture를 재사용. 대표 형태:

```python
"""목차 조회 ordinal 정렬 테스트."""

from __future__ import annotations

import pytest

from app.models.entry import Entry
from app.repositories.entry_repository import EntryRepository


@pytest.mark.asyncio
async def test_list_toc_orders_by_ordinal(db_session) -> None:
    """db_session: 프로젝트 기존 async session fixture 이름에 맞출 것."""
    rows = [
        Entry(
            entry_id="a",
            rcept_no="rcp1",
            source="body",
            path=["B"],
            ordinal=2,
            is_leaf=True,
        ),
        Entry(
            entry_id="b",
            rcept_no="rcp1",
            source="attachment",
            path=["A"],
            ordinal=0,
            is_leaf=True,
        ),
        Entry(
            entry_id="c",
            rcept_no="rcp1",
            source="body",
            path=["C"],
            ordinal=1,
            is_leaf=True,
        ),
    ]
    for row in rows:
        db_session.add(row)
    await db_session.commit()

    repo = EntryRepository(db_session)
    result = await repo.list_toc_by_rcept_no("rcp1")
    assert [e.entry_id for e in result] == ["b", "c", "a"]
```

`db_session` fixture 이름이 다르면 기존 테스트 파일(`tests/test_catalog_service.py` 등)을 보고 동일하게 맞춘다. 없으면 이 태스크에서 최소 in-memory SQLite fixture를 같은 파일에 둔다.

- [ ] **Step 2: Run — Expected FAIL** (여전히 source/dcm_no/ele_id 정렬)

- [ ] **Step 3: Implement**

```python
from sqlalchemy import case, select

async def list_toc_by_rcept_no(self, rcept_no: str) -> list[Entry]:
    """목차용 leaf 목록을 ordinal 순으로 반환한다."""
    statement = (
        select(Entry)
        .where(Entry.rcept_no == rcept_no)
        .order_by(
            case((Entry.ordinal.is_(None), 1), else_=0),
            Entry.ordinal,
            Entry.entry_id,
        )
    )
    result = await self._session.execute(statement)
    return list(result.scalars().all())
```

기존 `case((Entry.source == "body", 0), ...)` 정렬은 제거한다.

- [ ] **Step 4: Run — PASS**

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/repositories/entry_repository.py packages/web-api/tests/test_entry_repository_toc.py
git commit -m "feat(web-api): 목차 조회를 ordinal 순으로 정렬"
```

---

### Task 4: `build_toc_items` — path 기반 헤더 재구성

**Files:**
- Create: `packages/web-api/app/services/toc_items.py`
- Test: `packages/web-api/tests/test_toc_items.py`

**Interfaces:**
- Consumes: `Sequence` of objects with `path`, `section_name`, `document_name`, `entry_id`, `depth` (EntrySummary와 호환)
- Produces:
  - `TocItem` dataclass / TypedDict:  
    `kind: Literal["header","link"]`, `label: str`, `indent: int`, `entry: EntrySummary | None`
  - `build_toc_items(entries) -> list[TocItem]`

- [ ] **Step 1: Write the failing test**

```python
"""path 접두사 기반 목차 항목 재구성 테스트."""

from __future__ import annotations

from app.schemas.catalog_query import EntrySummary
from app.services.toc_items import build_toc_items


def _e(entry_id: str, path: list[str], section: str) -> EntrySummary:
    return EntrySummary(
        entry_id=entry_id,
        source="body",
        section_name=section,
        path=path,
        depth=len(path),
        ordinal=0,
    )


def test_build_toc_items_inserts_ancestor_headers() -> None:
    entries = [
        _e("1", ["감사보고서", "재무상태표"], "재무상태표"),
        _e("2", ["감사보고서", "(첨부)재무제표", "손익계산서"], "손익계산서"),
        _e("3", ["감사보고서", "(첨부)재무제표", "자본변동표"], "자본변동표"),
    ]
    items = build_toc_items(entries)
    kinds_labels = [(i.kind, i.label, i.indent) for i in items]
    assert kinds_labels == [
        ("header", "감사보고서", 0),
        ("link", "재무상태표", 1),
        ("header", "(첨부)재무제표", 1),
        ("link", "손익계산서", 2),
        ("link", "자본변동표", 2),
    ]


def test_build_toc_items_empty_path() -> None:
    entries = [_e("1", [], "단독")]
    items = build_toc_items(entries)
    assert len(items) == 1
    assert items[0].kind == "link"
    assert items[0].indent == 0


def test_build_toc_items_single_segment_path() -> None:
    entries = [_e("1", ["PDF첨부"], "PDF첨부")]
    items = build_toc_items(entries)
    assert [(i.kind, i.label) for i in items] == [("link", "PDF첨부")]
```

- [ ] **Step 2: Run — Expected FAIL** (모듈 없음)

```bash
.venv\Scripts\python.exe -m pytest tests/test_toc_items.py -v
```

- [ ] **Step 3: Implement**

`packages/web-api/app/services/toc_items.py`:

```python
"""leaf path로 Browse 목차용 헤더·링크 항목을 만든다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, Sequence


class TocEntryLike(Protocol):
    entry_id: str
    path: list[str]
    section_name: str | None
    document_name: str | None
    depth: int | None


@dataclass(frozen=True)
class TocItem:
    kind: Literal["header", "link"]
    label: str
    indent: int
    entry: TocEntryLike | None = None


def _ancestors(path: list[str]) -> list[str]:
    if len(path) <= 1:
        return []
    return list(path[:-1])


def _common_prefix_len(a: list[str], b: list[str]) -> int:
    n = 0
    for left, right in zip(a, b):
        if left != right:
            break
        n += 1
    return n


def _link_label(entry: TocEntryLike) -> str:
    return entry.section_name or entry.document_name or entry.entry_id


def _link_indent(entry: TocEntryLike) -> int:
    path = list(entry.path or [])
    if path:
        return max(0, len(path) - 1)
    if entry.depth is not None and entry.depth > 0:
        return max(0, entry.depth - 1)
    return 0


def build_toc_items(entries: Sequence[TocEntryLike]) -> list[TocItem]:
    """ordinal 순 leaf 목록을 헤더+링크 평탄 리스트로 변환한다."""
    items: list[TocItem] = []
    prev_ancestors: list[str] = []

    for entry in entries:
        path = list(entry.path or [])
        ancestors = _ancestors(path)
        k = _common_prefix_len(prev_ancestors, ancestors)
        for index, name in enumerate(ancestors[k:], start=k):
            items.append(TocItem(kind="header", label=name, indent=index))
        items.append(
            TocItem(
                kind="link",
                label=_link_label(entry),
                indent=_link_indent(entry),
                entry=entry,
            )
        )
        prev_ancestors = ancestors

    return items
```

- [ ] **Step 4: Run — PASS**

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/services/toc_items.py packages/web-api/tests/test_toc_items.py
git commit -m "feat(web-api): path 접두사로 목차 헤더·링크 재구성"
```

---

### Task 5: Browse UI — 바로가기 + 계층 목차

**Files:**
- Modify: `packages/web-api/app/api/browse/ui.py`
- Modify: `packages/web-api/app/templates/browse/partials/toc.html`
- Modify: `packages/web-api/app/static/browse.css`
- Modify: `packages/web-api/tests/test_browse_ui.py`

**Interfaces:**
- Consumes: `build_toc_items`, `DisclosureEntriesResponse`
- Produces: 템플릿 컨텍스트 `toc_items`, `primary_entries`(바로가기). `show_all` / details 제거
- `first_entry_id`: primary가 있으면 그 첫 항목, 없으면 `all_entries` 첫 항목 (기존 자동 로드 유지)

- [ ] **Step 1: Update failing Browse expectations**

`test_browse_ui.py`에서:

- `"전체 보기"` / `toc-all` / `toc-toggle`가 있으면 assert를 제거하고  
  `"바로가기"` 또는 `toc-shortcut` / `toc-tree` 클래스 존재를 assert
- primary가 있는 케이스: `"바로가기"` in response.text, `"재무상태표"` in response.text
- EmptyPrimary: details open 가정이 있으면 제거하고 계층 목차에 `"첨부문서"`만 확인

예시 추가:

```python
async def test_browse_disclosure_shows_shortcut_and_tree(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/browse/20260724000650")
    assert response.status_code == 200
    assert "바로가기" in response.text
    assert "toc-tree" in response.text
    assert "전체 보기" not in response.text
```

Fake catalog의 `path`를 다단계로 넣어 헤더가 나오는지 확인해도 된다:

```python
path=["감사보고서", "재무상태표"]
```

→ HTML에 헤더 텍스트 `감사보고서`와 indent 스타일/class가 보이면 충분.

- [ ] **Step 2: Run Browse tests — Expected FAIL**

```bash
.venv\Scripts\python.exe -m pytest tests/test_browse_ui.py -v
```

- [ ] **Step 3: Wire `ui.py`**

공시 상세 핸들러에서:

```python
from app.services.toc_items import build_toc_items

toc = await catalog.list_entries(rcp_no)
toc_items = build_toc_items(toc.all_entries)
if toc.primary_entries:
    first_entry_id = toc.primary_entries[0].entry_id
else:
    first_entry_id = toc.all_entries[0].entry_id if toc.all_entries else None

# template context:
# "toc": toc,
# "toc_items": toc_items,
# "first_entry_id": first_entry_id,
# show_all 제거
```

- [ ] **Step 4: Rewrite `toc.html`**

```html
<nav class="toc">
  <h2>목차</h2>

  {% macro toc_link(entry) %}
  <a hx-get="/browse/{{ rcp_no }}/sections/{{ entry.entry_id }}"
     hx-target="#section-panel"
     hx-swap="innerHTML"
     hx-indicator="#section-loading"
     hx-push-url="true">
    {{ entry.section_name or entry.document_name or entry.entry_id }}
  </a>
  {% endmacro %}

  {% if toc.primary_entries %}
  <section class="toc-shortcut">
    <h3>바로가기</h3>
    <ul>
      {% for entry in toc.primary_entries %}
      <li>{{ toc_link(entry) }}</li>
      {% endfor %}
    </ul>
  </section>
  {% endif %}

  {% if toc_items %}
  <ul class="toc-tree">
    {% for item in toc_items %}
      {% if item.kind == "header" %}
      <li class="toc-header" style="--toc-indent: {{ item.indent }}">{{ item.label }}</li>
      {% else %}
      <li class="toc-link" style="--toc-indent: {{ item.indent }}">{{ toc_link(item.entry) }}</li>
      {% endif %}
    {% endfor %}
  </ul>
  {% elif not toc.primary_entries %}
  <p>표시할 목차가 없습니다.</p>
  {% endif %}
</nav>
```

`disclosure.html`에서 빈 목차 메시지를 toc partial에 맡기도록 중복이 있으면 정리.

- [ ] **Step 5: CSS**

`browse.css`에:

```css
.toc-shortcut h3,
.toc-tree .toc-header {
  font-size: 0.82rem;
  color: var(--text-muted);
  font-weight: 600;
  margin: 10px 0 4px;
}
.toc-tree { list-style: none; margin: 0; padding: 0; }
.toc-tree .toc-header,
.toc-tree .toc-link {
  padding-left: calc(var(--toc-indent, 0) * 12px);
}
.toc-tree .toc-header {
  pointer-events: none;
  margin: 6px 0 2px;
}
```

- [ ] **Step 6: Run Browse tests — PASS**

- [ ] **Step 7: Commit**

```bash
git add packages/web-api/app/api/browse/ui.py packages/web-api/app/templates/browse/partials/toc.html packages/web-api/app/static/browse.css packages/web-api/tests/test_browse_ui.py
git commit -m "feat(web-api): Browse 목차를 바로가기+계층 트리로 표시"
```

---

### Task 6: README 갱신

**Files:**
- Modify: `packages/entry-extractor/README.md`
- Modify: `packages/web-api/README.md`

- [ ] **Step 1: entry-extractor README**

엔트리 스키마 예시에 `ordinal: 0` 한 줄 추가. “3단계” 또는 첨부 leaf 절 근처에:

```markdown
각 leaf에는 공시 내 등장 순번 `ordinal`(0부터)이 붙습니다. Browse/카탈로그 목차 정렬에 사용합니다.
```

- [ ] **Step 2: web-api README**

목차 설명에서 “전체 보기” 토글 문구를 다음으로 교체:

```markdown
Browse 목차는 `ordinal` 순의 전체 계층(path 기반 그룹 헤더)을 기본으로 보여 주고,
`primary_entries`(report_type allowlist)는 상단 “바로가기”로 분리합니다.
```

- [ ] **Step 3: Commit**

```bash
git add packages/entry-extractor/README.md packages/web-api/README.md
git commit -m "docs: Browse 계층 목차와 ordinal 설명 반영"
```

---

## Spec Coverage Checklist

| Spec 요구 | Task |
|-----------|------|
| buildEntries ordinal | Task 1 |
| Entry/EntryRecord/EntrySummary + ALTER | Task 2 |
| list_toc ORDER BY ordinal | Task 3 |
| build_toc_items path 헤더 | Task 4 |
| Browse 바로가기 + 계층, details 제거 | Task 5 |
| README | Task 6 |
| Catalog nested 변경 / 중간 노드 저장 / Admin / 백필 | 범위 밖 |

## Self-Review Notes

- Task 3의 DB fixture 이름은 저장소 기존 패턴에 맞춰야 한다. 없으면 테스트 파일 내 최소 fixture를 둔다.
- `disclosure.html`의 “표시할 목차가 없습니다”와 toc partial 중복을 Task 5에서 한곳으로 모은다.
- `first_entry_id`는 primary 우선 — 자동 로드 UX를 유지한다.
