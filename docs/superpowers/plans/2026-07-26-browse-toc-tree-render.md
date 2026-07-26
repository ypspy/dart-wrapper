# Browse 목차 트리 렌더 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Browse 목차를 중첩 `<ul>`+가이드선 트리로 렌더하고, 본문/첨부 구역을 분리하며, 헤더는 Bold 없이 muted·leaf는 파란 링크로 구분한다.

**Architecture:** `build_toc_items`는 유지한다. `to_nested_rows`가 indent 변화로 여는·닫는 `<ul>` 개수를 계산한다. `build_toc_sections`가 `source`별로 「본문」「첨부」 구역을 만들고, Browse 템플릿·CSS만 바꿔 렌더한다.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, HTMX, pytest

**Spec:** `docs/superpowers/specs/2026-07-26-browse-toc-tree-render-design.md`

## Global Constraints

- 주석·Docstring·로그·사용자 메시지는 **한국어**
- Bold 금지: 헤더·구역 제목 `font-weight: 400`
- `ordinal` / Catalog API / `build_toc_items` 접두사 규칙 / 수집기 변경 금지
- 바로가기 섹션 로직 유지
- `--toc-indent` 인라인 스타일 제거
- 구역 라벨: **「본문」** / **「첨부」**. 해당 source 없으면 숨김
- 작업 디렉터리: `packages/web-api`
- 테스트: `.\.venv\Scripts\python.exe -m pytest …` (또는 저장소 루트에서 web-api venv)

## File Structure

| Path | Responsibility |
|------|----------------|
| `app/services/toc_items.py` | `TocRow`, `to_nested_rows`, `build_toc_sections` |
| `app/api/browse/ui.py` | `toc_sections` 컨텍스트 전달 (`toc_items` 제거) |
| `app/templates/browse/partials/toc.html` | 구역 + 중첩 트리 마크업 |
| `app/static/browse.css` | 가이드선·헤더/leaf·구역 제목 스타일 |
| `tests/test_toc_items.py` | nested rows + sections 단위 테스트 |
| `tests/test_browse_ui.py` | 구역·트리·스타일 마크업 검증 |
| `packages/web-api/README.md` | Browse 목차 설명 한 줄 갱신 |

---

### Task 1: `to_nested_rows` + `build_toc_sections`

**Files:**
- Modify: `packages/web-api/app/services/toc_items.py`
- Modify: `packages/web-api/tests/test_toc_items.py`

**Interfaces:**
- Consumes: 기존 `TocItem`, `build_toc_items`
- Produces:
  - `@dataclass TocRow(item: TocItem, open_levels: int, close_levels: int)`
  - `to_nested_rows(items: Sequence[TocItem]) -> tuple[list[TocRow], int]`
  - `@dataclass TocSection(title: str, rows: list[TocRow], trailing_close: int)`
  - `build_toc_sections(entries: Sequence[TocEntryLike]) -> list[TocSection]`  
    body(`source=="body"`) → title `"본문"`, attachment → `"첨부"`. 빈 그룹 생략.

- [ ] **Step 1: Write the failing tests**

`tests/test_toc_items.py`에 추가:

```python
from app.services.toc_items import (
    TocItem,
    build_toc_items,
    build_toc_sections,
    to_nested_rows,
)


def test_to_nested_rows_opens_and_closes() -> None:
    items = [
        TocItem(kind="header", label="A", indent=0),
        TocItem(kind="link", label="B", indent=1, entry=_e("1", ["A", "B"], "B")),
        TocItem(kind="header", label="C", indent=1),
        TocItem(kind="link", label="D", indent=2, entry=_e("2", ["A", "C", "D"], "D")),
        TocItem(kind="link", label="E", indent=1, entry=_e("3", ["A", "E"], "E")),
    ]
    rows, trailing = to_nested_rows(items)
    assert [(r.open_levels, r.close_levels, r.item.label) for r in rows] == [
        (0, 0, "A"),
        (1, 0, "B"),
        (0, 0, "C"),
        (1, 0, "D"),
        (0, 1, "E"),
    ]
    assert trailing == 1


def test_to_nested_rows_flat() -> None:
    items = [
        TocItem(kind="link", label="X", indent=0, entry=_e("1", ["X"], "X")),
        TocItem(kind="link", label="Y", indent=0, entry=_e("2", ["Y"], "Y")),
    ]
    rows, trailing = to_nested_rows(items)
    assert all(r.open_levels == 0 and r.close_levels == 0 for r in rows)
    assert trailing == 0


def test_build_toc_sections_splits_body_and_attachment() -> None:
    body = EntrySummary(
        entry_id="b1",
        source="body",
        section_name="재무상태표",
        path=["감사보고서", "재무상태표"],
        depth=2,
    )
    att = EntrySummary(
        entry_id="a1",
        source="attachment",
        section_name="첨부문서",
        path=["첨부", "첨부문서"],
        depth=2,
    )
    sections = build_toc_sections([body, att])
    assert [s.title for s in sections] == ["본문", "첨부"]
    assert sections[0].rows
    assert sections[1].rows


def test_build_toc_sections_hides_empty_body() -> None:
    att = EntrySummary(
        entry_id="a1",
        source="attachment",
        section_name="첨부문서",
        path=["첨부문서"],
        depth=1,
    )
    sections = build_toc_sections([att])
    assert [s.title for s in sections] == ["첨부"]
```

