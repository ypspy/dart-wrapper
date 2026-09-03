# 내부회계관리제도 감사·검토 의견 추출 설계 (D-6)

날짜: 2026-09-03  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` — 감사보고서와 같은 dcm의 내부회계 leaf에서
감사·검토·해당없음과 의견 코드를 읽어 `audit_report_facts` 컬럼에 붙이고,
API·연구 CSV로 제공한다.  
구현 계획이 아니라 **아키텍처·스키마·selector·판별·파서 규칙·잡/API 계약·테스트 경계**다.

선행: [2026-08-28 표지·의견](2026-08-28-audit-opinion-extraction-design.md),
[2026-08-31 실시내용 D-4](2026-08-31-audit-activity-extraction-design.md),
[2026-09-02 계정 D-5](2026-09-02-audit-accounts-extraction-design.md).  
원전: [ypspy/dart-scraping](https://github.com/ypspy/dart-scraping) D-6-1 icReview.  
감사 서식: 감사기준서 1100 보론
[내부회계관리제도 감사보고서 사례](https://www.kifrs.com/s/1100/229ce2),
한공회 「연결내부회계관리제도 감사보고서 예시」.  
검토 서식: 한공회 「내부회계관리제도 검토기준」(공포용) 보론 2.  
규칙: 제목·키워드·판별 문구를 바꿀 때는 **해당 기준서·검토기준·옛 D-6-1을 연 뒤에만** 적는다.

이번 라운드는 D-6만. D-7(정관 OCR)은 다음 스펙.

## 1. 목표

의견 추출 잡이 이미 재무제표 의견서 HTML을 가져온다.
같은 잡에서 같은 감사 `dcm_no`의 내부회계 leaf를 한 장 더 가져와
engagement(감사 / 검토 / none)와 의견 코드를 컬럼으로 저장한다.
새 잡·새 패키지·자식 테이블은 없다.

회사의 `내부회계관리제도운영보고서`는 읽지 않는다. `is_audit_document` 제외는 그대로다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 산출 | 연구 CSV + Public API. 의견·D-4·D-5와 **같은 행** |
| 실행 | 기존 `POST /admin/extract/audit-opinion`. 새 `extractor_id` 없음 |
| 저장 단위 | 감사보고서 문서 (`rcept_no` + `dcm_no`) |
| 공시 유형 | F001, F002, A001 첨부 감사·연결감사. 운영보고서는 대상 아님 |
| 읽을 문서 | 같은 dcm의 내부회계 **leaf만**. 운영보고서 4절 fallback 없음 |
| 판별 | 재무제표 의견서 추가 문단 + leaf 본문. 의견 **코드는 leaf만** |
| 별도·연결 | **`fs_scope`에 맞춤**. 한 행에 두 세트 없음 |
| 감사 코드 | `unqualified` / `adverse` / `disclaimer`. 중요한 취약점은 **부적정** |
| 검토 코드 | `unqualified` / `qualified` / `disclaimer` / `material_weakness` |
| 기본 적정 | 서식인데 변형 키워드 없으면 `unqualified` (D-3와 같음) |
| HTML | 저장하지 않음. 재추출은 URL을 다시 fetch |
| 패키지 | `packages/web-api` `app/extracting/` |
| 파싱 | 내부회계 전용 순수 함수. D-3 `classify_opinion`에 분기를 섞지 않음 |
| 해소 | 별도/연결 형제 행과 의견을 맞추거나 `conflicts`에 넣지 않음 |
| 버전 | `extractor_version` = `audit_opinion.v14` |

원전 D-6-1은 책임 문단이 없으면 전부 검토로 넣고, 키워드가 여러 개면 **마지막**이 이겼다.
이번엔 세 갈래이고, 키워드는 **첫 매칭**이 이긴다.

## 3. 구조

```text
기존 Admin 추출 잡 (기간 + report_types)
  → Selector가 같은 dcm의 ICFR leaf 선정 (fs_scope 맞춤)
  → 이미 가져온 재무제표 의견서 HTML로 engagement 1차 판별
  → DartHttp로 내부회계 viewer_url fetch (leaf가 있을 때 1장)
  → extract_icfr(opinion_html, icfr_html, fs_scope)
  → 같은 audit_report_facts 행 upsert
