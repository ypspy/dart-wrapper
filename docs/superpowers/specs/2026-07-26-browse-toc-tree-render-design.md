# Browse 목차 트리 렌더 개선 설계

날짜: 2026-07-26  
상태: 브레인스토밍 승인 (구현 전)  
범위: `packages/web-api` — Browse 목차 partial 템플릿, `browse.css`, 얇은 toc 헬퍼

## 1. 배경과 목표

`ordinal` 정렬과 `build_toc_items`(path 접두사 기반 헤더 삽입)는 이미 동작한다. 그러나 렌더가
평탄한 `<ul>`에 `padding-left: indent * 12px`만 주는 방식이라, 원문 목차가 3–4단까지
내려가면 문제가 생긴다. 또한 본문 leaf와 첨부 leaf가 한 목록에 섞여 보여 원문(본문
treeData vs `#att`/`#doc`)과 다르게 읽힌다.

목표:

1. **깊이 인지** — 중첩 목록 + 세로 가이드선으로 3–4단을 읽히게
2. **헤더/leaf 구분** — muted 헤더(Bold 없음) vs 파란 leaf 링크
3. **본문/첨부 섹션 구분** — 목차에서 원문 문서와 첨부 문서를 구역으로 나눔

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 방향 | 시각안 B — 세로 가이드라인 트리 + 헤더/leaf 대비 |
| Bold 강조 | **사용하지 않음**. 헤더는 일반 weight + muted 색만 |
| 마크업 | 평탄 리스트 대신 indent에 맞춘 **중첩 `<ul>`** |
| 깊이 표시 | 중첩 `<ul>`마다 `border-left` 가이드선 + 단당 14–16px |
| leaf | 파란 링크 + 호버 배경. 클릭 동작은 현행 HTMX 그대로 |
| 헤더 | 클릭 불가 (`pointer-events: none`) |
| 본문/첨부 | `source`로 분리. 라벨 **「본문」** / **「첨부」**. 해당 source가 없으면 구역 숨김 |
| 구역 순서 | 본문 구역 → 첨부 구역 (ordinal이 이미 본문 선·첨부 후이므로 일치) |
| 바로가기 | 현행 유지. 이번 범위에서 손대지 않음 |
| 비변경 | `ordinal`, Catalog API flat 구조, `build_toc_items` 접두사 규칙, 수집기 |

### 2.1 왜 접이식(안 C)이 아닌가

토글 상태 관리가 붙는다. 지금 문제는 깊이·구분 가시성이므로 정적 트리로 충분하다.

### 2.2 왜 source 구역을 `build_toc_items` 안에 넣지 않는가

접두사 헤더는 path 로컬 문제이고, 본문/첨부는 source 전역 구역이다. `all_entries`를
source별로 나눈 뒤 구역마다 `build_toc_items`를 호출하는 편이 경계가 명확하다.

## 3. 구조 · 데이터 흐름

```text
all_entries
  ├─ source==body        ──► build_toc_items ──► to_nested_rows ──► 「본문」 구역
  └─ source==attachment  ──► build_toc_items ──► to_nested_rows ──► 「첨부」 구역
```

Browse `ui.py`가 구역 리스트를 만들어 템플릿에 넘긴다.

```python
# 의사코드
body = [e for e in toc.all_entries if e.source == "body"]
att = [e for e in toc.all_entries if e.source == "attachment"]
toc_sections = []
if body:
    rows, trailing = to_nested_rows(build_toc_items(body))
    toc_sections.append({"title": "본문", "rows": rows, "trailing_close": trailing})
if att:
    rows, trailing = to_nested_rows(build_toc_items(att))
    toc_sections.append({"title": "첨부", "rows": rows, "trailing_close": trailing})
```

바로가기는 기존처럼 `toc.primary_entries`를 구역 위에 둔다.

## 4. 중첩 헬퍼

