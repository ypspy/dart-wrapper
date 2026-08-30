# F001·F002 목록 감사인 최후 해소 설계

날짜: 2026-08-30  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` `resolve_auditor` — 표지·본문이 한자 상호라
`not_found`일 때 F001·F002 목록 `submitter` 이름으로만 채운다.  
선행: [2026-08-28 감사보고서 표지·의견 추출](2026-08-28-audit-opinion-extraction-design.md) §7 감사인 순위.  
원전: [ypspy/dart-scraping](https://github.com/ypspy/dart-scraping) D-2-2·D-3-1. 표지 마커는 한글 `회계법인`/`감사반` 그대로.

구현 계획이 아니라 **해소 순위, 저장, 재추출, 테스트 경계**다.

## 1. 문제

F002 대동시스템(`20160701000115`) 표지·서명란은 `宇理會計法人`이다.
D-2-2는 compact 텍스트에 한글 `회계법인`/`감사반`이 있을 때만 채택하고,
D-3-1 사전은 한글 `우리회계법인`만 본문에서 찾는다. 둘 다 `not_found`다.

같은 행의 목록 `submitter`는 `우리회계법인`이고 `auditor_listing`에 이미 들어가 있다.
해소는 listing을 무시하도록 되어 있어 `auditor_resolved`가 비고,
`auditor_status=not_found`다. 보고일·의견은 별개로 `ok`다.

옛 D-2-2도 한글 마커만 봤다. 표지 당기 파서는 `期`를 받지만 감사인 마커는
한자를 받지 않는다. 이번엔 마커를 늘리지 않고, 문서 출처가 없을 때만 목록명을 쓴다.

## 2. 전제

| 항목 | 결정 |
|------|------|
| 손대는 함수 | `resolve_auditor`와 그 테스트. `extract_cover_auditor`·`extract_body_auditor` 마커·사전은 그대로 |
| 스키마 | `audit_report_facts` 컬럼 추가 없음. 제출인 고유번호(`submitter_corp_code`) 없음 |
| F001·F002 listing | 표지·본문이 모두 `not_found`이고 `submitter`가 있을 때만 resolved. `auditor_source=listing` |
| A001 | 목록 `submitter`는 회사명이라 쓰지 않음. 「1. 외부감사에 관한 사항」 당기 칸은 기존 2순위 |
| conflict | listing을 문서 출처와 짝지어 conflict에 넣지 않음 |
| 버전 | `EXTRACTOR_VERSION`은 `audit_opinion.v3` 유지 |
| 재추출 | fetch가 `ok`이고 감사인만 `not_found`인 행은 `reparse`. `extract`는 같은 버전 `ok` 행을 건너뜀 |
| 한자 마커 | `會計法人`/`監査班`을 D-2-2에 추가하지 않음 |
| LLM | 감사인에 쓰지 않음 |

목록명은 현재 상호일 수 있다. 한글 표지가 있는 대다수 건은 1순위에서 끝나
listing이 본문을 덮지 않는다. 제출인 고유번호로 합병·분할을 추적하는 일은
다음 카탈로그 작업이다.

## 3. 해소 순위

`resolve_auditor` 시그니처는 유지한다. 호출자는 지금처럼 F001·F002만
`submitter`를 listing으로 넘긴다. 함수는 `report_type`이 F001·F002이고
앞 출처가 모두 없으며 listing이 비어 있지 않을 때만 4번을 탄다.

1. 표지 D-2-2 (`ok`)
2. A001만 「1. 외부감사에 관한 사항」 당기 칸 (`ok`)
3. 의견 본문 D-3-1 (`ok`)
4. F001·F002만 목록 `submitter` (비어 있지 않음). `normalize_firm_name` 적용

1~3이 하나라도 `ok`이면 4번은 타지 않는다. 4번이 이기면
`auditor_resolved`는 정규화한 listing, `auditor_source=listing`,
`auditor_status=ok`다. 표지·본문 원문 컬럼은 `None`이다.
`auditor_listing`은 기존처럼 F001·F002 `submitter`를 넣는다.

A001 당기 칸은 라벨 `감사인`만 보면 되고, 칸 값에 `회계법인`이 없어도 된다.
한자 상호가 칸에 있으면 2순위로 그대로 채택한다.

## 4. 재추출

버전을 올리지 않으므로 `extract`/`resume`은 대동시스템처럼
`fetch_status=ok`인 행을 건너뛴다. `reparse`는 필드 `not_found`가 있으면
다시 fetch한다. 감사인만 비어 있는 행이 대상이다.
override·LLM 날짜 보존은 기존 reparse 규칙을 따른다.

## 5. 테스트

live DART 없이 fixture.

| 케이스 | 기대 |
|--------|------|
| F002 표지·본문 `not_found`, listing `우리회계법인` | `resolved=우리회계법인`, `source=listing` |
| F001 동일 | 같음 |
| A001 listing이 회사명이어도 | listing을 resolved에 쓰지 않음. 표지 또는 a001 칸 |
| 한글 표지 `ok` + listing 다른 이름 | 표지. listing은 conflict에 없음 |
| 본문만 `ok` + listing | 본문 |

## 6. 밖

- D-2-2에 `會計法人`/`監査班` 추가
- 본문 사전 한자 표기·한→한글 변환
- 목록 제출인 `openCorpInfoNew` 고유번호 입수·저장
- `EXTRACTOR_VERSION` 변경
- Admin UI
- 감사인 LLM
