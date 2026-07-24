# Admin 카탈로그 · Public Viewer 코드 뼈대 설계

날짜: 2026-07-25  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` FastAPI 앱의 모듈·API·데이터 모델 뼈대 (구현 계획 전 스펙)

## 1. 목표

PRD/AGENTS 요구에 맞춰 DART 공시 파이프라인 Web App의 두 축을 코드 뼈대로 정의한다.

1. **Admin 카탈로그 수집** — 기간/기업별 flat entry 메타데이터를 DB에 저장
2. **Public Viewer** — 요청 시 `viewer_url`로 원문을 동적 수집·정제(Lazy Retrieval)

이번 스펙의 산출물은 구현 세부 계획이 아니라, **디렉터리·포트·API 계약·DB 스키마·에러/동시성/테스트 경계**다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| Entry 수집 | 기존 Node `@dart-wrapper/entry-extractor`를 `EntryCollector` 포트 뒤에서 서브프로세스로 호출 |
| DB | 로컬 SQLite / 웹 배포 Neon PostgreSQL. SQLAlchemy Repository로 추상화, `DATABASE_URL`만 교체 |
| Admin 실행 | FastAPI `BackgroundTasks` + `catalog_jobs` / `catalog_job_logs` |
| Viewer 전체 조회 | `rcp_no`의 **모든 leaf**(본문·첨부) 완전 파싱 — Agent/종합 분석용 |
| Viewer 단일 조회 | `entry_id` 기준 빠른 섹션 조회 — 사람/UI용 |
| 패키지 위치 | `packages/web-api/` |
| 아키텍처 | 단일 FastAPI 앱 + 레이어드 구조 (`api` → `services` → `ports/adapters` → `db`) |
| 본문 저장 | DB에는 entry 메타만. 원문 HTML·정제 텍스트·표는 저장하지 않음 |

### 2.1 Viewer 이중 엔드포인트 (의도)

- **사람**: 특정 섹션만 빠르게 본다 → `GET .../sections/{entry_id}`
- **Agent/종합**: 한 공시의 관련 leaf를 모두 모아 분석한다 → `GET .../{rcp_no}`

`viewer_url`은 “주소를 해석하는 대상”이 아니라, **원문 HTML을 가져오기 위한 링크**다. Admin이 메타·URL을 저장하고, Viewer는 조회 시점에 그 URL들로 문서를 가져온다.

### 2.2 PRD 경로 조정

PRD의 `GET /api/v1/viewer/{rcp_no}/sections/{ele_id}`는 고유 식별이 부족하다(`ele_id`는 `dcm_no`마다 중복 가능). 본 설계에서는 **`{entry_id}`** 를 사용한다.

## 3. 아키텍처

```text
[Admin]
POST /admin/catalog/extract
  → CatalogService (job 생성, BackgroundTasks)
  → NodeEntryCollector (entry-extractor 서브프로세스)
  → EntryRepository upsert + JobRepository/로그

GET /admin/catalog/status
  → JobRepository + 최근 로그

[Viewer]
GET /api/v1/viewer/{rcp_no}
  → EntryRepository (해당 rcp_no 모든 leaf)
  → DartHttp (semaphore 제한 병렬 fetch, 인코딩 자동 처리)
  → cleaner / tables → JSON (부분 실패 leaf는 error 필드)

GET /api/v1/viewer/{rcp_no}/sections/{entry_id}
  → leaf 1개만 동일 파이프라인
