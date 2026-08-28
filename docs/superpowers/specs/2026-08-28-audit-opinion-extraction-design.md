# 감사보고서 표지·의견 추출 설계

날짜: 2026-08-28  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` — 카탈로그 `viewer_url`로 감사 표지·의견을 뽑아
구조화 필드를 저장하고, API·연구 CSV로 제공한다.  
구현 계획이 아니라 **아키텍처·스키마·selector·해소 규칙·잡/API 계약·테스트 경계**다.

선행: 카탈로그(entry 메타·주소만 저장)와 Viewer(조회 시 HTML fetch·blocks).  
원전: [ypspy/dart-scraping](https://github.com/ypspy/dart-scraping) D-2·D-3·D-1·E-2·E-3·G-1.  
규칙: 추출기 규칙·키워드·섹션 매칭을 바꿀 때는 **해당 옛 파일을 연 뒤에만** 적는다. 파일명만으로 추론하지 않는다.

## 1. 목표

과거에는 HTML을 받아 glob으로 돌렸다. 지금은 카탈로그에 주소만 있으므로, 대상 leaf의 `viewer_url`에 접근해 같은 정보를 뽑는다. 결과는 연구 패널과 Public API가 같은 테이블을 읽는다.

이번 묶음은 옛 D-2(표지 당기·감사인)와 D-3(의견 본문 감사인·의견·보고일·GAAP)이다. 공통 추출 프레임을 두고, 이후 D-4~D-7은 같은 틀에 추출기만 추가한다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 산출 | 연구 CSV + Public API (동일 저장 행) |
| 실행 시점 | 카탈로그가 있는 기간에 대한 **별도 추출 잡**. 수집과 동시에 HTML을 뽑지 않음 |
| 저장 단위 | 감사보고서 **문서** 하나 (`rcept_no` + `dcm_no`). 정정 전·후 접수는 각각 행. 기업·연도당 최종 1행으로 접지 않음 |
| 공시 유형 | F001, F002, A001 첨부 감사·연결감사. **추출기 하나, selector 셋** |
| 필드 | 감사인, 감사의견, 감사보고서일, GAAP, 표지 당기. 의견·GAAP는 원문+정규화 코드 |
| HTML | 저장하지 않음. 날짜 ambiguous용으로 **후보 날짜와 앞뒤 문장만** 저장 |
| 패키지 | `packages/web-api` (`app/extracting/` + 잡 서비스). 별도 패키지 없음 |
| 파싱 | 기존 `DartHttp` + `extract_blocks`. 옛 `MatrixGenerator`를 복제하지 않음 |
| Admin UI | 추출 히트맵·새 화면 없음. Admin API(잡·완전성 집계)·로그 |
| 최종 패널 뷰 | 없음. export 때 `correction_type`·접수일로 고름 |
| 회사명 | 목록명은 **그 공시 시점 상호**. `corp_code`당 이름이 여러 개인 것은 이력이지 오류가 아님 |

## 3. 구조

```text
Admin 추출 잡 (기간 + report_types)
  → Selector가 entries에서 대상 문서·leaf 선정
  → DartHttp로 viewer_url fetch (인코딩 자동)
  → extract_blocks → AuditOpinionExtractor
  → 값 해소(우선순위·교차검증) → audit_report_facts upsert

Admin 날짜 해소 잡
  → status=ambiguous 행만
  → 저장된 후보+문장으로 LLM이 인덱스 선택
  → 날짜 컬럼·source=llm 갱신

Admin GET 완전성
  → 기간·유형별 대상/성공/실패/미추출/ambiguous 건수
  → 상태별 문서 목록(cursor)

