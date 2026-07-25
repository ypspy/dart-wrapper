# 카탈로그 목록·검색 API 설계

날짜: 2026-07-25
상태: 승인 (브레인스토밍 결과, 제품 목표 보완 반영)
범위: `packages/web-api` — 공시 목록·단건·목차 조회 API와 `disclosures` 테이블 도입

## 1. 배경과 목표

제품의 기본 흐름은 다음과 같다.

1. 파서가 leaf entry를 수집해 카탈로그에 저장한다
2. 사용자가 **공시 목록**에서 접수 단위를 고른다
3. 해당 공시의 **leaf 목차**에서 섹션을 고른다
4. 클릭하면 **Viewer**가 `viewer_url`로 원문을 Lazy Retrieval한다

현재 Public Viewer는 `rcp_no`를 이미 알고 있어야 사용할 수 있어, 2·3단계 탐색 API가 없다.
이번 스펙은 그 진입점을 만든다.

전역 leaf 목록을 주 탐색 UI로 두지 않는다. leaf는 수백만 건이 될 수 있고, 사용자가
디폴트로 보고 싶은 것은 **공시당 소수(감사보고서는 대체로 10건 안쪽, 사업보고서는 더 많을 수
있음)** 이기 때문이다. 탐색의 1차 단위는 공시이고, leaf는 공시 안의 목차다.

예상 규모는 **공시(접수) 수십만 건, leaf entry 수백만 건**이다. 이 규모가 설계 결정의 근거다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 제품 흐름 | 공시 목록 → leaf 목차(클릭) → Viewer |
| 조회 단위 | 공시 목록과 leaf 목차를 **엔드포인트 분리** |
| 디폴트 목차 | `report_type`별 섹션명 allowlist로 `primary_entries` 선별 |
| 전체 목차 | 같은 응답에 `all_entries`로 전량 제공(“전체 보기”) |
| allowlist 저장 | 코드 내 상수 (`report_type → 섹션명 패턴`) |
| 초기 allowlist | `F001`(감사보고서)만. 미등록 유형은 `primary_entries=[]` |
| 필터 | `corp_code`, `corp_name`(부분일치), `report_nm`(부분일치), `report_type`, `rcept_dt` 기간 |
| API 위치 | Public `/api/v1/catalog` (Viewer와 같은 공개 영역, 인증 없음) |
| 페이지네이션 | keyset cursor (`rcept_dt`, `rcept_no`) — **공시 목록만** |
| 총건수 | 응답에 포함하지 않음 |
| 집계 방식 | `disclosures` 테이블을 새로 두고 수집 시 upsert |
| 본문 저장 | 변경 없음. 여전히 메타만 저장하고 원문은 Lazy Retrieval |

### 2.1 왜 전역 leaf 목록이 아닌가

leaf를 평면 리스트로 보여주면 건수가 폭증하고, 사용자가 원하는 “공시당 핵심 몇 개”와 맞지
않는다. 공시를 고른 뒤 그 안의 leaf를 보여주는 구조가 Viewer 진입과 맞다.

### 2.2 왜 offset이 아니라 cursor인가

`LIMIT n OFFSET 200000`은 DB가 앞의 20만 행을 실제로 훑어 버리므로 뒤쪽 페이지가 선형으로
느려진다. `(rcept_dt DESC, rcept_no DESC)` 복합 인덱스에 keyset 조건
`(rcept_dt, rcept_no) < (:dt, :no)`를 걸면 몇 번째 페이지든 인덱스 진입 한 번으로 끝난다.

정렬 키에 PK를 포함해 tie-break가 확정적이므로, 수집이 동시에 진행돼 새 공시가 들어와도
페이지가 밀리거나 항목이 중복되지 않는다.

총건수를 내지 않는 것도 같은 이유다. 수십만 행에 대한 `COUNT(*)`는 필터가 걸려도 비싸고,
cursor 방식에서는 총건수가 UI 계약상 필요하지 않다.

