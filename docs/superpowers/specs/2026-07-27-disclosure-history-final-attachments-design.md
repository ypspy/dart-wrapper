# 공시 이력 목록 + 첨부 최종본만 추출 설계

날짜: 2026-07-27  
상태: 구현 완료
범위: `@dart-wrapper/entry-extractor` — 상세검색 `finalReport` 기본값 + `#att`/`#doc` 최종본 필터

## 1. 배경과 목표

DART 상세검색의 **최종보고서** 체크(`finalReport=recent`)가 켜져 있으면 목록에
최신(최종) 접수만 나온다. 체크를 끄면 **최종본과 수정/정정 전 접수**가 함께 나와
공시 이력을 따라갈 수 있다.

현재 `fetchDisclosureList*`는 항상 `finalReport: 'recent'`를 넣어 **이력 목록이 막혀 있다.**

한편 상세페이지 `#att`/`#doc`에는 같은 문서명(예: 감사보고서)이 **서로 다른 rcpNo**
(정정본·원본)로 여러 줄 나올 수 있다. 목록이 “최종만”이든 “이력 포함”이든,
**한 접수 단위를 펼칠 때 첨부까지 옛 버전을 전부 leaf로 넣으면** “입수 문서는 최종
링크” 정책과 어긋난다. 본문은 해당 `rcpNo`의 treeData만 쓰므로 사실상 그 접수 본문이지만,
첨부는 option 전량을 펼치고 있다.

목표:

1. **목록** — 기본으로 최종보고서 체크 **해제**와 동일하게 동작해 이력을 수집
2. **첨부** — 동일 문서명 그룹에서 **최종(최신) 1건만** 펼침 (`#att`/`#doc` 동일)

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 목록 `finalReport` | 기본 **미전송**(체크 해제). 옵션으로 `finalReport: 'recent'` 재활성화 가능 |
| 첨부 최종본 선정 | 정규화 `name` 그룹 → `reportDate` 최신 1건 → 동일 날짜면 `correctionType` 있는 쪽 우선 |
| `#doc`(관련) | `#att`와 동일 필터 |
| 본문 tree | 변경 없음 |
| entry `rcept_no` | 목록 공시 접수번호 유지 |
| 첨부 URL/rcp | option의 `rcpNo`/`dcmNo`(선정된 최종본) |
| 날짜 없는 첨부 | 그룹에 날짜 있는 후보가 있으면 날짜 있는 최종본 우선. 전원 무날짜면 **DOM 순 첫 건** |
| 스키마/web-api | 필수 변경 없음 (collector가 list 기본값을 그대로 탐) |

## 3. 동작

### 3.1 목록

`list.js` `URLSearchParams`에서 `finalReport: 'recent'` 기본 제거.

```js
// 기본: finalReport 키 없음
// params.finalReport === 'recent' 이면만 추가
```

`fetchDisclosureList` / `fetchDisclosureListResult` / `collectEntries` 모두 동일 경로.

### 3.2 첨부 필터

`extractAttachments` 직후(또는 `dedupe` 전/후 명확한 한 지점)에:

1. `source === 'attachment'` 문서를 `name`으로 그룹
2. 그룹마다 비교키:
   - `reportDate`를 `YYYY.MM.DD` → 정렬 가능 값 (없으면 최하 우선순위)
   - `correctionType` 비어 있지 않으면 가산
3. 승자 1건만 남김. 그룹 간·본문 문서는 유지
4. 기존 `rcpNo_dcmNo` `dedupe`는 유지

필터는 `parseDetail`의 attachments 경로에만 적용. 본문 `toBodyDocuments`는 불변.

### 3.3 수집 결과 의미

- **이력 모드(기본):** 같은 회사·유형이라도 정정 전·후 `rcept_no`가 목록에 각각 등장 → 각각 entry 수집
- **각 접수 내부:** 첨부 이름당 최종본 1개만 leaf/fallback

## 4. 테스트

1. 목록 요청 URL에 기본으로 `finalReport` 없음. `finalReport: 'recent'` 옵션 시 포함
2. 첨부 fixture: 같은 name·다른 date/`[정정]` → 최신(또는 정정) 1건만 documents에 남음
3. 이름 다른 첨부 2종 → 둘 다 유지
4. README: 1단계 최종보고서 체크 해제·첨부 최종본 규칙 명시

## 5. 범위 밖

- 본문 treeData 안의 과거 dcmNo 재해석
- Admin UI에 finalReport 토글
- DB 마이그레이션 (재수집)

## 6. 성공 기준

- 기본 목록 수집이 정정 전 접수도 포함
- 한 상세의 `#att`에 감사보고서가 여러 줄이어도 entry는 **최종 1계통**만
- `npm test` 통과
