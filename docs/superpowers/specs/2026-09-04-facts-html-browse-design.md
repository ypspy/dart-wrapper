# 감사 추출 결과 HTML 탐색 (문서 단위 납작 표) 설계

날짜: 2026-09-04  
상태: 승인 (구현)  
범위: `packages/web-api` — Public HTML `/facts`와 JSON 목록 `GET /api/v1/facts`  
선행: [Catalog HTML 탐색](2026-07-27-catalog-html-explore-design.md), [감사보고서 표지·의견 추출](2026-08-28-audit-opinion-extraction-design.md)

## 1. 목표

추출해 둔 `audit_report_facts`를 브라우저에서 표로 확인한다. 연구 열람이 1차고, Admin QA·추출 실행은 다음이다.

- **한 행 = 문서 하나** (`rcept_no` + `dcm_no`). F001·F002는 보통 1행, A001 별도·연결은 같은 접수번호가 연속 2행이다.
- facts가 **있는 문서만** 나열한다. `ok` / `section_missing` / `fetch_failed`는 모두 보여 실패도 보인다. 아직 추출하지 않은 카탈로그 접수는 안 나온다.
- 셀은 연구 TSV와 같이 조인 메타 + facts 전 컬럼이다. JSON도 한 줄로 덤프한다.
- 서버 렌더(Jinja). 인증 없음. `/catalog`와 같은 표 골격.

접수 블록으로 묶거나 별도_/연결_ 접두 컬럼으로 접수당 1행을 만들지 않는다. 구현은 `/catalog` 목록과 같은 납작 표다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 대상 | 연구 열람 1차. QA 히트맵은 후속 |
| 행 단위 | facts 문서 (`rcept_no` + `dcm_no`) |
| 행 범위 | facts 행이 있는 문서만 |
| 컬럼 | 조인 4칸 + facts 전 컬럼. `date_resolver_*` 제외 |
| JSON 칸 | 한 줄 문자열, 자르거나 접지 않음. 가로 스크롤 |
| 인증 | 없음 |
| 페이징 | keyset cursor. 총건수 없음 |
| 기존 단건 API | `GET /api/v1/disclosures/{rcp_no}/audit-facts` 유지 |

## 3. 라우트

| 경로 | 역할 |
|------|------|
| `GET /facts` | 납작 표 HTML (`include_in_schema=False`) |
| `GET /api/v1/facts` | 같은 목록의 JSON |

쿼리(둘 다): `limit`(기본 20, 최대 100), `cursor`, 선택 필터 `corp_code`, `corp_name`, `report_nm`, `report_type`, `start_date`, `end_date`.  
`report_type`은 facts의 `source_report_type`이다. 날짜·회사 필터는 조인한 `disclosures` 컬럼이다.

HTML 1차는 필터 폼을 두지 않아도 된다. 쿼리 문자열이 있으면 적용하고, 화면에는 «다음»만 둔다. `/catalog` 1차와 같다.

`GET /api/v1/disclosures/{rcp_no}/audit-facts`는 접수 단건 조회 그대로다. 목록이 아니다.

## 4. 화면

### 4.1 `/facts`

`catalog/base.html`을 재사용한다. 상단 바에 Catalog · Facts 링크(기존 `/catalog` 헤더에도 Facts를 넣는다). 제목은 `Facts · 추출 결과`.

가로 스크롤 `<table>`. 컬럼 순서:

조인 (export TSV와 동일):

1. `corp_name`
2. `year_end`
3. `rcept_dt`
4. `correction_type`

이어서 `AuditReportFact` 모델 선언 순서에서 `date_resolver_model`, `date_resolver_prompt_version`, `date_resolver_raw_response`를 뺀 전부. `rcept_no`는 `/catalog/{rcept_no}` 링크다.

`rcept_no`만 링크로 바꾼다. `fetch_status`는 글자 그대로다.

하단: `next_cursor`가 있으면 «다음» → `?cursor=…` 와 현재 `limit`·필터를 유지한다.

행이 없으면 표 한 줄에 “표시할 추출 결과가 없습니다.” 404가 아니다.

### 4.2 셀 표시

catalog의 `path`(` › ` 조인)를 깨지 않도록, facts 표는 **별도 셀 함수**를 쓴다.

- `null` / 빈 문자열 / 빈 배열 → `—`
- `list`·`dict` JSON (`hours`, `activities`, `communications`, `accounts`, `conflicts`, `audit_report_date_candidates`) → compact JSON 한 줄 (`ensure_ascii=False`, 구분자 최소)
- `extracted_at` → ISO 문자열
- boolean → `true` / `false`

