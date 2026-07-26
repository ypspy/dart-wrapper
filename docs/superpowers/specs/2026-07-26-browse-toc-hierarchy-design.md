# Browse Viewer 계층 목차 설계

날짜: 2026-07-26  
상태: 브레인스토밍 승인 (구현 전)  
범위: `@dart-wrapper/entry-extractor`의 `ordinal` 부여 + `packages/web-api` Browse 목차 재구성

## 1. 배경과 목표

Browse 왼쪽 목차는 leaf entry를 평탄한 `<ul>`로만 보여 준다. 정렬은 `source` → `dcm_no` →
`ele_id`(문자열)라서 원문 목차 순서와 어긋날 수 있고, `depth`/`path`는 저장돼 있어도 UI에
반영되지 않는다. 중간 노드(`(첨부)재무제표` 등)는 `leafOnly` 수집이라 DB에 없다.

목표:

1. **원문 순서** — 공시 내 leaf 등장 순서를 안정적으로 보존·표시
2. **계층 가시성** — leaf만 유지하면서 `path`로 다단계 그룹 헤더·들여쓰기를 재구성
3. **탐색 UX** — 전체 계층 목차를 기본으로 두고, allowlist 주요 섹션은 상단 바로가기로 분리

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 계층 표현 | leaf 유지. Serve 시 `path`/`depth`로 그룹 헤더 + 들여쓰기 |
| 그룹 헤더 | 인접 leaf의 `path` 접두사 비교. 새로 등장한 조상마다 헤더 행 삽입 (다단계) |
| 순서 | 수집 시 `ordinal`(공시 내 0부터 증가) 저장. 조회는 `ORDER BY ordinal` |
| 기본 화면 | 전체 계층 목차 + (있을 때) 상단 “바로가기”(`primary_entries`) |
| “전체 보기” details | 제거 (전체 계층이 기본이므로 중복) |
| DB 모델 | 계속 leaf-only. 중간 노드를 entry로 저장하지 않음 |
| Catalog JSON | `primary_entries` / `all_entries` flat 구조 유지. `ordinal` 필드만 추가 |
| 기존 데이터 | DB를 비운 상태 전제. `ordinal` null은 정렬 맨 뒤(호환) |

### 2.1 왜 nested TOC JSON / 중간 노드 저장이 아닌가

DB에는 flat leaf만 두는 제품 전제와 맞추고, 이중 저장·동기화를 피한다. `path`만으로
Serve 시 계층 UI를 재구성할 수 있다.

### 2.2 왜 ele_id / offset 정렬이 아닌가

문자열 `ele_id`는 문서 순서를 보장하지 않고, `offset`도 첨·본문 혼합 시 전역 순서가 아니다.
파서 전위순회 시점에 부여하는 `ordinal`이 원문 목차 순서를 직접 보존한다.

## 3. 아키텍처 · 데이터 흐름

```text
[entry-extractor]                       [web-api]
buildEntries가 entry마다                 ① EntryRecord.ordinal → entries.ordinal
ordinal(공시 내 등장 순번) 부여   ──►    ② list_toc: ORDER BY ordinal
  본문 트리 전위순회                     ③ build_toc_items(path) → 헤더+링크
  → 첨부 문서 등장 순서                  ④ Browse: 바로가기 + 계층 목차
  → 각 첨부 트리 전위순회
```

## 4. 컴포넌트

| 단위 | 역할 |
|------|------|
| `entry-extractor` `buildEntries` | 생성 entry마다 공시 내 `ordinal` 부여 (한 카운터로 본문→첨부 연속) |
| `Entry` / `EntryRecord` / `EntrySummary` | `ordinal: int \| null`. 기동 시 `ensure_schema` ALTER |
| `EntryRepository.list_toc_by_rcept_no` | `ORDER BY ordinal ASC NULLS LAST, entry_id` |
| `build_toc_items(entries)` (신규) | leaf → `{kind: "header"\|"link", ...}` 평탄 리스트 |
| Browse `toc.html` + `browse.css` | 바로가기 + 계층 목차. details “전체 보기” 제거 |

### 4.1 ordinal 부여 규칙

- 공시(`rcept_no`) 단위로 0부터 1씩 증가
- 순서: 본문 leaf(트리 전위·leafOnly 규칙과 동일) → `#att`/`#doc` 첨부 문서 등장 순 →
  각 첨부 트리 leaf(또는 fallback 1건)
- body 트리에 이미 있는 `dcmNo` 첨부는 기존처럼 skip (ordinal도 그 위치에서 안 증가)

### 4.2 `build_toc_items` 규칙

입력: `ordinal` 순으로 정렬된 leaf (`path: list[str]`, `section_name`, `entry_id`, …).

각 leaf에 대해 `ancestors = path[:-1]` (path가 비거나 길이 1이면 빈 리스트):

1. 직전 leaf의 ancestors와 공통 접두사 길이 `k`를 구한다
2. `ancestors[k:]`의 각 이름을 순서대로 `kind=header` 항목으로 삽입  
   - `label`: 조상 이름  
   - `indent`: 해당 조상의 depth index (0-based)
3. leaf를 `kind=link`로 삽입  
   - `label`: `section_name` (없으면 `document_name` / `entry_id`)  
   - `indent`: `max(0, len(path) - 1)` (path 비면 `depth` 또는 0)  
   - `entry`: 기존 EntrySummary 전달용

헤더는 클릭 불가. link는 기존 HTMX 섹션 로드와 동일.

### 4.3 Browse 레이아웃

1. **바로가기** — `primary_entries`가 있을 때만. 평탄 링크(들여쓰기 없음)
2. **목차** — `build_toc_items(all_entries)` 결과
3. “전체 보기” `<details>` 제거

## 5. 엣지 케이스

| 상황 | 동작 |
|------|------|
| `path` 비어 있음 | 헤더 없음. leaf indent 0 |
| `path` 길이 1 | 헤더 없음. leaf만 |
| `ordinal` null | 정렬 맨 뒤. UI 동작은 동일 |
| primary 없음 | 바로가기 숨김. 계층 목차만 |
| 첨부 fallback `..._att` | path=`[document_name]`이면 헤더 없이 1행 |

## 6. 테스트

1. `buildEntries` — 본문→첨부 순 ordinal 0,1,2… 연속
2. `build_toc_items` — 접두사 변화에 따른 헤더 삽입·중복 없음
3. Browse UI — 바로가기 + 계층 목차, details 없음
4. `list_toc` — ordinal 순 정렬

## 7. 범위 밖

- Catalog JSON을 nested tree로 변경
- 중간 노드를 DB entry로 저장
- Admin UI 목차
- ordinal-less 기존 DB 일괄 백필 스크립트

## 8. 구현 시 주의

- SQLite는 `NULLS LAST` 문법이 다를 수 있음 → dialect별 order 표현 또는  
  `CASE WHEN ordinal IS NULL THEN 1 ELSE 0 END, ordinal, entry_id`로 통일
- Node collector → Python `EntryRecord` 매핑에 `ordinal` 키 누락 없는지 확인
- DB를 비운 뒤 재수집하면 ordinal이 채워짐. 재수집 전 Browse는 빈 카탈로그