- 위치: `app/services/toc_items.py`
- `to_nested_rows(items) -> tuple[list[TocRow], int]`
- `TocRow`: `item: TocItem`, `open_levels: int`, `close_levels: int`
- 두 번째 반환값: 마지막에 닫을 `</ul>` 개수 (`trailing_close`)

규칙:

- `indent > prev` → `open_levels = indent - prev`
- `indent < prev` → `close_levels = prev - indent`
- `indent == prev` → 둘 다 0
- 마지막에 열린 깊이만큼 `trailing_close`

## 5. 마크업

```html
{% if toc.primary_entries %}
<section class="toc-shortcut">…</section>
{% endif %}

{% for section in toc_sections %}
<section class="toc-section">
  <h3 class="toc-section-title">{{ section.title }}</h3>
  <ul class="toc-tree">
    {% for row in section.rows %}
      {% for _ in range(row.open_levels) %}<ul class="toc-branch">{% endfor %}
      {% if row.item.kind == "header" %}
      <li class="toc-header">{{ row.item.label }}</li>
      {% else %}
      <li class="toc-link">{{ toc_link(row.item.entry) }}</li>
      {% endif %}
      {% for _ in range(row.close_levels) %}</ul>{% endfor %}
    {% endfor %}
    {% for _ in range(section.trailing_close) %}</ul>{% endfor %}
  </ul>
</section>
{% endfor %}
```

`indent` 인라인 스타일(`--toc-indent`)은 제거한다.

## 6. 스타일

```css
.toc-section { margin-top: 12px; }
.toc-section:first-of-type { margin-top: 0; }
.toc-section-title {
  font-size: 0.78rem;
  font-weight: 400;          /* Bold 없음 */
  color: var(--text-muted);
  letter-spacing: 0.02em;
  margin: 0 0 6px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border);
}

.toc-tree,
.toc-branch { list-style: none; margin: 0; padding: 0; }

.toc-branch {
  margin-left: 7px;
  padding-left: 9px;
  border-left: 1px solid var(--border);
}

.toc-tree .toc-header {
  color: var(--text-muted);
  font-size: 0.8rem;
  font-weight: 400;
  pointer-events: none;
  margin: 6px 0 2px;
  padding: 2px 4px;
}

.toc-tree .toc-link > a {
  color: var(--link, #1d4ed8);
  font-size: 0.86rem;
  padding: 4px 6px;
  border-radius: 5px;
}
.toc-tree .toc-link > a:hover { background: var(--surface-soft); }
```

`--link` 토큰이 없으면 `browse.css` 상단 변수에 추가한다.

## 7. 엣지 케이스

| 상황 | 동작 |
|------|------|
| 본문만 있음 | 「본문」 구역만 |
| 첨부만 있음 | 「첨부」 구역만 |
| 둘 다 없음 | 바로가기도 없으면 “표시할 목차가 없습니다” |
| 모든 leaf가 indent 0 | 중첩 없음 |
| 깊이 급변 | open/close levels로 처리 |

## 8. 테스트

1. `to_nested_rows` — 상승/하강/동일 indent, trailing close
2. Browse UI — `toc-branch` 렌더, `--toc-indent` 없음
3. Browse UI — 헤더는 `<a>` 없음, leaf는 `<a>`
4. Browse UI — 본문+첨부 fixture에서 「본문」「첨부」 구역 제목 출현
5. Browse UI — 첨부만 있을 때 「본문」 미출현

## 9. 범위 밖

- 접이식 토글(안 C)
- 바로가기 섹션 재설계
- `build_toc_items` path 접두사 규칙 변경
- Admin UI 목차
- source 외 세분(문서명별 추가 구역)

## 10. 구현 시 주의

- Jinja에서 `</ul>` 개수는 파이썬이 계산한다
- 기존 테스트의 `--toc-indent` / “한 목록” 가정은 함께 갱신한다
- Fake catalog fixture에 body·attachment를 섞어 구역 테스트를 넣는다
