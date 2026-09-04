# 첨부 재무제표 계정 추출 설계 (D-5)

날짜: 2026-09-02  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` — 감사보고서 첨부 제표 HTML에서 E-4 연구 계정
(당기·전기)을 읽어 `audit_report_facts`에 붙이고, API·연구 CSV로 제공한다.  
구현 계획이 아니라 **아키텍처·스키마·selector·파서 규칙·잡/API 계약·테스트 경계**다.

선행: [2026-08-28 표지·의견](2026-08-28-audit-opinion-extraction-design.md),
[2026-08-31 실시내용 D-4](2026-08-31-audit-activity-extraction-design.md).  
스크래핑 원전: [ypspy/dart-scraping](https://github.com/ypspy/dart-scraping)
D-5-1 자산총계 · D-5-2 당기순손익 · D-5-3 재고,
[E-4 연구 병합](https://github.com/ypspy/dart-scraping/blob/master/(E-4)%20mergeCSV_financials)
(자본총계·매출채권·장기매출채권·계약자산·미청구공사).  
규칙: 계정 라벨·제외 키워드를 바꿀 때는 **해당 옛 파일을 연 뒤에만** 적는다.
칸 인덱스(`len % 2`)와 `FindTargetTable`(td>20)은 이식하지 않는다.

이번 라운드는 D-5만. D-6(내부통제)·D-7(정관 OCR)은 다음 스펙.

## 1. 목표

의견 추출 잡이 이미 감사 문서(`rcept_no`+`dcm_no`)를 순회한다.
같은 잡에서 첨부 재무상태표·손익계산서 `viewer_url`을 더 가져와
연구에 쓰는 여덟 계정의 당기·전기 금액을 JSON으로 저장한다.
새 잡·새 패키지·계정 자식 테이블은 없다.

원전은 첨부 파일 전체를 연 뒤 `주석 ` 앞에서 잘랐다.
카탈로그에는 옛 TOC의 제표 leaf와, 신형 TOC의 부모 `(첨부)재무제표`(아래 leaf가 `주석`뿐)가 공존한다.
있는 leaf를 쓰고, 없으면 부모 HTML을 원전처럼 자른다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 산출 | 연구 CSV + Public API. 의견·D-4와 **같은 행** |
| 실행 | 기존 `POST /admin/extract/audit-opinion`. 새 `extractor_id` 없음 |
| 저장 단위 | 감사보고서 문서 (`rcept_no` + `dcm_no`) |
| 공시 유형 | F001, F002, A001 첨부 감사·연결감사. `is_audit_document` 변경 없음 |
| 계정 | E-4 세트: 자산총계, 자본총계, 당기순손익, 재고, 매출채권, 장기매출채권, 계약자산, 미청구공사 |
| 기간 | 당기 **그리고** 전기. 전기 열이 없으면 `prior` 원소를 만들지 않음 |
| 단위 | `raw` + 공시단위 `value` + `unit_raw`/`unit_scale` + `value_won` (`value * unit_scale`) |
| JSON | 본표 전 행 덤프가 아니라 **계정×기간 레코드** |
| HTML | 저장하지 않음. 재추출은 URL을 다시 fetch |
| 패키지 | `packages/web-api` `app/extracting/` |
| 파싱 | `expand_table_matrix` + 헤더 열 역할. Viewer `_parse_table`은 그대로 |
| 해소 | 형제 F001/A001 행과 금액을 맞추거나 `conflicts`에 넣지 않음 |
| 버전 | `extractor_version` = `audit_opinion.v11` |

## 3. 구조

```text
기존 Admin 추출 잡 (기간 + report_types)
  → Selector가 같은 dcm의 BS/IS leaf (없으면 제표 부모) 선정
  → DartHttp로 viewer_url fetch (1~2장, 실시내용과 별도)
  → extract_accounts(bs_html, is_html, unit from each statement)
  → 같은 audit_report_facts 행 upsert
