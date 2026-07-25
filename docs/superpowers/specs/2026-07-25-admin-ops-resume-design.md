# Admin 운영 UI · 불연속 수집 재개·완전성 설계

날짜: 2026-07-25  
상태: 초안 (브레인스토밍 승인 반영)  
범위: Admin 수집 오케스트레이션(날짜 슬라이스 + 공시 단위 재개), 내부 완전성 모니터, Jinja/HTMX Admin UI

## 1. 목표

DART 원천은 차단·셧다운·지연으로 수집이 자주 끊긴다. Admin의 핵심은 **불연속 실행에서도 중복·누락 없이 카탈로그를 채우고**, 그 완전성을 **모니터링·검증**하는 것이다.

이번 스펙은 다음을 정의한다.

1. **재개 계약** — 날짜 슬라이스 + 공시(`rcp_no`) 단위 체크포인트
2. **Python 오케스트레이터** — Node는 목록/단건 추출기, 저장·상태는 web-api
3. **내부 완전성** — 원천 목록 `listed_count` 대비 succeeded/failed
4. **Admin UI** — FastAPI + Jinja/HTMX (`/admin`), 수집·재개·슬라이스 모니터

Public App UI, 상시 스케줄러, DART 외부 갭 리포트(검색엔진 등)는 비범위다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 주 사용자 | 개발자 1인, 인증 최소화 (`X-Admin-Token`) |
| UI | FastAPI + Jinja/HTMX, 별도 SPA 없음 |
| 재개 단위 | 상위=`report_type × 날짜(1일)`, 하위=`rcp_no` |
| 페이지 번호 | 재개 기준으로 **사용하지 않음** (시간 경과 후 내용 변경) |
| 재스캔 기본 | 최근 **7일** 겹침 수집 (기간은 Admin에서 변경 가능) |
| 재시도 | 일시 오류 자동 N회 + 차단 시 `blocked` 대기/재개 + 수동 오버라이드 |
| 오케스트레이션 | **Python**이 슬라이스·공시를 돌리고 Node를 목록/단건으로 호출 |
| 저장 | 공시 성공 즉시 `entries`/`disclosures` upsert + attempt 기록 |
| 완전성 | 슬라이스 `complete` ⟺ `listed_count == succeeded` && `failed_count == 0` |
| 기존 extract | 요청 스키마 유지, 통째 배치 저장 → 오케스트레이터로 **교체** |

## 3. 아키텍처

```text
[Admin UI /admin]
  수집 폼 · 슬라이스 대시보드 · 상세 · 재시도
       │  HTMX / JSON
       ▼
[Admin API]
  extract / resume / status / slices / retry
       │
       ▼
[CatalogOrchestrator]          ← 신규 (기존 CatalogService 확장·교체)
  날짜 슬라이스 분해
  slice_progress / disclosure_attempt 갱신
  재시도·blocked·soft-stop
       │
       ├── EntryCollector.port
       │     list_disclosures(day) → listed_count + 목록
       │     extract_disclosure(one) → leaf entries
       │
       └── EntryRepository / DisclosureRepository / JobRepository
             즉시 upsert · job 로그
```

### 3.1 왜 Python 오케스트레이터인가

| 방식 | 평가 |
|------|------|
| A. Python이 공시 단위로 Node 호출·즉시 저장 | **채택** — 재개·상태·Admin이 한곳에 모임 |
| B. Node NDJSON 스트리밍 | 프로세스 1회 이점, 크래시·부분 JSON·skip 전달이 복잡 → 후속 최적화 |
| C. 날짜 job만 쪼개고 하루는 통째 저장 | 하루 중간 차단 시 진행분 손실 → 요구와 충돌 |

### 3.2 EntryCollector 포트 확장

기존 `collectEntries` 일괄 호출을 다음으로 나눈다.

| 메서드 | 역할 |
|--------|------|
| `list_disclosures(report_type, start_date, end_date)` | 보통 1일. 원천 목록 + `listed_count`(pageInfo "총 N건") |
| `extract_disclosure(disclosure, include_attachments)` | 1건 상세 → leaf entry 배열 |

Node `entry-extractor`에 대응 CLI 모드/서브커맨드를 추가한다. 기존 일괄 `collectEntries`는 예제·수동용으로 남겨도 되나, web-api Admin 경로는 위 두 메서드만 사용한다.