### 2.3 왜 `disclosures` 테이블이 필요한가

`entries`만으로 공시 목록을 만들면 매 요청마다 `GROUP BY rcept_no` 집계가 필요하다. 공시
수십만 × leaf 수십 건이면 keyset을 써도 그룹핑이 넓은 범위를 스캔하므로 느려진다.
접수 단위 1행을 미리 만들어 두면 목록 조회가 인덱스 스캔만으로 끝난다.

검색엔진(Meilisearch/ES) 도입은 이번 필터 범위에 과하고 동기화·운영 비용이 크므로 제외한다.

## 3. 데이터 모델

### 3.1 새 테이블 `disclosures`

`app/models/disclosure.py`

| 컬럼 | 타입 | 비고 |
|------|------|------|
| `rcept_no` | `String(32)` | PK |
| `corp_code` | `String(16)` | 인덱스 |
| `corp_name` | `String(255)` | |
| `report_nm` | `String(255)` | |
| `report_type` | `String(16)` | 인덱스 |
| `correction_type` | `String(32)` | |
| `submitter` | `String(255)` | |
| `rcept_dt` | `String(16)` | 복합 인덱스 선두 |
| `bsns_year` | `String(8)` | |
| `year_end` | `String(32)` | |
| `disclosure_url` | `String(1024)` | |
| `entry_count` | `Integer` | leaf 전량 개수 |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | |

인덱스: `(rcept_dt DESC, rcept_no DESC)`, `corp_code`, `report_type`.

컬럼은 모두 기존 `Entry`에 이미 있는 공시 단위 필드에서 온다. 새로 수집할 정보는 없다.
`is_primary` 같은 플래그는 DB에 두지 않는다. primary 여부는 조회 시 allowlist로 계산한다.

### 3.2 `entries` 변경

스키마 변경 없음. 목차 조회를 위해 필요한 컬럼만 뽑는 경량 select를 리포지터리에 추가한다.

## 4. API 계약

모두 Public, 인증 없음. prefix `/api/v1/catalog`.

명명 규칙은 기존 코드를 따른다. DB 컬럼과 cursor 내부 키는 `rcept_no`, URL 경로 변수와 응답
필드는 `rcp_no`다(기존 Viewer 라우터가 `/{rcp_no}`를 쓴다). 둘은 같은 접수번호를 가리킨다.

### 4.1 `GET /disclosures` — 공시 목록

쿼리 파라미터:

| 이름 | 타입 | 기본 | 설명 |
|------|------|------|------|
| `corp_code` | `str?` | | 정확일치 |
| `corp_name` | `str?` | | 부분일치 |
| `report_nm` | `str?` | | 부분일치 |
| `report_type` | `str?` | | 정확일치 |
| `start_date` | `str?` | | `rcept_dt >= ` (YYYYMMDD) |
| `end_date` | `str?` | | `rcept_dt <= ` (YYYYMMDD) |
| `limit` | `int` | 20 | 1~100 |
| `cursor` | `str?` | | 이전 페이지의 `next_cursor` |

응답 `DisclosureListResponse`:

```json
{
  "items": [
    {
      "rcp_no": "20260724000650",
      "corp_code": "00224628",
      "corp_name": "회사명",
      "report_nm": "감사보고서",
      "report_type": "F001",
      "rcept_dt": "20260724",
      "entry_count": 10,
      "disclosure_url": "https://dart.fss.or.kr/..."
    }
  ],
  "next_cursor": "eyJyY2VwdF9kdCI6..."
}
```

마지막 페이지에서는 `next_cursor`가 `null`이다.

### 4.2 `GET /disclosures/{rcp_no}` — 공시 1건

`DisclosureSummary` 단건을 반환한다. 없으면 `404`.

### 4.3 `GET /disclosures/{rcp_no}/entries` — leaf 목차