```

카탈로그 수집과 추출 잡의 DART 상호 배타는 의견 추출과 같다.
문서마다 제표 HTML을 1~2장 더 가져온다.

## 4. 데이터 모델

`audit_report_facts`에 컬럼을 추가한다. `ensure_schema`로 기존 SQLite/Postgres 행을 보강한다.

| 컬럼 | 내용 |
|------|------|
| `accounts` | JSON 배열. 기본 `[]` |
| `accounts_status` | `ok` / `not_found` / `skipped` |
| `bs_entry_id` | 고른 재무상태표(연결 포함) entry. 없으면 null |
| `is_entry_id` | 고른 손익·포괄손익 entry. 없으면 null |
| `fs_parent_entry_id` | leaf가 없어 쓴 `(첨부)(연결)재무제표` 부모. leaf를 썼으면 null |

필드 상태는 의견·D-4와 같다. 칸 일부만 라벨이 없어도 표를 읽었으면 `accounts_status=ok`이고 그 계정 원소는 `status=not_found`다.

### 4.1 `accounts` 원소

```json
{
  "account": "inventory",
  "account_raw": "재고자산",
  "period": "current",
  "period_raw": "제 9 (당)기",
  "raw": "27,435,697,146",
  "value": 27435697146,
  "unit_raw": "원",
  "unit_scale": 1,
  "value_won": 27435697146,
  "status": "ok"
}
```

`period`: 헤더 compact에 `당기` 또는 `(당)기` → `current`, `전기` 또는 `(전)기` → `prior`.
비교 열이 없으면 current만 둔다. `period=unknown`은 쓰지 않는다.

`value`: 쉼표·공백 제거 정수. 괄호 또는 선행 `△`/`-`(숫자 앞)는 음수. `=`는 버린다.
금액 칸이 `-` 또는 `－`이면 `value=0`, `value_won=0`, `raw`는 유지한다.
단위를 못 읽으면 `unit_scale`·`value_won`은 null이다. `value_won = value * unit_scale`.

라벨 행이 표에 없으면 그 계정×있는 기간 원소를 넣되 `status=not_found`, `value`/`value_won`/`raw`는 null.
`account_raw`는 null.

`account` (compact, 앞이 이김):

| compact | `account` |
|---------|-----------|
| `자산총계` | `total_asset` |
| `자본총계` | `total_equity` (`부채와자본총계`·`부채및자본총계`는 아님) |
| `당기순` 이면서 제외 키워드 없음 | `net_income` |
| `재고` 이면서 `충당` 없음 | `inventory` |
| `장기매출` 또는 `장기성매출` | `long_term_receivable` |
| `매출채` 또는 `매출금` (장기 제외) | `receivable` |
| `계약자산` | `contract_asset` |
| `미청구공사` | `unbilled` |

`net_income` 제외 compact: `계속`·`중단`·`귀속`·`미처분`·`미처리`·`처분전`·`지배`·`비지배`·`관계`·`공동`·`차감전`·`이익잉여금`·`총포괄`.
원전 D-5-2 `matchesNeg`에 `총포괄`을 더한다(포괄손익계산서 합계 행을 당기순으로 쓰지 않기 위함).

같은 계정이 두 행이면 **앞 행**이 이긴다. 코우산업 `(2) 재고자산` 합계 행이 자식 상품·제품보다 앞이면 그 합계를 쓴다.

## 5. Selector

`is_audit_document`는 그대로다. `LeafIds`에 제표 id를 추가한다. **같은 감사 `dcm_no`** 안에서만 고른다.

compact 섹션(앞이 이김):

| 역할 | 매칭 |
|------|------|
| BS | `연결재무상태표` 또는 (연결이 아니고) `재무상태표` |
| IS | `연결손익계산서` 또는 `손익계산서`. 없으면 `연결포괄손익계산서` 또는 `포괄손익계산서` |
| 부모 | BS·IS leaf가 **둘 다** 없을 때만. `첨부재무제표`를 compact에 포함 (`(첨부)재무제표`, `(첨부)연결재무제표`) |

`재무상태표등`처럼 `재무상태표`를 포함하면 BS로 본다.
`주석` leaf는 제표가 아니다.
자본변동표·현금흐름표는 고르지 않는다.

부모 HTML은 원전처럼 본문을 `주석` 앞에서 자른 뒤 BS·IS 표를 찾는다.
leaf를 썼으면 부모를 fetch하지 않는다.

## 6. 파서

### 6.1 표

제목(`p`/heading) compact가 `재무상태표`(연결 포함)이면 그 **다음** 첫 의미 표(열 3개 이상).
없으면 펼친 격자에 `부채`가 있는 첫 표, 그것도 없으면 `자산총계`가 있는 표.

IS는 제목 `손익계산서`/`포괄손익계산서`(연결 포함) 다음 표.
없으면 compact에 `당기순`이 있고 `미처분`·`미처리`·`이익잉여금`이 없는 첫 표(자본변동표 제외).

### 6.2 단위

해당 제표 HTML에서 표 **앞** `p`/`td` compact에 `단위`가 있는 첫 줄.
`원` → 1, `천원` → 1000, `백만원` → 1_000_000. 그 밖은 null.
BS와 IS를 따로 읽어 계정별로 그 표의 단위를 붙인다.

### 6.3 열 역할 (실측 3갈래)

헤더 행: compact `과목`이 있거나 `당기`/`전기`/`제`+`기`가 있는 첫 행.

- `주석` 또는 `주기` → `note` (금액 아님)
- `당기` 또는 `(당)기` → current 그룹
- `전기` 또는 `(전)기` → prior 그룹

실측:

| 갈래 | 열 | 사례 |
|------|----|------|
| 5칸 | 과목 \| 당기내역 \| 당기합계 \| 전기내역 \| 전기합계 | 이케이에프, 해피투모로우, 골든트리, 코우. 주석은 과목 `(주석 3)` |
| 6칸 | 과목 \| 주석 \| 당기내역 \| 당기합계 \| 전기내역 \| 전기합계 | 범한메카텍, 화일약품 |
| 4칸 | 과목 \| 주석 \| 당기 \| 전기 | 상미식품, 한화손해보험. 기간당 금액 한 칸 |

기간 그룹 칸이 하나면 그 칸이 금액이다. **둘**이면 왼쪽=내역(개별), 오른쪽=합계(합산).
헤더가 같은 기간명으로 colspan 복제된 경우가 5·6칸이다.

### 6.4 행 금액

이름 칸은 비어 있지 않은 셀을 compact로 이어 라벨로 쓴다. `note` 칸은 라벨·금액이 아니다.

그 기간의 금액 칸 중 **비어 있지 않은 쪽**을 쓴다. 둘 다 차 있으면
`total_asset`/`total_equity`/`net_income`은 합계 칸, 나머지 계정은 내역 칸.
실측 샘플은 한 칸만 차 있었다.

- 짝 칸 **공란** → 무시. 0이 아니다 (유동자산 합계의 내역 칸, 현금의 합계 칸, 총계 행의 주석).
- 금액 칸 `-`/`－` → `value=0` (한화 보험계약자산 당기, 화일 당기법인세자산).
- 기간 금액 칸이 모두 비면 그 기간 원소를 만들지 않는다.

### 6.5 상태

| 조건 | `accounts_status` |
|------|-------------------|
| 감사 문서가 아니거나 제표 URL을 고르지 못함 | `skipped`, `accounts=[]` |
| HTML은 가져왔으나 BS·IS 표를 못 찾음 (의견거절 등) | `not_found`, `accounts=[]` |
| 표를 하나라도 읽음 | `ok` |

파싱 예외는 행을 버리지 않고 이 필드만 `not_found`다.

## 7. 잡 · API

기존 `POST /admin/extract/audit-opinion`.
`EXTRACTOR_VERSION`을 `audit_opinion.v11`로 올린다. v10 `ok` 행은 다음 추출에서 제표 URL을 다시 가져온다.
`reparse`의 not_found 필드에 `accounts_status`를 포함한다.
override·LLM 보고일은 D-4와 같이 유지한다.

`GET /api/v1/disclosures/{rcp_no}/audit-facts`와 연구 CSV에 `accounts`·`accounts_status`와 제표 entry id를 노출한다.

`field_partial` 핵심 필드에 `accounts_status`를 넣는다. 제표가 없는 문서·계정만 비어도(표를 못 읽으면) 의견이 `ok`여도 `field_partial`이 될 수 있다.
제표 leaf가 없어 부모가 있고 표를 읽으면 `ok`다.

## 8. 테스트

실제 DART 호출 없음. HTML fixture (실측 8건에서 축약한 표).

- 5칸: 현금은 내역 칸, 자산총계·유동자산은 합계 칸. 내역 공란을 0으로 읽지 않음.
- 6칸: 주석 열을 금액으로 쓰지 않음. 재고·매출채권은 내역, 자산총계·자본총계·당기순은 합계.
- 4칸: 과목\|주석\|당기\|전기. 자산총계 주석 공란 무시. `-` 금액 → 0.
- 단위 `천원` → `unit_scale=1000`, `value_won=value*1000`.
- 재고 라벨 없음 → `inventory` 원소 `status=not_found`.
- `부채및자본총계`를 `total_equity`로 쓰지 않음.
- 자본변동표만 있는 HTML에서 `net_income`을 읽지 않음.
- selector: `연결재무상태표` leaf, 부모 `(첨부)연결재무제표` fallback, `주석`만 있는 트리는 부모를 씀.
- leaf 없음 → `accounts_status=skipped`.
- 기존 의견·D-4 테스트가 v11 upsert 후에도 깨지지 않음.

## 9. 범위 밖

- D-6 내부회계 의견, D-7 정관·OCR
- BS·IS·CI·CF·자본변동 전 행 덤프
- OpenDART 재무 API
- 원 환산만 저장하고 `value`/`unit_scale`을 버리는 것
- 별도/연결 금액 교차 conflict
- 제표 전용 Admin 화면·잡

## 10. 디렉터리 (web-api)

```text
app/extracting/selector.py              # BS/IS/부모 LeafIds
app/extracting/accounts.py              # extract_accounts
app/extracting/constants.py             # audit_opinion.v11
app/models/audit_report_fact.py         # accounts 컬럼
app/db/session.py                       # ensure_schema 패치
app/services/extraction_service.py      # fetch + 파서 연결
app/services/completeness_service.py    # field_partial
app/schemas/facts.py                    # Public 응답
```
