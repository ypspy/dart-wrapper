# Browse 목차 트리 렌더 개선 설계

날짜: 2026-07-26  
상태: 브레인스토밍 승인 (구현 전)  
범위: `packages/web-api` — Browse 목차 partial 템플릿과 `browse.css`

## 1. 배경과 목표

`ordinal` 정렬과 `build_toc_items`(path 접두사 기반 헤더 삽입)는 이미 동작한다. 그러나 렌더가
평탄한 `<ul>`에 `padding-left: indent * 12px`만 주는 방식이라, 원문 목차가 3–4단까지
내려가면 두 가지 문제가 생긴다.

1. **깊이 인지 실패** — 12px 들여쓰기만으로는 3단과 4단이 구분되지 않는다
2. **헤더/leaf 혼동** — 상위 헤더와 클릭 가능한 leaf가 비슷해 보인다

목표는 데이터·API를 그대로 두고 **렌더와 스타일만** 고쳐 계층을 읽히게 하는 것이다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 방향 | 시각안 B — 세로 가이드라인 트리 + 헤더/leaf 대비 |
| Bold 강조 | **사용하지 않음**. 헤더는 일반 weight + muted 색만 |
| 마크업 | 평탄 리스트 대신 indent에 맞춘 **중첩 `<ul>`** |
| 깊이 표시 | 중첩 `<ul>`마다 `border-left` 가이드선 + 단당 14–16px |
| leaf | 파란 링크 + 호버 배경. 클릭 동작은 현행 HTMX 그대로 |
| 헤더 | 클릭 불가 (`pointer-events: none`) |
| 바로가기 | 현행 유지. 이번 범위에서 손대지 않음 |
| 비변경 | `ordinal`, Catalog API, `build_toc_items` 규칙, 수집기 |

### 2.1 왜 접이식(안 C)이 아닌가

토글 상태 관리(초기 펼침 규칙, HTMX 갱신 후 상태 유지)가 붙는다. 지금 문제는 “깊이가 안
보인다”이므로 정적 트리로 충분하다. 접기는 필요해지면 후속으로 다룬다.

### 2.2 왜 `build_toc_items`를 바꾸지 않는가

`TocItem(kind, label, indent, entry)`는 이미 렌더에 필요한 정보를 모두 담고 있다. 중첩은
순수 표현 문제이므로 템플릿에서 해결한다.

## 3. 구조 · 데이터 흐름

```text
정렬된 leaf ──► build_toc_items ──► TocItem[] (kind, label, indent, entry)
                                        │
                                        └─► toc.html: indent 기준 중첩 <ul> 생성
                                              헤더 = <li class="toc-header">
                                              leaf  = <li class="toc-link"><a …>
```

### 3.1 중첩 규칙

`toc_items`는 평탄하지만 `indent`가 단조롭게 오르내린다. 템플릿은 직전 항목의 `indent`와
비교해 트리를 만든다.

- `indent > prev` → 그 차이만큼 `<ul class="toc-branch">` 열기
- `indent < prev` → 그 차이만큼 `</ul>` 닫기
- `indent == prev` → 형제로 이어 붙이기
- 마지막에 열린 `<ul>`을 모두 닫기

Jinja에서 상태를 들고 다니기 번거로우므로, **템플릿 필터/헬퍼 하나**로 여는·닫는 태그 수를
미리 계산해 넘긴다. 즉 `build_toc_items` 결과를 렌더 직전에
`(item, open_count, close_count)` 형태로 감싸는 얇은 헬퍼를 둔다.

- 위치: `app/services/toc_items.py` (기존 모듈 재사용)
- 이름: `to_nested_rows(items) -> list[TocRow]`
- `TocRow`: `item: TocItem`, `open_levels: int`, `close_levels: int`
- 마지막 행 뒤에 남은 닫기 수는 `trailing_close: int`로 별도 반환하거나 마지막 행의
  `close_after`에 합산한다. **결정:** `to_nested_rows`는
  `tuple[list[TocRow], int]`를 반환하고, 두 번째 값이 마지막에 닫을 `</ul>` 개수다.

## 4. 마크업

```html
<ul class="toc-tree">
  {# 각 행마다 open_levels 만큼 <ul class="toc-branch"> 를 연다 #}
  <li class="toc-header">감사보고서</li>
  <ul class="toc-branch">
    <li class="toc-header">(첨부)재무제표</li>
    <ul class="toc-branch">
      <li class="toc-link"><a …>재무상태표</a></li>
    </ul>
  </ul>
</ul>
```

`indent` 인라인 스타일(`--toc-indent`)은 제거한다. 깊이는 중첩과 CSS가 담당한다.

## 5. 스타일

```css
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
  font-weight: 400;       /* Bold 없음 */
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

## 6. 엣지 케이스

| 상황 | 동작 |
|------|------|
| 모든 leaf가 indent 0 | 중첩 없음. 평탄 리스트와 동일 |
| 깊이가 갑자기 2단 이상 증가 | `open_levels`가 2 이상 → 빈 `<ul>` 중첩이 생기지만 가이드선만 늘어남 |
| 깊이가 여러 단 감소 | `close_levels`로 한 번에 닫음 |
| `toc_items` 비어 있음 | 기존처럼 “표시할 목차가 없습니다” (바로가기도 없을 때) |

## 7. 테스트

1. `to_nested_rows` — 상승/하강/동일 indent에 대한 open/close 수와 trailing close
2. Browse UI — `toc-branch`가 렌더되고 `--toc-indent` 인라인 스타일이 사라짐
3. Browse UI — 헤더는 `<a>`가 아니고, leaf는 `<a>`로 렌더

## 8. 범위 밖

- 접이식 토글(안 C)
- 바로가기 섹션 재설계
- `build_toc_items` 헤더 규칙 변경
- Admin UI 목차

## 9. 구현 시 주의

- Jinja에서 `</ul>`를 조건부로 출력하면 HTML이 깨지기 쉬우므로, 여는·닫는 수를
  파이썬에서 계산해 넘기고 템플릿은 반복만 한다.
- 기존 테스트에서 `--toc-indent`를 검사하는 부분이 있으면 함께 갱신한다.
