# 첨부문서 leaf entry 추출 설계

날짜: 2026-07-26  
상태: 브레인스토밍 승인 (구현 전)  
범위: `@dart-wrapper/entry-extractor` — 첨부(`#att`/`#doc`)를 본문과 같이 leaf까지 펼쳐 flat entry로 저장

## 1. 배경과 목표

제품 흐름은 **수집(leaf entry) → 카탈로그 목차 → Viewer Lazy Retrieval**이다. 본문(`treeData`)은
이미 leaf까지 펼치지만, 첨부/관련 문서는 `#att`·`#doc` select의 `dcmNo`당 **문서 단위 1건**
(`entry_id=..._att`, `ele_id`/`offset`/`length` 없음)으로만 저장된다.

그 결과 Browse·API에서 첨부는 섹션 단위로 고를 수 없고, Agent도 첨부 leaf `viewer_url`로
본문과 동일한 품질의 Lazy Retrieval을 하기 어렵다.

이번 스펙의 목표:

1. **Browse/카탈로그** — 첨부도 본문처럼 섹션(leaf) 단위로 선택·열람
2. **Agent/API** — 첨부 leaf의 `viewer_url`로 Lazy Retrieval (본문과 동일 entry 품질)

웹 API·Browse UI 계약 변경은 범위 밖이다. entry 스키마를 유지한 채 수집 품질만 올린다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 성공 기준 | Browse + API 모두 본문과 동일 leaf 카탈로그 품질 |
| 접근 | 첨부 전용 `dcmNo`마다 `main.do?rcpNo&dcmNo` 재파싱 (기존 `extractTree` 재사용) |
| 목차 없음/빈 트리 | 문서 단위 1건 fallback (`..._att`) |
| 목차 있음 | leaf만 저장. 문서 단위 `..._att`는 만들지 않음 |
| 본문 트리에 이미 있는 `dcmNo` | 재요청하지 않음. body leaf만 유지 |
| 요청 범위 | `includeAttachments=true`일 때 첨부 전용 `dcmNo`를 **항상** 펼침 (완전성 우선) |
| 옵션 분리 | `expandAttachments` 같은 신규 플래그 없음. 기존 `includeAttachments` 재사용 |
| Serve/API | 스키마·엔드포인트 변경 없음. `source`/`path`/`viewer_url`로 동작 |
| 기존 DB `..._att` | 일괄 마이그레이션 없음. 필요 시 Admin 기간 재수집 |

### 2.1 왜 on-demand(Serve 시) 펼치기가 아닌가

DB에는 entry만 두고 목차·Agent 탐색은 저장된 leaf에 의존한다. Serve 시점에만 첨부 트리를
파싱하면 카탈로그가 “저장 entry”가 아니게 되어 Lazy Retrieval 전제와 어긋난다.

### 2.2 왜 Viewer HTML 휴리스틱이 아닌가

`eleId`/`offset`/`length` 없이 추정한 URL은 Viewer·`entry_id` 안정성이 낮다. 본문과 동일한
`treeData` 파서가 목표 품질에 맞다.

## 3. 아키텍처 · 데이터 흐름

```text
[공시 상세 main.do]  ──1회──►  body treeData + #att/#doc 목록
                                    │
                                    ├─ body: 기존 walk → leaf (source=body)
                                    │
                                    └─ attachment dcmNo 중 body 트리에 없는 것만
                                            │
                         각 dcmNo마다 main.do?rcpNo&dcmNo  ──추가 N회──►
                                            │
                                   tree 있음 → leaf (source=attachment)
                                   tree 없음/실패 → 문서 1건 (..._att) fallback
```

- **변경 중심**: `packages/entry-extractor` (`documents.js`, `entries.js`, CLI·README)
- **호출 경로**: `collectEntries` / `bin/collect-entries.js` → Admin 수집기는 파라미터 추가 없이
  동작이 완전성 쪽으로 향상됨
- **비변경**: entry 필드 집합, `web-api` Viewer/Browse/Catalog 계약

## 4. 컴포넌트 · entry 규칙

| 단위 | 역할 |
|------|------|
| `parseDetail` | body tree + 첨부 목록. body에 등장한 `dcmNo` 집합을 알 수 있게 함 |
| `parseAttachmentDetail(rcpNo, dcmNo)` (신규) | `main.do?rcpNo&dcmNo` 1회 → `extractTree` 재사용. 빈 트리/실패는 빈 결과 |
| `buildEntries` | body walk 유지. 첨부 전용 문서마다: 대응 트리가 비어 있지 않으면 leaf walk(`source=attachment`), 아니면 `..._att` 1건 |
| `collectEntries` | `parseDetail` 후, `includeAttachments=true`이면 body에 없는 첨부 `dcmNo`만 `parseAttachmentDetail`로 트리를 모아 `buildEntries`에 넘김 (기존 `safeGet` 지연·재시도) |

