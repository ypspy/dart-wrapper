# 중간 TOC 노드 저장 (`leafOnly` 기본 false) 설계

날짜: 2026-07-27  
상태: 구현 완료
범위: `@dart-wrapper/entry-extractor` 기본 수집 정책 + Catalog가 `is_leaf`로 구분 노출  
관련: 감사보고서 `(첨부)재무제표` 등 신형 TOC에서 제표 본표가 부모 구간에만 있는 경우

## 1. 배경과 목표

기본값 `leafOnly: true`는 자식이 있는 중간 노드를 DB에 넣지 않는다. 그 결과:

- leaf의 `parent_ele_id`가 가리키는 노드 row가 없어 **누락처럼 보인다**
- 신형 감사보고서 TOC처럼 `(첨부)재무제표` 아래 leaf가 `주석`뿐인 경우,  
  **제표 본표는 부모 viewer 구간에만** 있는데 부모 entry가 없어 Catalog에서 열 수 없다

과거 포맷은 재무상태표·손익계산서 등을 **별도 TOC leaf**로 주기도 한다.  
원문에 leaf가 있으면 그대로 저장되면 되고, 없는 제표를 합성하지 않는다.

목표:

1. TOC의 **모든 노드**(중간 포함)를 flat entry로 저장
2. `is_leaf`로 leaf / 중간을 구분
3. 스키마·API 필드 추가 없이 기본 수집 정책만 변경

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 저장 범위 | **모든** TOC 노드 (본문·첨부 동일). 옵션 A |
| 기본값 | `leafOnly: false` (`buildEntries` / `buildEntriesFromDisclosure` / `collectEntries` / CLI) |
| 호환 | `leafOnly: true`는 옵션으로 유지 (테스트·특수 수집) |
| `is_leaf` | 자식 없으면 `true`, 있으면 `false` |
| `viewer_url` | 중간 노드도 DART `eleId`/`offset`/`length` 그대로 (부모 본문이 자식과 겹칠 수 있음 — DART 특성) |
| `ordinal` | 전위순회(부모 → 자식) 등장 순 0… |
| `entry_id` | 기존과 동일 `rcept_no_dcmNo_eleId` (중간도 `eleId` 있음) |
| web-api 스키마 | 변경 없음 (`is_leaf` 이미 존재) |
| Catalog HTML/JSON | non-leaf도 노출. `is_leaf` 컬럼·필드로 구분 |
| 제표 leaf 합성 | **하지 않음** (원문 TOC에 있을 때만 leaf로 존재) |
| 기존 DB | 마이그레이션 스크립트 없음. **재수집**으로 반영 |
| Browse UI | 범위 밖 (이미 제거됨) |

## 3. 동작

### 3.1 추출

`buildEntries` walk:

```
if (isLeaf || !leafOnly) { emit entry with is_leaf: isLeaf }
for child in children: walk(child)
```

기본 `leafOnly=false`이면 모든 노드 emit.  
첨부 `attachmentTrees` walk도 동일.

### 3.2 Catalog / Viewer

- `/api/v1/catalog/.../entries` · `/catalog/{rcp_no}`: 중간 노드 포함 전량
- Viewer는 `viewer_url` Lazy Retrieval 경로 동일. non-leaf도 열람 가능
- UI에서 leaf만 보고 싶으면 클라이언트/`is_leaf` 필터 (1차 필수 아님)

### 3.3 수집 파이프라인

web-api `NodeEntryCollector`가 `leaf_only`를 넘기지 않으면 extractor 기본값(`false`)을 쓴다.  
Admin 수집도 별도 플래그 추가 없음 (필요 시 후속).

## 4. 테스트

1. `buildEntries` 기본: 부모+자식 모두 entry, 부모 `is_leaf=false`, 자식 `true`
2. `leafOnly: true`: 기존처럼 leaf만
3. 첨부 트리: `(첨부)재무제표` + `주석` 둘 다 저장, ordinal 부모 먼저
4. README: 기본값·중간 노드 설명 갱신

## 5. 범위 밖

- 원문에 없는 재무상태표 등 synthetic leaf
- offset gap 전용 가상 섹션
- Admin UI에 `leaf_only` 체크박스
- 기수집 DB ALTER/백필

## 6. 성공 기준

- 신형 감사보고서 재수집 시 `(첨부)재무제표` entry(`is_leaf=false`)와 `주석` leaf가 함께 존재
- 과거처럼 제표가 쪼개진 TOC는 하위 leaf가 그대로 존재
- `npm test` 통과. Catalog가 `is_leaf`를 표시