Public GET / CSV는 audit_report_facts (+ entries 조인)만 읽음
```

카탈로그 수집과 추출 잡은 DART를 쓰므로 **한 프로세스에서 둘 중 하나만** 실행한다. 날짜 해소 잡은 DART를 치지 않으므로 수집과 병행할 수 있다.

식별자(`rcept_no`, `dcm_no`, `corp_code`)는 카탈로그만 쓴다. 회사명·결산월 문자열로 조인하지 않는다.

## 4. 데이터 모델

### 4.1 `audit_report_facts`

한 행 = 감사보고서 문서 하나. 카탈로그의 회사명·접수일 등은 넣지 않고 export·API가 `entries`/`disclosures`와 조인한다. 다만 해소·검증에 쓴 스냅샷은 아래 추출 컬럼과 `conflicts`에 남긴다.

| 그룹 | 컬럼 |
|------|------|
| 키 | `rcept_no`, `dcm_no`, `source_report_type` (A001/F001/F002), `fs_scope` (separate/consolidated/unknown) |
| 출처 entry | `cover_entry_id`, `opinion_entry_id`, `a001_opinion_entry_id`, `a001_cover_entry_id` (없으면 null) |
| 감사인 | `auditor`, `auditor_status`, `auditor_resolved`, `auditor_source` |
| 의견 | `opinion_raw`, `opinion_code`, `opinion_status`, `opinion_resolved`, `opinion_source` |
| 보고일 | `audit_report_date_raw`(후보 연결 문자열), `audit_report_date_candidates`(JSON: `{date, snippet}[]`), `audit_report_date`(ISO 또는 null), `audit_report_date_status`, `audit_report_date_source`, `audit_report_date_override` |
| GAAP | `gaap_raw`, `gaap_code`, `gaap_status`, `gaap_resolved`, `gaap_source` |
| 당기 | `current_period_raw`, `current_period_status`, `current_period_resolved`, `current_period_source` |
| 문서 | `fetch_status`, `conflicts`(JSON), `extracted_at`, `extractor_version` |
| LLM | `date_resolver_model`, `date_resolver_prompt_version`, `date_resolver_raw_response` (해소 잡이 채움) |

`fetch_status`: `ok` / `fetch_failed` / `blocked` / `section_missing`.  
`ok`여도 개별 필드는 비어 있을 수 있다.

필드 상태: `ok` / `not_found` / `ambiguous` / `normalize_failed` / `skipped`.  
`normalize_failed`이면 원문은 두고 코드는 `other`.

의견 코드: `unqualified`(적정) / `qualified`(한정) / `adverse`(부적정) / `disclaimer`(의견거절) / `other`.  
GAAP 코드: `k-gaap`(일반기업회계기준) / `k-ifrs`(한국채택국제회계기준) / `other`(공공·지방공기업·예외 등). 옛 D-3-4에 없는 별도 `ifrs`(풀 IFRS) 코드는 두지 않는다.

`fs_scope`: F001 → separate, F002 → consolidated, A001은 `document_name`이 `연결감사보고서`이면 consolidated, `감사보고서`이면 separate.

### 4.2 작업 테이블

`extraction_jobs` + `extraction_job_logs`. 카탈로그 잡 테이블과 분리한다.  
`extractor_id`: `audit_opinion` 또는 `resolve_dates`.  
일자 슬라이스 테이블은 없다. 재개 대상은 기간 안 문서 중 행이 없거나 `fetch_status`가 재시도 대상인 것이다.  
`reparse` 모드는 필드 `not_found`를 다시 fetch한다. HTML을 안 남기므로 재파싱도 URL을 다시 가져온다.

## 5. Selector

비교 시 공백을 제거한다. 카탈로그 실제 `section_name`(약 650만 entry 집계)과 옛 glob을 대응한다.

### 5.1 대상 문서

| 옛 대상 | 카탈로그 조건 |
|---------|----------------|
| F001/F002 | `report_type` ∈ {F001, F002} |
| A001 첨부 감사 | `report_type=A001`, `source=attachment`, `document_name` compact ∈ {`감사보고서`, `연결감사보고서`} |

제외: `내부회계*`, `내부감시장치*`, `감사의감사보고서`(법정 감사 의견서, 외부감사인 의견이 아님).

### 5.2 문서 안 leaf

| 역할 | 옛 glob | `section_name` |
|------|---------|----------------|
| 감사 표지 | D-2 `*감사보고서_감사보고서*` | 해당 문서의 `감사보고서`. `독립된 감사인의 감사보고서` 제외 |
| 의견 본문 | D-3 `*감사인의감사보고서*` | `독립된 감사인의 감사보고서` 또는 `외부감사인의 감사보고서` |
| A001 본문 의견 공시 | D-3에 없음. 이번에 추가 | `1. 외부감사에 관한 사항` 우선. 없으면 `V. 감사인의 감사의견 등` / `V. 회계감사인의 감사의견 등` / `IV. 감사인의 감사의견 등` |
| A001 사업 표지 | D-1 `*사업보고서_사업보고서*` | `source=body`, `document_name=사업보고서`, `section_name` compact = `사업보고서` (회사명·기간 검증) |

제외: `2. 감사제도에 관한 사항`(내부 감사제도), `내부회계관리제도 감사 또는 검토의견`.

표지·의견 leaf가 둘 다 있으면 둘 다 fetch한다. 의견만 있으면 표지 필드는 `skipped`.

## 6. 파서 (옛 코드 대응)

Viewer `extract_blocks` 이후 순수 함수로 나눈다. 하드코딩 경로·복제된 `FindTargetTable`/`Indexing`(D-4용)은 가져오지 않는다.

### 6.1 표지 (D-2-1, D-2-2)

- 당기: 표 텍스트에서 `기`/`期` 뒤 구간. 상태 `not_found` 가능.
- 감사인: `회계법인` 또는 `감사반`이 들어 있는 `p`/`td` 텍스트(D-2-2).

### 6.2 의견 본문 (D-3-2, D-3-3, D-3-4, D-3-1)

**의견.** 변형이 표준 서식의 예외라는 전제(D-3-2, KICPA 사례 주석)를 유지한다.

1. 의견 본문 entry를 가져왔고 서식처럼 보이면(섹션 선정, 그리고 공백 제거 본문이 200자 이상이거나 ‘감사의견’ 포함)  
   거절·한정·부적정 키워드(D-3-2 `keyWord1..3`)가 있으면 그 코드, **없으면 `unqualified`**. 상태 `ok`.  
   `opinion_raw`는 매칭 문구 또는 `boilerplate_unqualified`.
2. 섹션 없음·fetch 실패·서식이 아니면 `not_found`. 적정을 넣지 않는다.

키워드 목록은 D-3-2 원문을 구현 시 그대로 옮긴 뒤, 공백 제거한 본문에 적용한다.

**GAAP.** D-3-4 문구 목록. 매칭 없으면 코드 `other`(옛 출력 `예외`). 적정 기본값 논리와 섞지 않는다. D-3-4가 같은 파일에서 의견도 다시 뽑지만, 의견은 D-3-2 규칙만 쓴다.

**날짜.** D-3-3처럼 `[0-9]{4}년[0-9]{1,2}월[0-9]{1,2}일`을 모두 찾는다. 본문에서 `의견근거` 앞과 `재무제표에대한경` 이후를 잇는 전처리는 D-3-3과 같다. 모든 매칭을 `audit_report_date_candidates`에 `{date, snippet}`로 저장한다.

자동 선택(창을 통과한 날짜):

- 회계기간 종료일 이후
- `rcept_dt` 이전(당일 허용)
- 문서 후반(의견·서명란)을 앞선 본문 날짜보다 우선

통과분이 1개면 ISO로 넣고 `ok`. 0개면 `not_found`. **2개 이상이면 `ambiguous`이고 하나를 고르지 않는다.**  
옛 G-1은 Excel(`wp01.data.reportdate.xlsx`)에서 `drop` 후 `LAG`를 썼다. 저장소에 수동 선택 스크립트는 없다. 그 단계는 ambiguous → LLM 해소 잡이 대신한다.

**본문 감사인.** D-3-1: 감사인명 사전(`data01.auditor.txt` / `wp01.data02_auditor.txt`)과 본문 매칭, 문서상 **가장 뒤에 나온** 이름. 1순위가 아니다(§7).

### 6.3 A001 `1. 외부감사에 관한 사항`

표의 **당기** 칸에서 감사의견·감사인을 읽는다. 여기에는 적정 boilerplate 기본값을 쓰지 않는다. 칸이 비면 `not_found`.

## 7. 값 해소

옛 E-2는 표지 감사인과 본문 감사인을 나란히 merge만 했다. 이번엔 후보를 비교하고 순위로 고르며, 불일치는 `conflicts`에 남긴다. 정규화(공백, `주식회사`, 날짜 형식) 후 비교한다.

| 필드 | 우선순위 (앞이 이김) | 검증 |
|------|----------------------|------|
| 감사인 | ① 감사 표지 회계법인/감사반 ② F001·F002만 목록 `submitter` ③ 의견 본문 D-3-1 | A001 `submitter`는 회사명이므로 감사인에 쓰지 않음 |
| 당기·결산월 | ① 목록 `year_end` ② A001 사업 표지 기간(D-1) ③ 감사 표지 당기 | ②·③은 ①을 확인만 함. 조인 키 `year_end`는 자동 변경하지 않음 |
| 회사명 | 그 접수의 목록 `corp_name` | 사업 표지 `회사명`과 **같은 `rcept_no`만** 비교. 연도가 다른 행의 이름 차이는 conflict가 아님. 불일치 시 목록명 유지 |
| 감사의견 | ① 첨부/단독 의견 본문(D-3-2) ② A001만 `1. 외부감사에 관한 사항` 당기 칸 | ②는 요약이라 약칭·전기 칸이 섞일 수 있음. 불일치 시 ①. ① 없고 ②만 있으면 ② |
| GAAP | 의견 본문(D-3-4) | 같은 `corp_code`+`year_end`+`fs_scope`의 F001/F002/A001 첨부 행과 비교 |
| 감사보고서일 | 의견 본문 후보 중 창을 통과한 값. ambiguous는 LLM 또는 override | 목록 `rcept_dt`로 바꾸지 않음 |

교차 행: 같은 `corp_code`+`year_end`+`fs_scope`에서 A001 첨부와 F001/F002가 겹치면 **전용 공시(F001/F002)가 A001 첨부보다 앞**이다. 행은 둘 다 둔다. 추출 upsert 때 이미 있는 형제 행과 비교하고, 나중에 들어온 쪽도 양쪽 `conflicts`를 갱신한다.

수동 수정 UI는 없다. `audit_report_date_override`와 `reparse`로 다시 해소한다.

## 8. 잡 · API

### 8.1 추출

`POST /admin/extract/audit-opinion`  
본문: `start_date`, `end_date`, `report_types` (`A001`/`F001`/`F002` 부분집합).  
재개: 행 없음 또는 `fetch_status` ∈ {`fetch_failed`, `blocked`, `section_missing`}.  
`reparse`: 필드 `not_found`를 다시 fetch.

### 8.2 날짜 LLM 해소

`POST /admin/extract/resolve-dates`  
대상: `audit_report_date_status=ambiguous`.  
LLM은 후보 **인덱스** 또는 고를 수 없음만 답한다. 새 날짜를 만들지 않는다.  
temperature는 0에 가깝게. 모델·프롬프트 버전·원문 응답을 행에 저장.  
설정: `DATE_RESOLVER_*` (API 키, 모델명). 어댑터 포트로 감싸 테스트에서 mock한다.

### 8.3 조회

- `GET /api/v1/disclosures/{rcp_no}/audit-facts` — 해당 접수 문서 행(해소 값·출처·conflicts)
- Admin `PATCH` — `audit_report_date_override`
- 연구 CSV: `entries`와 조인하는 스크립트. 최종 접수만 필터하는 DB 뷰는 없음

### 8.4 추출 완전성 (히트맵 대신)

일별 칸 UI는 없다. 마커는 **상태 코드와 집계 API**다.

`GET /admin/extract/audit-opinion/completeness`  
쿼리: `start_date`, `end_date`, `report_type`(한 유형).

집계(문서 = `rcept_no`+`dcm_no`, selector 대상 기준):

| 키 | 의미 |
|----|------|
| `target` | 카탈로그에서 selector가 고른 문서 수 |
| `ok` | `fetch_status=ok` |
| `fetch_failed` / `blocked` / `section_missing` | 해당 `fetch_status` 행 |
| `unextracted` | 대상인데 facts 행이 없음 |
| `ambiguous_dates` | `audit_report_date_status=ambiguous` |
| `field_partial` | `fetch_status=ok`이지만 핵심 필드 중 하나라도 `ok`가 아님 |

같은 경로에 `status`(`unextracted`/`fetch_failed`/`blocked`/`section_missing`/`ambiguous_dates`/`field_partial`)와 `cursor`/`limit`을 주면 해당 문서 식별자 목록을 돌려 재개·reparse 대상과 이어 준다.

## 9. 에러 · 동시성

- DART 일시 오류: 카탈로그와 같은 재시도·차단 연속 중단.
- 필드 실패는 행을 버리기 않고 상태 코드로 남긴다.
- 카탈로그 수집 vs 추출: 상호 배타. 날짜 해소는 DART 없음 → 수집과 병행 가능.
- LLM 실패·거절: 날짜는 `ambiguous` 유지.

## 10. 테스트

실제 DART·LLM 호출 없음 (기존 web-api와 같이 MockTransport·mock 어댑터).

- selector: 위 섹션명 fixture (F001 `감사보고서`/`독립된 감사인의 감사보고서`, A001 첨부·`1. 외부감사에 관한 사항`, 제외 목록)
- 의견 키워드: D-3-2 fixture. 서식+키워드 없음 → `unqualified`. 서식 아님 → `not_found`
- GAAP: D-3-4 문구 → `k-gaap`/`k-ifrs`/`other`
- 날짜 창: 1개 통과 / 0개 / 2개 이상(`ambiguous`)
- 감사인: A001에서 `submitter` 미사용. 표지가 본문·목록보다 앞
- 회사명: 같은 접수만 비교. 다른 연도 이름 차이는 conflict 아님
- LLM mock: 인덱스 응답으로 날짜 채움. 범위 밖 인덱스는 `ambiguous` 유지
- 완전성 API: fixture 카탈로그+facts로 `target`/`ok`/`unextracted`/`ambiguous_dates` 건수

## 11. 범위 밖

- D-4 실시내용·D-5 계정·D-6 내부통제·D-7 지배구조
- 원문 HTML 저장, 추출 일별 히트맵 UI, 기업명 마스터 테이블
- Excel식 날짜 선택 화면
- 최종 접수만 남기는 패널 뷰
- 추출 전용 Python 패키지 분리

## 12. 디렉터리 (web-api)

```text
app/extracting/          # selector, audit_opinion 파서, 정규화, 해소
app/services/extraction_service.py
app/services/date_resolver_service.py
app/models/audit_report_fact.py
app/models/extraction_job.py
app/api/admin/extract.py
app/api/v1/facts.py
app/ports/date_resolver.py
app/adapters/llm_date_resolver.py
scripts/export_audit_report_facts.py
```