해당 공시의 leaf를 **전량** 읽은 뒤, allowlist로 primary를 가른다.
목차는 공시당 보통 수십~수백 건이라 **페이지네이션 없음**.
정렬은 `source`(본문 우선), `dcm_no`, `ele_id` 순.

응답 `DisclosureEntriesResponse`:

```json
{
  "rcp_no": "20260724000650",
  "report_type": "F001",
  "primary_entries": [ /* allowlist 일치 leaf */ ],
  "all_entries": [ /* 전량 leaf */ ]
}
```

항목 `EntrySummary`: `entry_id`, `source`, `dcm_no`, `ele_id`, `document_name`,
`section_name`, `path`, `depth`.

`primary_entries`는 `all_entries`의 부분집합이다(동일 객체 중복이 아니라 같은 정렬·필드의
필터 결과). 클라이언트의 기본 UI는 `primary_entries`를 보여주고, “전체 보기”에서
`all_entries`를 쓴다.

`entry_id`가 포함되므로 클라이언트는 곧바로
`GET /api/v1/viewer/{rcp_no}/sections/{entry_id}`로 이어갈 수 있다. 본문 파싱은 하지 않는다.

등록되지 않은 `report_type`이거나 일치 leaf가 없으면 `primary_entries`는 빈 배열이다.
이 경우 UI는 `all_entries`로 전체 보기를 기본으로 쓸 수 있다.

## 5. primary allowlist

`app/catalog/primary_sections.py` (또는 동등 위치)에 **코드 상수**로 둔다.

```python
# report_type → section_name 부분일치 패턴 (대소문자·공백 정규화 후 포함 여부)
PRIMARY_SECTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "F001": (
        "재무상태표",
        "손익계산서",
        "포괄손익계산서",
        "자본변동표",
        "현금흐름표",
        "주석",
    ),
}
```

매칭 규칙:

1. `entry.report_type`(또는 disclosure의 `report_type`)으로 패턴 목록을 찾는다
2. `section_name`(없으면 `document_name`)을 공백 압축·소문자화 없이 **부분 문자열 포함**으로
   비교한다(한국어 섹션명이므로 대소문자 변환은 불필요, 앞뒤 공백만 strip)
3. 패턴이 하나라도 포함되면 primary
4. DB에 `is_primary`를 저장하지 않는다 — allowlist 변경이 재수집 없이 즉시 반영된다

초기 범위는 `F001`만. 사업보고서 등 다른 유형은 후속으로 패턴을 추가한다.
첨부(`source=attachment`)도 패턴에 맞으면 primary에 포함될 수 있다. 첨부를 일괄 제외하는
규칙은 이번 범위에 두지 않는다(필요하면 allowlist/후속 규칙으로 추가).

## 6. cursor 규격

`base64url(json({"rcept_dt": "...", "rcept_no": "..."}))` — 클라이언트에게는 opaque 토큰이다.

- 정렬: `ORDER BY rcept_dt DESC, rcept_no DESC`
- 다음 페이지: `WHERE (rcept_dt, rcept_no) < (:dt, :no)`
  (SQLite/Postgres 모두 지원하도록 `rcept_dt < :dt OR (rcept_dt = :dt AND rcept_no < :no)`로 전개)
- `limit + 1`건을 읽어 초과분이 있으면 마지막 항목으로 `next_cursor`를 만든다
- 디코딩 실패·필드 누락 시 `400`

`rcept_dt`가 `NULL`인 행은 정렬이 불안정해지므로, 수집 시 `rcept_dt`가 없으면 빈 문자열로
정규화해 저장한다.

## 7. 레이어 구성

기존 레이어드 패턴(`api` → `services` → `repositories`)을 그대로 확장한다.