## 4. 데이터 모델

### 4.1 `slice_progress`

| 컬럼 | 설명 |
|------|------|
| `slice_id` | PK (UUID) |
| `report_type` | 예: `F001` |
| `slice_date` | `YYYYMMDD` |
| `status` | `pending` \| `running` \| `blocked` \| `complete` \| `failed` |
| `listed_count` | 원천 목록 총건수 (미확정이면 null) |
| `attempted` / `succeeded` / `failed_count` | 집계 |
| `last_job_id` | 최근 처리 job |
| `attempt` | 슬라이스 재시도 횟수 |
| `started_at` / `finished_at` / `updated_at` | |

Unique: `(report_type, slice_date)` — 같은 슬라이스는 1행, 재실행 시 갱신.

### 4.2 `disclosure_attempt`

| 컬럼 | 설명 |
|------|------|
| `rcept_no` | PK |
| `slice_id` | FK |
| `report_type` | |
| `status` | `pending` \| `succeeded` \| `failed` \| `blocked` |
| `entry_count` | 성공 시 leaf 수 |
| `attempt` | 재시도 횟수 |
| `last_error` | 한국어 요약 |
| `updated_at` | |

성공한 `rcept_no`는 resume/rescan 시 **상세 재파싱 skip**(또는 upsert만). 실패·blocked만 재시도 대상.

### 4.3 `catalog_jobs` 확장

기존 필드 유지 + `mode`: `collect` \| `resume` \| `rescan`.  
`params`에 기간·유형·`include_attachments` 유지.

### 4.4 상태 전이

```text
slice: pending → running → complete
                 running → blocked → running (대기 후/수동 resume)
                 running → failed
disclosure: pending → succeeded | failed | blocked
            failed/blocked → (retry) → succeeded | failed | blocked
```

`complete` 조건: `listed_count`가 확정이고 `succeeded == listed_count`이며 `failed_count == 0`.  
목록 fetch 실패로 `listed_count` 미확정이면 `complete` 불가.

`succeeded`에는 **이번 실행에서 새로 파싱한 공시**와 **이미 succeeded라 skip한 공시**를 모두 포함한다. 재스캔 시 “목록에 있는 접수번호가 전부 성공 상태”인지만 보면 된다.

## 5. 수집·재개 흐름

### 5.1 extract / rescan

1. Admin이 `report_type`, `start_date`, `end_date`(기본 최근 7일), `include_attachments` 제출
2. job 생성 (`mode=collect` 또는 기간이 최근 윈도우면 `rescan`), BackgroundTasks로 오케스트레이터 실행
3. 기간을 **1일 슬라이스**로 분해. 각 슬라이스:
   1. `list_disclosures` → `listed_count` 기록, `rcp_no` 집합 확보
   2. 이미 `succeeded`인 `rcp_no`는 skip
   3. 나머지마다 `extract_disclosure` → 즉시 entries/disclosures upsert → attempt=`succeeded`
   4. 일시 오류: 공시별 지수 백오프 N회(기본 3) 후 `failed`
   5. 연속 M회(기본 5) 차단성(403/429/연결 거부): 슬라이스·job → `blocked`, 대기 후 자동 재개 또는 수동
   6. 종료 시 complete 조건 평가
4. soft-stop: 다음 공시 경계에서 중단, 이미 succeeded는 유지

### 5.2 resume

`POST /admin/catalog/resume` (선택적으로 `slice_id` / `report_type` 필터):

- `status ∈ {pending, running, blocked, failed}` 이거나 `failed_count > 0`인 슬라이스
- 그 안의 `failed`/`blocked`/`pending` 공시만 처리
- `mode=resume` job 생성

### 5.3 슬라이스 단위 실패 재시도

`POST /admin/catalog/slices/{slice_id}/retry` — 해당 슬라이스의 실패분만 재시도(내부적으로 resume과 동일 경로).

## 6. Admin API