```

카탈로그 수집과 추출 잡의 DART 상호 배타는 의견 추출과 같다.
문서마다 내부회계 HTML을 0~1장 더 가져온다.

## 4. 데이터 모델

`audit_report_facts`에 컬럼을 추가한다. `ensure_schema`로 기존 SQLite/Postgres 행을 보강한다.

| 컬럼 | 내용 |
|------|------|
| `icfr_entry_id` | 고른 내부회계 leaf. 없으면 null |
| `icfr_engagement` | `audit` / `review` / `none`. skipped면 null |
| `icfr_opinion_raw` | 매칭 제목 또는 키워드. 기본 적정이면 `boilerplate_unqualified` |
| `icfr_opinion_code` | 아래 코드. none·skipped면 null |
| `icfr_status` | `ok` / `skipped` / `not_found` |

감사 `icfr_opinion_code`: `unqualified` / `adverse` / `disclaimer`.  
검토 `icfr_opinion_code`: `unqualified` / `qualified` / `disclaimer` / `material_weakness`.

`none`일 때 `icfr_status=ok`, `icfr_opinion_code`는 null이다.
재무제표 의견서만 감사라 하고 leaf가 없으면 **skipped**다. engagement를 의견서만으로 채우지 않는다.

필드 상태는 의견·D-4와 같다. fetch·파싱 예외는 행을 버리지 않고 `icfr_status=not_found`.

## 5. Selector

`is_audit_document`는 그대로다. `LeafIds`에 `icfr_entry_id`를 추가한다. **같은 감사 `dcm_no`** 안에서만 고른다.

compact 섹션(앞이 이김):

| `fs_scope` | 매칭 |
|------------|------|
| `separate` | `내부회계관리제도`를 포함하고 `연결`이 없음. 예: `내부회계관리제도검토의견`, `내부회계관리제도감사또는검토의견` |
| `consolidated` | `연결내부회계관리제도`를 포함. 예: `연결내부회계관리제도감사또는검토의견` |
| `unknown` | 별도와 같다 (`연결` 없는 것) |

`주석` leaf는 고르지 않는다. 운영보고서 본문 절은 이 dcm이 아니므로 오지 않는다.

## 6. Engagement 판별

의견서·leaf 본문은 compact 문자열만 본다. 순서는 고정이다.

1. **감사 (의견서 추가 문단).**  
   `consolidated`이면 `연결내부회계관리제도를감사하였`.  
   `separate`/`unknown`이면 `내부회계관리제도를감사하였`이 있고
   `연결내부회계관리제도를감사하였`이 **없음**.  
   (`연결…를감사하였`은 `내부회계관리제도를감사하였`을 부분문자열로 포함한다.)
2. **검토 (leaf).** `내부회계관리제도검토보고서` 또는 `검토기준에따라검토`.
3. **감사 (leaf 백업).** `내부회계관리제도감사보고서` 또는 `내부회계관리제도를감사하였`.
4. **none.** 그 밖의 leaf.

leaf가 없으면 이 판별을 하지 않고 `skipped`다.

## 7. 파서

`_parse_amount`·D-3 `classify_opinion`은 그대로 둔다. `app/extracting/icfr.py`에서
leaf compact만 분류한다. 연결 서식 제목은 `연결` 접두가 있어도
`내부회계관리제도에대한감사의견` 등 **접미 제목**으로 맞는다.

### 7.1 감사 (`engagement=audit`)

제목(먼저 나온 것):

| compact 부분문자열 | 코드 |
|--------------------|------|
| `내부회계관리제도에대한의견거절` | `disclaimer` |
| `내부회계관리제도에대한부적정의견` | `adverse` |
| `내부회계관리제도에대한감사의견` | `unqualified` |

제목이 없으면 **근거·책임 앞**만 검색한다. 자르는 표지(먼저 나온 것):
`내부회계관리제도감사의견근거`, `내부회계관리제도부적정의견근거`,
`내부회계관리제도의견거절근거`, `내부회계관리제도에대한경영진과지배기구의책임`.
표지가 없으면 leaf 전체다.

구간 안에서 **첫 매칭**, 거절 → 부적정:

| 코드 | 키워드 |
|------|--------|
| `disclaimer` | `의견을표명하지`, `의견거절근거` |
| `adverse` | `효과적으로설계및운영되고있지`, `부적정의견근거` |

중요한 취약점 키워드는 감사 코드가 **아니다**. 부적정 근거에 취약점 서술이 있어도 제목·키워드가 부정이면 `adverse`다.

제목·키워드가 없으면 `unqualified`, `raw=boilerplate_unqualified`.

### 7.2 검토 (`engagement=review`)

책임 단락(`내부회계관리제도에대한경영진과지배기구의책임`)이 있으면 그 앞만.
없으면 leaf 전체. **첫 매칭**, 거절 → 한정 → 취약점:

| 코드 | 키워드 |
|------|--------|
| `disclaimer` | `검토의견을표명하지` |
| `qualified` | `미치는영향을제외하고는` |
| `material_weakness` | `중요한취약점이발견되었`, `중요한취약점이언급` |

`중요한취약점이발견되지`는 `발견되었`과 다르다. 표준보고
「중요한 취약점이 발견되지 아니하였」은 취약점이 아니다.

제목·키워드가 없으면 `unqualified`.

### 7.3 상태

| 조건 | `icfr_status` | engagement·code |
|------|---------------|-----------------|
| 감사 문서가 아니거나 내부회계 leaf를 고르지 못함 | `skipped` | 모두 null |
| leaf는 가져왔으나 none | `ok` | `none`, code null |
| 감사·검토 서식을 읽음 | `ok` | 코드 있음 |
| fetch·파싱 예외 | `not_found` | 모두 null |

## 8. 잡 · API

기존 `POST /admin/extract/audit-opinion`.
`EXTRACTOR_VERSION`을 `audit_opinion.v14`로 올린다. v13 `ok` 행은 다음 추출에서
내부회계 URL을 다시 가져온다.
`reparse`의 not_found 필드에 `icfr_status`를 포함한다.
override·LLM 보고일은 D-5와 같이 유지한다.

`GET /api/v1/disclosures/{rcp_no}/audit-facts`와 연구 CSV에
`icfr_engagement`·`icfr_opinion_code`·`icfr_status`·`icfr_entry_id`를 노출한다.

`field_partial` 핵심 필드에 `icfr_status`를 넣는다. leaf가 없는 문서(skipped)도
의견을 `ok`여도 `field_partial`이 될 수 있다.

## 9. 테스트

실제 DART 호출 없음. 한공회·기준서 원문 파일은 저장하지 않는다. compact 가능한 한글 fixture.

- 감사 적정·부적정·거절: 1100 보론 제목. 부적정 근거의 취약점 서술이 `material_weakness`가 되지 않음.
- 검토 표준: 「발견되지 아니하였」→ `unqualified`.
- 검토 한정: `미치는영향을제외하고는` → `qualified`.
- 검토 거절: `검토의견을표명하지` → `disclaimer`.
- 검토 취약점: `중요한취약점이발견되었` → `material_weakness`.
- 연결: 제목 `연결내부회계관리제도에대한감사의견`, 의견서 문단 `연결내부회계관리제도를감사하였`.
- 별도 의견서의 `내부회계관리제도를감사하였`이 연결 행을 audit으로 만들지 않음.
- leaf 없음 → `skipped`.
- leaf 자리만 있고 서식 아님 → `none`.
- `내부회계관리제도운영보고서`는 계속 `is_audit_document` False.
- 기존 의견·D-4·D-5 테스트가 v14 upsert 후에도 깨지지 않음.

## 10. 범위 밖

- D-7 정관·OCR
- `내부회계관리제도운영보고서` 본문·4절
- ICFR 보고일·감사인명
- 한 행에 별도+연결 두 세트
- D-3 `classify_opinion`에 내부회계 키워드를 섞는 것
- OpenDART

## 11. 디렉터리 (web-api)

```text
app/extracting/selector.py              # icfr_entry_id, fs_scope 맞춤
app/extracting/icfr.py                  # extract_icfr
app/extracting/constants.py             # audit_opinion.v14
app/models/audit_report_fact.py         # icfr 컬럼
app/db/session.py                       # ensure_schema 패치
app/services/extraction_service.py      # fetch + 파서 연결
app/services/completeness_service.py    # field_partial
app/schemas/facts.py                    # Public 응답
tests/test_extracting_icfr.py
tests/test_extracting_selector.py
tests/test_audit_report_fact_repository.py
tests/test_extraction_service.py
packages/web-api/README.md
```