- [ ] **Step 2: Run tests — Expected FAIL**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_toc_items.py -v
```

- [ ] **Step 3: Implement**

`toc_items.py`에 추가:

```python
@dataclass(frozen=True)
class TocRow:
    item: TocItem
    open_levels: int
    close_levels: int


@dataclass(frozen=True)
class TocSection:
    title: str
    rows: list[TocRow]
    trailing_close: int


def to_nested_rows(items: Sequence[TocItem]) -> tuple[list[TocRow], int]:
    """indent 변화로 중첩 <ul> 개폐 수를 계산한다."""
    rows: list[TocRow] = []
    prev_indent = 0
    for item in items:
        indent = item.indent
        open_levels = max(0, indent - prev_indent)
        close_levels = max(0, prev_indent - indent)
        rows.append(
            TocRow(item=item, open_levels=open_levels, close_levels=close_levels)
        )
        prev_indent = indent
    return rows, prev_indent


def build_toc_sections(entries: Sequence[TocEntryLike]) -> list[TocSection]:
    """source별로 본문/첨부 목차 구역을 만든다."""
    groups: list[tuple[str, list[TocEntryLike]]] = [
        ("본문", [e for e in entries if getattr(e, "source", None) == "body"]),
        (
            "첨부",
            [e for e in entries if getattr(e, "source", None) == "attachment"],
        ),
    ]
    sections: list[TocSection] = []
    for title, group in groups:
        if not group:
            continue
        rows, trailing = to_nested_rows(build_toc_items(group))
        sections.append(TocSection(title=title, rows=rows, trailing_close=trailing))
    return sections
```

**주의:** `close_levels`는 **다음 행으로 넘어가기 전**이 아니라, indent가 줄어든 **현재 행을 출력하기 직전**에 이전 깊이를 닫는 값이다. 위 구현은 현재 행의 indent가 prev보다 작을 때 `close_levels`를 넣고 그 다음 현재 행을 출력한다. 템플릿 순서는 **open → item → close**가 아니라 스펙 마크업대로 **open → item → close**인데, 깊이 하강 시에는 **먼저 닫고 나서** 형제 항목을 써야 한다.

스펙 마크업 순서:

```
open_levels 만큼 <ul>
<li>item</li>
close_levels 만큼 </ul>
```

하강 케이스(indent 2→1)에서는 **현재 item 전에** 닫아야 한다. 따라서 템플릿/헬퍼를 스펙과 맞추려면:

**결정 (구현):** `close_levels`는 “이 행을 출력하기 **전에** 닫을 개수”, `open_levels`는 “이 행을 출력하기 **전에** 열 개수”. 템플릿:

```html
{% for _ in range(row.close_levels) %}</ul>{% endfor %}
{% for _ in range(row.open_levels) %}<ul class="toc-branch">{% endfor %}
<li>…</li>
```

그리고 `to_nested_rows` 계산:

```python
def to_nested_rows(items: Sequence[TocItem]) -> tuple[list[TocRow], int]:
    rows: list[TocRow] = []
    prev_indent = 0
    for item in items:
        indent = item.indent
        close_levels = max(0, prev_indent - indent)
        open_levels = max(0, indent - prev_indent)
        rows.append(
            TocRow(item=item, open_levels=open_levels, close_levels=close_levels)
        )
        prev_indent = indent
    return rows, prev_indent
```

테스트 assert도 이 의미에 맞춘다:

```python
# A0, B1, C1, D2, E1
assert [(r.close_levels, r.open_levels, r.item.label) for r in rows] == [
    (0, 0, "A"),
    (0, 1, "B"),
    (0, 0, "C"),
    (0, 1, "D"),
    (1, 0, "E"),
]
assert trailing == 1
```

Step 1 테스트를 위 assert로 작성할 것.

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Commit**

```bash
git add app/services/toc_items.py tests/test_toc_items.py
git commit -m "feat(web-api): 목차 중첩 행 계산과 본문/첨부 구역 분리"
```

---

### Task 2: Browse UI — 템플릿·CSS·라우터

**Files:**
- Modify: `packages/web-api/app/api/browse/ui.py`
- Modify: `packages/web-api/app/templates/browse/partials/toc.html`
- Modify: `packages/web-api/app/static/browse.css`
- Modify: `packages/web-api/tests/test_browse_ui.py`
- Modify: `packages/web-api/README.md`

**Interfaces:**
- Consumes: `build_toc_sections`
- Produces: 템플릿 컨텍스트 `toc_sections: list[TocSection]`. `toc_items` 제거.

- [ ] **Step 1: Update Browse tests (fail first)**

`FakeCatalogQueryService.list_entries`는 이미 body+attachment를 준다. 테스트 갱신:

```python
async def test_browse_disclosure_shows_shortcut_and_tree(client_factory) -> None:
    async with client_factory(_app()) as client:
        response = await client.get("/browse/20260724000650")
    assert response.status_code == 200
    assert "바로가기" in response.text
    assert "toc-tree" in response.text
    assert "toc-branch" in response.text or "toc-section" in response.text
    assert "본문" in response.text
    assert "첨부" in response.text
    assert "--toc-indent" not in response.text
    assert "전체 보기" not in response.text