```

### 3.1 디렉터리 뼈대

```text
packages/web-api/
├── pyproject.toml
├── README.md
├── app/
│   ├── main.py
│   ├── config.py
│   ├── errors.py
│   ├── api/
│   │   ├── admin/
│   │   │   └── catalog.py
│   │   └── v1/
│   │       └── viewer.py
│   ├── schemas/
│   ├── models/
│   ├── db/
│   ├── repositories/
│   ├── services/
│   │   ├── catalog_service.py
│   │   └── viewer_service.py
│   ├── ports/
│   │   └── entry_collector.py
│   ├── adapters/
│   │   ├── node_entry_collector.py
│   │   └── dart_http.py
│   └── parsing/
│       ├── cleaner.py
│       └── tables.py
└── tests/
```

### 3.2 주요 단위 책임

| 단위 | 역할 | 의존 |
|------|------|------|
| `EntryCollector` (port) | flat entry 목록 수집 계약 | 없음 (Protocol) |
| `NodeEntryCollector` | Node `collectEntries` 서브프로세스 어댑터. CLI/스크립트에 JSON 파라미터를 넘기고 stdout의 entry 배열 JSON을 파싱한다 | entry-extractor, config |
| `CatalogService` | job 생성·백그라운드 실행·상태 조회 | collector, repositories |
| `ViewerService` | Lazy Retrieval 오케스트레이션 | EntryRepository, DartHttp, parsing |
| `DartHttp` | httpx fetch + EUC-KR/UTF-8 인코딩 | httpx |
| `cleaner` / `tables` | HTML 정제·표 JSON화 | BeautifulSoup4, pandas(필요 시) |
| Repositories | Entry/Job/Log 영속화 | SQLAlchemy async |

## 4. 데이터 모델

### 4.1 `entries`

flat leaf 카탈로그. entry-extractor 스키마를 저장한다.

- PK: `entry_id` (`rcept_no_dcmNo_ele_id`, 첨부는 `..._att` 규칙 유지)
- 주요 필드: `rcept_no`, `corp_code`, `corp_name`, `report_nm`, `rcept_dt`, `report_type`, `correction_type`, `year_end`, `submitter`, `source` (`body`\|`attachment`), `dcm_no`, `ele_id`, `document_name`, `section_name`, `section_original_name`, `depth`, `is_leaf`, `parent_ele_id`, `offset`, `length`, `dtd`, `path`(JSON), `viewer_url`, `disclosure_url`, `created_at`, `updated_at`
- 인덱스: `rcept_no`, `(rcept_no, entry_id)`, `corp_code`
- 저장 정책: `entry_id` 기준 upsert. 원문 본문/표는 저장하지 않음

### 4.2 `catalog_jobs`

- `job_id` (PK, UUID)
- `status`: `pending` \| `running` \| `succeeded` \| `failed`
- `params` (JSON): `report_type`, `start_date`, `end_date`, `corp_code?`, `max_total?`, `include_attachments?`
- `total_entries`, `saved_entries`, `error_message`
- `started_at`, `finished_at`, `created_at`

동일 파라미터로 이미 `running`인 job이 있으면 새 job을 만들지 않고 기존 `job_id`를 반환한다.

### 4.3 `catalog_job_logs`

- `id`, `job_id` (FK), `level` (`info`\|`warning`\|`error`), `message`, `created_at`

## 5. API 계약

### 5.1 Admin

**`POST /admin/catalog/extract`**

요청:

```json
{
  "report_type": "F001",
  "start_date": "20260701",
  "end_date": "20260724",
  "corp_code": null,
  "max_total": 100,
  "include_attachments": true
}
```

응답 (즉시):

```json
{ "job_id": "...", "status": "pending" }
```

**`GET /admin/catalog/status?job_id=...`**

응답: job 상태, `saved_entries`/`total_entries`, 최근 로그 목록.

### 5.2 Public Viewer

**`GET /api/v1/viewer/{rcp_no}`** — Agent/종합용, 모든 leaf

```json
{
  "rcp_no": "20260724000650",
  "meta": {
    "corp_name": "...",
    "report_nm": "...",
    "rcept_dt": "..."
  },
  "sections": [
    {
      "entry_id": "20260724000650_11495035_5",
      "source": "body",
      "dcm_no": "11495035",
      "ele_id": "5",
      "path": ["(첨부)재무제표", "재무상태표"],
      "document_name": "감사보고서",
      "section_name": "재무상태표",
      "text": "...",
      "tables": [{ "headers": [], "rows": [] }],
      "error": null
    }
  ]
}
```

**`GET /api/v1/viewer/{rcp_no}/sections/{entry_id}`** — 단일 leaf, 위 `sections[]` 요소와 동일 스키마.

## 6. 에러 처리

도메인 예외는 `app/errors.py`에 두고 FastAPI 핸들러에서 한국어 메시지로 변환한다.

| 상황 | 응답 |
|------|------|
| 카탈로그에 `rcp_no` 없음 | `404` |
| `entry_id`가 해당 `rcp_no`에 속하지 않음 | `404` |
| 일부 leaf fetch/파싱 실패 (전체 조회) | `200` + 해당 section `error`, 나머지는 정상 |
| 모든 leaf 실패 (전체 조회) | `502` |
| 단일 섹션 fetch/파싱 실패 | `502` |
| Admin: 개별 공시 파싱 실패 | job 계속, 로그 `warning` |
| Admin: Node 프로세스 비정상 종료 | job `failed`, `error_message`에 stderr 요약 |

## 7. 동시성 · 인코딩 · 배포 경제성

- Viewer 병렬 fetch: `asyncio.Semaphore` (기본 동시 4, 설정 가능)
- leaf별 타임아웃 + 제한 재시도(지수 백오프)
- 공용 `httpx.AsyncClient`를 앱 lifespan에 등록
- 인코딩: Content-Type → `meta charset` → EUC-KR 폴백
- DB: 개발 SQLite(`aiosqlite`), 배포 Neon PostgreSQL(`asyncpg`). MongoDB/Turso는 채택하지 않음 — flat entry·job 관계와 FastAPI ORM 경제성에서 Neon이 유리. 무료 티어(약 0.5GB)로 시작하고 용량 초과 시 재평가

## 8. 테스트 범위 (뼈대 기준)

실제 DART 호출 없이:

- HTML 픽스처(EUC-KR 포함)로 `cleaner` / `tables` 단위 테스트
- 가짜 `EntryCollector`로 Admin job 상태 전이 테스트
- 인메모리 SQLite로 Repository upsert·조회 테스트
- `httpx.MockTransport`로 Viewer 전체/단일, 부분 실패, 404/502 테스트

## 9. 비범위 (이번 뼈대에서 하지 않음)

- entry-extractor Python 이식
- Celery/Redis 등 외부 작업 큐
- Viewer 응답 캐시(Redis 등)
- Admin 인증/인가 UI 및 프론트엔드
- OpenDART API 사용
- 원문 HTML/PDF 장기 저장

## 10. 성공 기준

1. `packages/web-api`에 Admin 2개·Viewer 2개 엔드포인트의 라우트·서비스·포트 스텁이 존재한다.
2. Admin extract가 `job_id`를 즉시 반환하고 status로 진행을 조회할 수 있다(가짜 collector로).
3. Viewer가 카탈로그 entry의 `viewer_url`만으로 텍스트·표를 반환하는 파이프라인이 분리되어 있다.
4. `DATABASE_URL` 교체만으로 SQLite ↔ PostgreSQL을 전환할 수 있는 Repository 경계가 있다.
5. 주석·Docstring·로그·예외 메시지는 한국어다.