모두 `X-Admin-Token` 필수(설정 `ADMIN_TOKEN`). JSON API는 요청 헤더로 검증한다. HTML UI는 최초에 토큰을 입력해 **HttpOnly 쿠키**에 저장한 뒤, 미들웨어가 헤더 또는 해당 쿠키를 허용한다(로그인 화면 수준의 UX는 두지 않음).

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/admin/catalog/extract` | 기간 수집/재스캔 시작 → `{job_id, status}` |
| POST | `/admin/catalog/resume` | 미완료·실패만 재개 |
| GET | `/admin/catalog/status?job_id=` | job 상태·카운트·최근 로그 |
| GET | `/admin/catalog/slices` | 슬라이스 목록·완전성 요약 (`report_type`, 날짜 범위 필터) |
| GET | `/admin/catalog/slices/{slice_id}` | 공시별 attempt + 슬라이스 메타 |
| POST | `/admin/catalog/slices/{slice_id}/retry` | 실패분 재시도 |

기존 extract 요청 바디 필드는 유지한다. 동일 파라미터로 `running` job이 있으면 기존처럼 기존 `job_id` 반환 정책을 유지하되, resume은 별도 엔드포인트다.

## 7. Admin UI (`/admin`)

Jinja 템플릿 + HTMX. web-api 패키지 내 `app/templates/admin/`, `app/static/admin/`.

| 화면 | 내용 |
|------|------|
| 수집 폼 | report_type, 기간(기본 최근 7일), include_attachments → extract |
| 대시보드 | 슬라이스 테이블: 날짜, listed/succeeded/failed, status, 이어하기·실패 재시도 |
| 슬라이스 상세 | 공시별 상태·에러, job 로그 폴링 |
| job 배지 | running / blocked, soft-stop 버튼 |

로그인 UI 없음. 로컬/내부에서 토큰을 설정·전달.

## 8. 에러 처리

| 상황 | 응답/동작 |
|------|------|
| 공시 상세 타임아웃·5xx·파싱 실패 | attempt↑, N회 후 `failed`, job 계속 |
| 연속 차단성 응답 | slice/job `blocked` |
| 목록 fetch 실패 | slice `failed`, listed_count 미확정 |
| Node 단건 프로세스 비정상 종료 | 해당 공시만 `failed` |
| soft-stop / 프로세스 다운 | succeeded 유지, resume 대상 남김 |
| Admin 토큰 없음/불일치 | `401` 한국어 |
| 없는 slice_id / job_id | `404` |

로그는 `catalog_job_logs`에 슬라이스·`rcp_no`를 메시지에 포함한다.

## 9. 테스트 범위

실제 DART 호출 없이 가짜 `EntryCollector` + 인메모리 SQLite.

- 오케스트레이터: 1일 3공시 → 중간 1건 실패 → resume 시 실패만 재시도, succeeded skip
- 완전성: 3/3 → `complete`; 2/3 → 아님
- blocked: 연속 실패 전이, resume 후 재개
- upsert: 동일 `rcp_no` 재수집 시 entries/disclosures 중복 없음
- Admin API: extract/resume/slices/retry 스키마·상태코드·401
- UI: 핵심 템플릿에 슬라이스 요약·재시도 버튼 존재(스모크)

## 10. 비범위

- Public 카탈로그·Viewer UI
- 상시 스케줄러(cron). 단, resume/extract API는 나중에 스케줄러가 호출 가능하도록 유지
- DART 목록 총건수 외 외부 기대치·검색엔진 갭 리포트
- Celery/Redis, Viewer 응답 캐시
- Alembic(기존 `create_all` + 필요 시 일회 스크립트)
- 다중 사용자 로그인·역할·감사 계정 체계
- Node NDJSON 스트리밍 최적화

## 11. 성공 기준

1. 하루 슬라이스 중 일부 공시만 실패해도 성공분은 DB에 남고, resume으로 나머지를 채울 수 있다.
2. `listed_count == succeeded && failed_count == 0`일 때만 슬라이스 `complete`다.
3. `/admin`에서 수집 시작·슬라이스 완전성 확인·실패 재시도가 가능하다.
4. `X-Admin-Token` 없이는 Admin API·UI가 거부된다.
5. 주석·Docstring·로그·예외 메시지는 한국어다.

## 12. 기존 스펙과의 관계

- `2026-07-25-admin-viewer-skeleton-design.md`: Admin extract/status 뼈대 위에 **오케스트레이션·체크포인트·UI**를 얹는다. Viewer Public API는 변경하지 않는다.
- `2026-07-25-catalog-query-api-design.md`: disclosures upsert는 유지. 공시 성공 시점에 기존과 같이 disclosure를 갱신한다.