async def test_browse_disclosure_empty_primary_opens_all(client_factory) -> None:
    async with client_factory(_app(catalog=EmptyPrimaryService())) as client:
        response = await client.get("/browse/20260724000650")
    assert response.status_code == 200
    assert "첨부문서" in response.text
    assert "바로가기" not in response.text
    assert "첨부" in response.text
    assert "본문" not in response.text  # EmptyPrimary는 attachment만
    assert "전체 보기" not in response.text
```

`test_browse_disclosure_shows_primary_toc`에서 `toc-header`/`감사보고서` 검사는 유지하되 `--toc-indent` 관련 assert가 있으면 제거.

- [ ] **Step 2: Run Browse tests — Expected FAIL**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_browse_ui.py -v
```

- [ ] **Step 3: Wire `ui.py`**

```python
from app.services.toc_items import build_toc_sections

# browse_disclosure 안:
toc_sections = build_toc_sections(toc.all_entries)
# context: "toc_sections": toc_sections  (toc_items 키 삭제)
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

  {% if toc_sections %}
    {% for section in toc_sections %}
    <section class="toc-section">
      <h3 class="toc-section-title">{{ section.title }}</h3>
      <ul class="toc-tree">
        {% for row in section.rows %}
          {% for _ in range(row.close_levels) %}</ul>{% endfor %}
          {% for _ in range(row.open_levels) %}<ul class="toc-branch">{% endfor %}
          {% if row.item.kind == "header" %}
          <li class="toc-header">{{ row.item.label }}</li>
          {% else %}
          <li class="toc-link">{{ toc_link(row.item.entry) }}</li>
          {% endif %}
        {% endfor %}
        {% for _ in range(section.trailing_close) %}</ul>{% endfor %}
      </ul>
    </section>
    {% endfor %}
  {% elif not toc.primary_entries %}
  <p>표시할 목차가 없습니다.</p>
  {% endif %}
</nav>
```

- [ ] **Step 5: Update `browse.css`**

기존 `.toc-tree .toc-header` / `--toc-indent` 규칙을 스펙 §6 스타일로 교체. `:root` 또는 기존 변수 블록에 `--link: #1d4ed8;` 추가(없을 때).

제거:

```css
.toc-tree .toc-header,
.toc-tree .toc-link {
  padding-left: calc(var(--toc-indent, 0) * 12px);
}
```

추가: `.toc-section`, `.toc-section-title`, `.toc-branch`, leaf 링크 색(`font-weight: 400` 명시).

- [ ] **Step 6: README 한 줄**

Browse 목차 설명에 “본문/첨부 구역 + 가이드라인 트리”를 반영.

- [ ] **Step 7: Run tests — PASS**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_toc_items.py tests/test_browse_ui.py -v
```

- [ ] **Step 8: Commit**

```bash
git add app/api/browse/ui.py app/templates/browse/partials/toc.html app/static/browse.css tests/test_browse_ui.py README.md
git commit -m "feat(web-api): Browse 목차 가이드라인 트리와 본문/첨부 구역"
```

---

## Spec Coverage Checklist

| Spec 요구 | Task |
|-----------|------|
| `to_nested_rows` | Task 1 |
| 본문/첨부 구역 | Task 1–2 |
| 중첩 마크업 + CSS (Bold 없음, 파란 leaf) | Task 2 |
| `--toc-indent` 제거 | Task 2 |
| 바로가기 유지 | Task 2 |
| 테스트 1–5 | Task 1–2 |
| 접이식 / API / 수집기 | 범위 밖 |

## Self-Review Notes

- 템플릿은 **close → open → item** 순서 (하강 시 형제 앞에 닫기).
- `EmptyPrimaryService`는 attachment만 있으므로 「본문」 미출현 assert가 성립한다.
- HTML5에서 `<ul>` 직계 `<ul>`은 엄밀히는 invalid이나 스펙·브라우저 관용에 따름. 시각 목표를 우선한다.