**핸드오프:** `collectEntries`(또는 동일 오케스트레이션)가  
`Map<dcmNo, tree[]>`(또는 동등 구조)를 만들어 `buildEntries(disclosure, detail, { attachmentTrees, ... })`에 전달한다.  
`buildEntries`는 HTTP를 하지 않는다. 단위 테스트에서 fixture 트리만 주입할 수 있다.

### 4.1 entry 필드

- `source`: 첨부에서 펼친 leaf·fallback 모두 `'attachment'`
- `document_name`: `#att`/`#doc` select에서 얻은 첨부 문서명
- `section_name` / `path` / `ele_id` / `offset` / `length` / `dtd` / `viewer_url`: 본문 leaf와 동일 규칙 (트리 노드 기준)
- fallback만: `ele_id`/`offset`/`length`/`dtd`는 null, `path=[document_name]`, 문서 URL

### 4.2 entry_id

| 경우 | 형식 | 예 |
|------|------|-----|
| 첨부 leaf | `rcept_no_dcmNo_eleId` | `20260724000650_11495099_3` |
| 첨부 fallback | `rcept_no_dcmNo_att` | `20260724000650_11495099_att` |

본문/첨부는 `source`로 구분한다. leaf id 형식은 본문과 통일한다.

### 4.3 중복 방지

같은 `dcmNo`가 body `treeData`에 있으면:

- 해당 `dcmNo`에 대한 첨부 fetch를 하지 않는다
- `source=attachment` entry를 추가로 만들지 않는다 (이미 `source=body` leaf로 존재)

## 5. 오류 처리

첨부 추가 fetch는 공시당 N회이므로, **한 첨부 실패가 공시 전체 수집을 깨지 않는다.**

| 상황 | 동작 |
|------|------|
| 첨부 `main.do` 일시 오류(5xx·타임아웃) | `safeGet` 지수 백오프 재시도. 최종 실패 시 그 `dcmNo`만 `..._att` fallback. 본문·다른 첨부는 계속 |
| HTML은 왔지만 `treeData` 없음/빈 트리 | 즉시 `..._att` fallback (재시도 불필요) |
| `includeAttachments=false` | 첨부 fetch·첨부 entry 없음 (현행) |
| 본문 `parseDetail` 자체 실패 | 현행과 동일 — 해당 공시 수집 실패 (첨부 단계 진입 안 함) |

로그(stderr): 첨부 `dcmNo`별 `expanded` / `fallback` / `fetch_failed→fallback`.  
진행 콜백에 첨부 펼친 건수 포함은 선택 사항이다.

## 6. 테스트

`entry-extractor` 단위 테스트(fixture HTML):

1. 본문 트리에 이미 있는 `dcmNo` → 첨부 fetch 0회, 중복 entry 없음
2. `#att` 전용 `dcmNo` + 목차 있음 → leaf 여러 개, `source=attachment`, `..._att` 없음
3. `#att` 전용 + 빈 목차 → `..._att` 1건만
4. 첨부 fetch 실패 → 해당 건만 fallback, 본문 leaf 유지
5. `includeAttachments=false` → 첨부 관련 entry·fetch 없음

## 7. 범위 밖

- `web-api` 스키마·엔드포인트 변경
- Browse UI의 첨부 전용 그룹 UI 개편 (기존 `source`/`path` 표시로 충분)
- PDF 바이너리 파싱, OpenDART
- 이미 DB에 있는 `..._att` 일괄 재수집 마이그레이션

## 8. 문서

`packages/entry-extractor/README.md`에 “첨부도 leaf까지 / 목차 없으면 문서 단위 fallback /
본문 트리에 있는 dcmNo는 skip”을 명시한다.

## 9. 구현 시 주의

- 요청 간 기본 1초 지연 + 지수 백오프는 첨부 fetch에도 동일 적용 (DART 부하)
- 주말·공휴일 0건·HTML 구조 변경 가능성은 기존과 동일
- Admin 재수집 시 같은 `entry_id` upsert로 leaf가 `..._att`를 자연 대체할 수 있음
  (leaf id ≠ `..._att`이므로, 재수집 후 옛 `..._att`가 남을 수 있음 — 범위 밖; 필요 시
  운영에서 해당 공시 엔트리 정리 또는 후속 스펙으로 다룸)