| 파일 | 역할 |
|------|------|
| `app/models/disclosure.py` | `Disclosure` ORM 모델 |
| `app/catalog/primary_sections.py` | `report_type`별 섹션명 allowlist 상수와 매칭 헬퍼 |
| `app/schemas/catalog_query.py` | `DisclosureSummary`, `EntrySummary`, `DisclosureListResponse`, `DisclosureEntriesResponse` |
| `app/repositories/disclosure_repository.py` | keyset 목록 조회, 단건 조회, upsert, backfill |
| `app/repositories/entry_repository.py` | `list_toc_by_rcept_no` 추가 |
| `app/services/catalog_query_service.py` | cursor 인코딩·디코딩, 목차 primary 분리, 조회 오케스트레이션 |
| `app/api/v1/catalog.py` | Public 라우터 |
| `app/api/deps.py` | `get_catalog_query_service` 추가 |

조회 서비스를 수집용 `CatalogService`와 분리한다. 수집은 쓰기·백그라운드 작업이고 조회는
읽기 전용이라 의존성과 변경 이유가 다르다.

## 8. 수집 연동과 backfill

`CatalogService.run_job`에서 entries upsert 직후, 수집 결과를 `rcept_no`로 묶어 disclosure를
upsert하고 `entry_count`를 해당 접수번호의 leaf 수로 갱신한다. 재수집 시 중복 행이 생기지
않아야 한다. primary 여부는 수집 시점에 저장하지 않는다.

기존에 `entries`만 있는 DB를 위해 **idempotent backfill 헬퍼**를 제공한다.
`entries`를 `rcept_no`로 집계해 `disclosures`를 채우며, 두 번 실행해도 결과가 같다.
운영 트리거는 이번 범위에서 정의하지 않고, 로컬에서 스크립트로 한 번 실행한다.

Alembic 마이그레이션은 별도 과제로 남긴다. 현재는 `create_all`이 새 테이블을 만든다.

## 9. 에러 처리

| 상황 | 응답 |
|------|------|
| 없는 `rcp_no` | `CatalogNotFound` → `404` |
| 손상된 cursor | `400` + 한국어 메시지 |
| `limit` 범위 초과 | FastAPI 검증 → `422` |

메시지는 기존 규칙대로 친절한 한국어로 제공한다.

## 10. 테스트 범위

실제 DART 호출 없이 aiosqlite 인메모리로 검증한다.

- **`test_disclosure_repository.py`** — upsert 재실행 시 중복 없이 `entry_count` 갱신,
  `(rcept_dt, rcept_no)` 역순 정렬, 같은 `rcept_dt` tie 구간에서 누락·중복 없는 cursor 경계,
  각 필터의 단독·조합 동작
- **`test_primary_sections.py`** — F001 패턴 매칭, 미등록 report_type은 빈 primary,
  부분일치·공백 strip
- **`test_catalog_query_service.py`** — cursor 인코딩·디코딩 왕복, 손상된 cursor 예외,
  마지막 페이지 `next_cursor is None`, 없는 `rcp_no`에 `CatalogNotFound`,
  목차 응답에서 `primary_entries ⊆ all_entries`
- **`test_catalog_query_api.py`** — 세 엔드포인트의 상태코드·응답 스키마, `limit` 초과 422,
  잘못된 cursor 400, 없는 공시 404, 목차에 `entry_id`와 `primary_entries`/`all_entries` 포함
- **`test_catalog_service.py` 확장** — 수집 후 `disclosures`가 `rcept_no`별 1행,
  `entry_count`가 leaf 수와 일치, 재수집 시 갱신
- **backfill** — entries만 있는 상태에서 채워지고, 두 번 실행해도 동일

## 11. 범위 밖

- Admin 엔드포인트 인증
- Viewer 정제 결과 캐시
- 검색엔진 도입, leaf `section_name`/`path` 키워드 검색
- 총건수(`total`) 제공
- 전역 leaf 목록 API
- 사업보고서 등 F001 외 allowlist (후속 상수 추가만으로 확장 가능)
- Alembic 마이그레이션, 수집 워커 분리
- 프론트엔드 UI 구현
