# 부채총계·계속기업·연결 종속기업 수 추출 설계

날짜: 2026-09-04  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` — 기존 감사 추출 잡이 같은 `audit_report_facts` 행에
부채총계, 당기 계속기업 중요한 불확실성(MU), 연결 종속기업 수를 붙인다.  
구현 계획이 아니라 **아키텍처·스키마·selector·파서 규칙·잡/API 계약·테스트 경계**다.

선행: [2026-08-28 표지·의견](2026-08-28-audit-opinion-extraction-design.md),
[2026-08-29 의견서 서식](2026-08-29-audit-opinion-letter-format-design.md),
[2026-09-02 계정 D-5](2026-09-02-audit-accounts-extraction-design.md),
[2026-09-03 내부회계 D-6](2026-09-03-audit-icfr-opinion-extraction-design.md),
[2026-09-04 유동 소계](2026-09-04-current-asset-liability-extraction-design.md).  
계속기업 서식: 한공회 「감사보고서 작성사례 개정」(2014.12, 종전 보론),
「2018년 감사보고서 작성사례」 별첨1·별첨2. 제목·창·키워드를 바꿀 때는
**해당 작성사례를 연 뒤에만** 적는다. 원문 파일을 저장하지 않는다.

[ypspy/dart-scraping](https://github.com/ypspy/dart-scraping)에는 세 필드 전용
스크립트가 없다. D-5-1의 `부채`는 재무상태표 **표 탐색**용이고 부채총계 칸이 아니다.
D-3-2는 적정/한정/거절/부적정만 본다. D-7은 정관 OCR(감사 vs 감사위원회)이다.
이번은 포팅이 아니라 **새 추출기**다.

이번 라운드는 DART facts만. 상장 배지·업종·FSS 감리·KIS 조인·D-7은 다음 스펙.

## 1. 목표

의견 추출 잡이 이미 의견서·재무상태표 HTML을 가져온다.
같은 잡·같은 행에 세 값을 붙인다.

- 부채총계: 기존 BS 파서에 계정 키 하나.
- 계속기업: 이미 가져온 의견서 HTML에서 의견 코드 창 **밖**을 읽는다.
- 종속기업 수: 연결 문서만 주석(없으면 제표 부모의 주석 이후)을 한 장 더 가져오고,
  실패 시에만 같은 접수 A001 계열회사 표를 한 장 더 가져온다.

새 잡·새 패키지·자식 테이블·HTML 저장은 없다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 산출 | 연구 CSV + Public API + `/facts`. 의견·D-4·D-5·D-6과 **같은 행** |
| 실행 | 기존 `POST /admin/extract/audit-opinion`. 새 `extractor_id` 없음 |
| 저장 단위 | 감사보고서 문서 (`rcept_no` + `dcm_no`) |
| 공시 유형 | F001, F002, A001 첨부 감사·연결감사. `is_audit_document` 변경 없음 |
| 부채총계 | `accounts` JSON `total_liability`. 당기·전기. 새 컬럼 없음 |
| 계속기업 | 당기 MU가 있으면 1 (적정 포함). 전기 인용만이면 0. 청산기준 강조사항만이면 0 |
| 종속 | 연결만 숫자. 주석 1차 → 같은 접수 A001 종속 구분 가능할 때만 2차. **종속기업만** |
| 별도 문서 | `fs_scope=separate` → `subsidiary_status=not_applicable`, 카운트 null (0 아님) |
| HTML | 저장하지 않음. 재추출은 URL을 다시 fetch |
| 패키지 | `packages/web-api` `app/extracting/` |
| 해소 | 형제 F001/A001 행과 금액을 맞추거나 `conflicts`에 넣지 않음 |
| 버전 | `extractor_version` = `audit_opinion.v16` |

카탈로그 수집과 추출 잡의 DART 상호 배타는 의견 추출과 같다.

## 3. 구조

```text
기존 Admin 추출 잡 (기간 + report_types)
  → Selector가 같은 dcm의 주석 leaf (연결만), 같은 접수 A001 계열회사 leaf
  → 부채: 이미 가져온 BS HTML → extract_accounts (키 추가)
  → GC: 이미 가져온 의견서 HTML → extract_going_concern (창 밖)
  → 종속: 연결만 주석 HTML fetch (0~1장). 실패 시 A001 1장
  → 같은 audit_report_facts 행 upsert