JSON 칸은 `white-space: nowrap`을 유지해 한 줄로 밀린다.

## 5. 데이터 흐름

```text
GET /facts  또는  GET /api/v1/facts
  → FactQueryService.list_page
  → FactRepository.list_page
       audit_report_facts
       INNER JOIN disclosures ON rcept_no
       필터 · keyset · LIMIT limit+1
  → 조인 4칸 + Fact 공개 컬럼
```

공시 행이 없는 facts는 목록에 안 나온다. 연구 TSV 조인과 같다.

정렬: `disclosures.rcept_dt DESC`, `audit_report_facts.rcept_no DESC`, `audit_report_facts.dcm_no ASC`.  
같은 접수의 A001 별도·연결이 붙어 나오고, 접수는 카탈로그와 같이 최신 접수일이 위다.

커서 payload: `{rcept_dt, rcept_no, dcm_no}`. catalog의 `encode_cursor`를 세 필드로 확장한 전용 함수를 쓴다. 손상되면 `BadRequest`(400), 안내 문구는 카탈로그와 같다.

keyset 조건 (내림차순 두 키 + `dcm_no` 오름차순):

- `rcept_dt < cursor.rcept_dt` 이거나
- 같은 `rcept_dt`이고 `rcept_no < cursor.rcept_no` 이거나
- 세 키가 같고 `dcm_no > cursor.dcm_no`

`limit+1`로 다음 페이지 여부를 본다. 총건수는 반환하지 않는다.

### 5.1 JSON 목록 스키마

```json
{
  "items": [
    {
      "corp_name": "삼호저축은행",
      "year_end": "(2025.12)",
      "rcept_dt": "2026.06.01",
      "correction_type": "최초공시",
      "...": "AuditReportFactItem 필드 (date_resolver_* 없음)"
    }
  ],
  "next_cursor": "..."
}
```

`AuditReportFactItem`을 재사용하고 조인 4칸을 앞에 붙인 목록 아이템 모델을 둔다. LLM 해소 메타는 계속 숨긴다.

## 6. 구현 구조

| 경로 | 역할 |
|------|------|
| `app/repositories/fact_repository.py` | `list_page` (join·필터·cursor) |
| `app/services/fact_query_service.py` | cursor 인코딩, 목록 조립 |
| `app/schemas/facts.py` | 목록 아이템·`next_cursor` 응답 |
| `app/api/v1/facts.py` | 단건(`prefix=/api/v1/disclosures`)은 유지. 목록은 같은 모듈 또는 인접 라우터에 `GET /api/v1/facts` |
| `app/api/facts/ui.py` | `GET /facts`. catalog 헤더에 Facts 링크 |
| `app/templates/facts/list.html` | 표. `catalog/base.html` 확장 |
| `tests/test_facts_ui.py` | HTML |
| `tests/test_facts_api.py` | 목록 JSON·커서 보강 |

`main.py`에 HTML 라우터 등록. DART HTTP·추출 잡·스키마 마이그레이션 없음.

## 7. 테스트

메모리 SQLite. DART 호출 없음.

1. `/facts` 200. 조인 4헤더와 facts 공개 컬럼 헤더가 모두 있다. `date_resolver` 헤더가 없다.
2. F001 fixture 1행. `rcept_no`가 `/catalog/{rcp}`로 링크된다.
3. 같은 `rcept_no`의 A001 별도·연결 2행이 `dcm_no` 오름차순으로 연속이다.
4. facts가 없으면 빈 표 문구. 404 아님.
5. `GET /api/v1/facts?limit=1` 다음 `cursor`로 두 번째 행을 받는다. 잘못된 커서는 400.
6. `hours` 칸은 JSON 한 줄이고 ` › ` 조인이 아니다.

## 8. README

루트·`packages/web-api` README에 `http://127.0.0.1:8000/facts` 한 줄과 Public `GET /api/v1/facts`를 적는다.

## 9. 범위 밖

- Admin 추출 QA·완전성 히트맵
- 이 화면에서 추출 잡 실행
- 접수 헤더 아래 중첩 표 (접근 A)
- `별도_` / `연결_` 접두 컬럼 (접근 C)
- JSON 접기·툴팁·문서 단건 HTML
- `fetch_status` 전용 필터
- 카탈로그 미추출 접수를 빈 칸으로 채우기
- 첫 열 freeze, 다크 테마
- `date_resolver_*` 공개