```

문서당 추가 HTTP는 종속만이다. 별도 문서는 0장, 연결은 주석 1장, 주석 실패·A001 있으면 최대 2장.

## 4. 데이터 모델

`ensure_schema`로 기존 SQLite/Postgres 행을 보강한다.

### 4.1 부채총계 (`accounts`)

`_ACCOUNTS`에 `total_liability`를 추가한다. JSON 스키마는 기존 계정과 같다.
`_TOTAL_ACCOUNTS`에 넣어 내역·합계가 둘 다 차면 합계 칸을 쓴다.
표를 읽었는데 행이 없으면 원소 `status=not_found`, `accounts_status`는 `ok`다.

`_account_of` compact (앞이 이김, 자본총계 다음):

| compact | `account` |
|---------|-----------|
| `부채총계` | `total_liability` |
| `부채와자본총계` / `부채및자본총계` | 매칭하지 않음 (자산총계와 같음) |
| `유동부채` (기존) | `current_liability` |

`유 동 부 채`는 기존 `compact`가 붙인다. `부채` 단독·`비유동부채`는 `total_liability`가 아니다.

### 4.2 계속기업

| 컬럼 | 내용 |
|------|------|
| `going_concern` | `1` 또는 `0`. skipped·예외면 null |
| `going_concern_status` | `ok` / `skipped` / `not_found`(예외만) |
| `going_concern_raw` | 매칭 제목 또는 근거 한 줄. 0이면 null |
| `going_concern_source` | `heading` / `eom` / `grounds`. 0이면 null |

의견 HTML을 읽었고 MU가 없으면 `0`이고 `status=ok`다.
MU 없음을 `not_found`로 두지 않는다. 의견 leaf가 없으면 `skipped`.
파서 예외만 행을 살리고 `going_concern=null`, `status=not_found`다.

변형 코드(한정 vs 거절)는 `opinion_code`에 있으므로 별도 컬럼이 없다.

### 4.3 종속기업 수

당기말 연결대상만. “N개” 문장은 쓰지 않는다. 명단 JSON은 저장하지 않는다.

| 컬럼 | 내용 |
|------|------|
| `subsidiary_count` | 정수. 해당없음·미발견이면 null (**0이 아님**). 표는 있고 본문 행이 0이면 **0** |
| `subsidiary_status` | `ok` / `not_found` / `skipped` / `not_applicable` |
| `subsidiary_source` | `notes` / `a001`. 숫자 없을 때 null |
| `notes_entry_id` | 고른 주석 leaf. 부모 주석 꼬리만 썼으면 부모 id, `fs_parent_entry_id`와 같을 수 있음 |
| `a001_affiliate_entry_id` | A001 계열회사 fallback leaf |

| 조건 | status | count |
|------|--------|-------|
| `fs_scope=separate` | `not_applicable` | null (fetch 없음) |
| 연결인데 주석·부모 꼬리·A001을 고르지 못함 | `skipped` | null |
| 가져왔으나 종속만 가를 수 없음 | `not_found` | null |
| 표를 세었음 (0행 포함) | `ok` | 정수 |

F001/F002 단독 접수에 A001이 없으면 주석 실패 후 `not_found`다.

## 5. 계속기업 파서

`classify_opinion`의 검색 창은 그대로다. 그 창은 `계속기업관련중요한불확실성` 등에서
잘라 **의견 코드**가 MU 문장에 오염되지 않게 한다. GC는 **같은 HTML의 compact 전체**에서
아래 구간만 본다. D-3 키워드 목록을 바꾸지 않는다.

### 5.1 제외 구간 (항상 0의 근거가 아님)

- 경영진·지배기구 책임, 감사인 책임 단락 (2018 이후 **모든** 의견서에
  `계속기업`과 `중요한 불확실성`이 있다).
- `기타사항` (전기 감사보고서 인용).
- 핵심감사사항이 GC 단락을 **가리키기만** 하는 문장
  (제목·강조사항·근거가 없을 때 1로 올리지 않음).

### 5.2 GC = 1 (당기 MU)

한공회 작성사례 변형. compact 매칭. 2018 `회계의계속기업전제`와 2014 `계속기업가정`을 모두 받는다.
첫 매칭이 이긴다.

| 우선 | 조건 | `source` | 사례 |
|------|------|----------|------|
| 1 | 제목 compact `계속기업관련중요한불확실성` | `heading` | 별첨1 5.1 적정 |
| 2 | `강조사항`/`특기사항` 본문에 계속기업(가정·전제)과 (`중요한불확실성` 또는 존속능력에 대한 유의적 의문) | `eom` | 2014 5.2 적정 |
| 3 | `한정의견근거` / `부적정의견근거` / `의견거절근거`에 같은 계속기업 MU·전제 부적합·평가 기피·평가 미실시 | `grounds` | 별첨1 5.3–5.8, 2014 2.3–2.4·3.2–3.3·4.4–4.5 |

적정이어도 1이다. 의견 코드는 바꾸지 않는다.

### 5.3 GC = 0

- 책임 문단만 있고 5.2가 없음.
- 소송 등 **다른** 강조사항의 `중요한불확실성` (계속기업 토큰 없음).
- **청산가치·청산기준** 강조사항만 있음 (계속기업전제를 버린 작성. 별첨1 5.2, 2014 5.5).
  그 강조사항에 `계속기업`이 있어도 `중요한불확실성`이 없으면 5.2의 `eom`으로 쓰지 않는다.
  같은 보고서에 MU 제목·근거가 따로 있으면 5.2가 이긴다.
- `기타사항`의 전기 계속기업 한정 인용만.

## 6. 종속기업 selector · 세기

연결(`fs_scope=consolidated`)만 고른다. 별도는 섹션 4.3.

### 6.1 주석 (1차)

같은 감사 `dcm_no`에서 compact 섹션명이 **정확히** `주석`인 leaf.
`재무상태표에대한주석`은 제외한다.

그 leaf가 없고 제표 부모(`(첨부)연결재무제표` 등)만 있으면 부모 HTML을 가져와
기존 `cut_notes`와 **같은 구분자** `주석 `의 **뒷부분**만 쓴다. 본표는 다시 세지 않는다.

주석 HTML에서 제목 compact에 `종속기업` 또는 `연결대상`이 있는 **첫 표**.
`관계기업`·`공동기업`·`특수관계자`만 있는 제목은 건너뛴다.

### 6.2 세기 (주석)

- 헤더·`합계`·`소계`·빈 이름 행 제외. 회사명처럼 보이는 본문 행.
- `구분`/`관계`/`기업구분` 칸이 있으면 compact에 `종속`이 있고 `관계`·`공동`이 없는 행만.
- 그런 칸이 없고 제목이 종속·연결대상이면 본문 행 전부.
- 특수관계자·계열 혼합인데 구분이 안 되면 그 표는 실패. 다음 후보 표, 없으면 1차 실패.
- 종속 표는 있는데 본문 행이 0이면 `0` + `ok`.

### 6.3 A001 (2차, 1차 실패만)

같은 `rcept_no`, `report_type=A001`, `source=body`, compact에 `계열회사`.
`타법인출자`는 쓰지 않는다.
`계열회사현황` / `계열회사의현황`이 있으면 부모 `계열회사등에관한사항`보다 앞.

**구분 칸에서 종속만 셀 수 있을 때만** 숫자를 남긴다. 칸이 없거나 값이 계열/관계뿐이면
`not_found`. 표 전체 행 수는 쓰지 않는다.

`subsidiary_source`: 1차 `notes`, 2차 `a001`.

## 7. 잡 · API

기존 `POST /admin/extract/audit-opinion`.
`EXTRACTOR_VERSION`을 `audit_opinion.v16`으로 올린다. v15 `ok` 행은 다음 `extract`에서
다시 돈다. override·LLM 보고일은 유지한다.

`reparse`의 not_found 필드에 `subsidiary_status`와 `going_concern_status`를 넣는다.
MU 없음은 `ok`+`0`이라 reparse에 안 걸린다. 파서 예외로만 `going_concern_status=not_found`가 된다.

주석·A001 fetch/파싱 실패는 의견 행을 버리지 않고 해당 필드만 `not_found`다.

`GET /api/v1/disclosures/{rcp_no}/audit-facts`, `GET /api/v1/facts`, HTML `/facts`,
연구 CSV에 4.1–4.3 필드를 노출한다. `date_resolver_*`는 숨긴다.
`AuditReportFactItem`에 컬럼을 명시하고, 목록은 모델 공개 컬럼 튜플을 따른다.

`field_partial` 핵심 필드에 `going_concern_status`를 넣는다.
`subsidiary_status`는 `skipped`·`not_found`만 부분실패다.
**`not_applicable`은 부분실패가 아니다** (별도 F001이 전부 `field_partial`이 되면 안 됨).

## 8. 테스트

실제 DART 호출 없음. 한공회 doc 원문은 저장하지 않는다. compact 가능한 한글 fixture.

- 부채: `부채총계` 당기·전기. `부채와자본총계` 비매칭. `유동부채`와 키 분리.
- GC: 2018 제목 → 1·`heading`. 2014 강조사항 → 1·`eom`. 한정·부적정·거절 근거 → 1·`grounds`.
  책임 문단만 → 0. 소송 강조사항만 → 0. 청산가치 강조사항만 → 0. 기타사항 전기 인용만 → 0.
- 종속: 주석 종속 표 행 수. 구분 칸 혼합표는 종속만. A001은 구분 가능할 때만.
  구분 없는 계열 표 → `not_found`. 별도 → `not_applicable`. 주석 실패 후 A001 성공 → `source=a001`.
  헤더만 있는 종속 표 → `0` + `ok`.
- selector: 정확 `주석`, `재무상태표에대한주석` 제외, 부모 주석 꼬리, A001 `계열회사`·`타법인출자` 제외.
- 기존 의견·D-4·D-5·D-6 테스트가 v16 upsert 후에도 깨지지 않음.

## 9. 범위 밖

- D-7 정관 OCR
- 카탈로그 상장 배지·업종, FSS 감리 리스트, KIS 조인
- 주석·계열 원표 JSON 덤프
- 관계기업·공동기업·기타 계열을 수에 포함
- 청산기준 강조사항을 GC=1로 두는 것
- GC 변형을 `opinion_code`와 별도 enum으로 저장
- 새 Admin 화면·새 추출 잡
- OpenDART 재무 API
- 별도/연결 금액 교차 conflict

## 10. 디렉터리 (web-api)

```text
app/extracting/accounts.py              # total_liability
app/extracting/going_concern.py         # extract_going_concern
app/extracting/subsidiaries.py          # extract_subsidiaries
app/extracting/selector.py              # notes_entry_id, a001_affiliate_entry_id
app/extracting/constants.py             # audit_opinion.v16
app/models/audit_report_fact.py         # GC·종속 컬럼
app/db/session.py                       # ensure_schema 패치
app/services/extraction_service.py      # fetch + 파서 연결, reparse
app/services/completeness_service.py    # field_partial (not_applicable 제외)
app/schemas/facts.py                    # Public 응답
tests/test_extracting_accounts.py
tests/test_extracting_going_concern.py
tests/test_extracting_subsidiaries.py
tests/test_extracting_selector.py
tests/test_extraction_service.py
tests/test_extract_admin_api.py         # field_partial
packages/web-api/README.md
```
