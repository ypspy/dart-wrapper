# web-api

DART 공시 파이프라인의 FastAPI 서비스입니다. 로컬 앱은 Admin 카탈로그 수집과 열람을 제공하고, 공개 앱은 카탈로그 조회와 Viewer(Lazy Retrieval)를 제공합니다.

## 구조

| 레이어 | 위치 | 역할 |
|--------|------|------|
| API | `app/api` | 라우터·의존성 |
| Service | `app/services` | 수집 오케스트레이션, Viewer 파이프라인 |
| Port/Adapter | `app/ports`, `app/adapters` | 엔트리 수집기, DART HTTP |
| Parsing | `app/parsing` | 본문 정제, 표 → JSON |
| DB | `app/models`, `app/repositories`, `app/db` | 엔트리·작업 메타데이터 |

DB에는 entry 메타데이터만 저장하고, 본문·표는 조회 시점에 `viewer_url`로 가져옵니다.

## 설치

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

PostgreSQL로 배포할 때는 `.\.venv\Scripts\python.exe -m pip install -e ".[postgres]"`를 추가합니다.

## 실행

`packages/web-api` 디렉터리에서 실행합니다. PowerShell은 `.\.venv\...`처럼 `.\` 접두사가 필요합니다.

로컬 앱:

```powershell
cd packages/web-api
.\.venv\Scripts\python.exe -m uvicorn app.local:app --reload
```

공개 앱은 Postgres `DATABASE_URL`이 필요하며 `0.0.0.0:$PORT`에 바인딩합니다.

```bash
python -m uvicorn app.public:app --host 0.0.0.0 --port "$PORT"
```

로컬 앱의 API 문서는 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)에서 확인합니다.

## 엔드포인트

Admin 경로(`/admin/**`)는 `X-Admin-Token` 헤더 또는 `admin_token` 쿠키를 요구합니다.

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/admin/catalog/extract` | 기간/기업별 수집 트리거 (202, `job_id` 반환) |
| POST | `/admin/catalog/resume` | 미완료·실패 슬라이스만 재개 |
| GET | `/admin/catalog/status?job_id=` | 수집 현황·로그 |
| GET | `/admin/catalog/slices` | 날짜 슬라이스 완전성 목록 |
| GET | `/admin/catalog/slices/{slice_id}` | 슬라이스 상세와 공시별 처리 결과 |
| POST | `/admin/catalog/slices/{slice_id}/retry` | 해당 슬라이스 실패분 재시도 |
| POST | `/admin/catalog/jobs/{job_id}/soft-stop` | 다음 공시 경계에서 중단 |
| GET | `/api/v1/catalog/disclosures` | 공시 목록 (cursor 페이지네이션) |
| GET | `/api/v1/catalog/disclosures/{rcp_no}` | 공시 단건 요약 |
| GET | `/api/v1/catalog/disclosures/{rcp_no}/entries` | entry 목록 (전 feature, `all_entries`) |
| GET | `/api/v1/viewer/{rcp_no}` | 접수번호의 모든 entry 섹션 원문 |
| GET | `/api/v1/viewer/{rcp_no}/sections/{entry_id}` | 특정 entry 섹션 원문 |
| GET | `/catalog` | 공시 목록 표 |
| GET | `/catalog/{rcp_no}` | 공시 메타와 entry 표 |

목록 쿼리는 `corp_code`, `corp_name`, `report_nm`, `report_type`, `start_date`, `end_date`, `limit`(1–100), `cursor`를 받습니다. 총건수는 반환하지 않으며 `next_cursor`로 다음 페이지를 이어갑니다.

`all_entries`는 `ordinal` 순 entry이며, entry-extractor 스키마와 같은 feature(`viewer_url`, `path`, `is_leaf`, 공시 features 등)를 담습니다. `entry_id`로 Viewer 단건 조회에 바로 이어갈 수 있습니다.

수집기는 Node entry-extractor 기본값을 따릅니다(목록 이력 포함·첨부 접수 스코프·TOC 중간 노드 포함). 자세한 내용은 [../entry-extractor/README.md](../entry-extractor/README.md)를 보세요.

전체 Viewer 조회는 일부 섹션이 실패하면 해당 섹션에만 `error`를 담고 나머지는 정상 반환합니다. 모든 섹션이 실패하면 502입니다.

## 불연속 수집과 완전성

- 요청 기간을 하루 단위 슬라이스로 나눕니다.
- 공시 하나를 처리할 때마다 저장을 확정하고, 이미 성공한 공시는 다시 파싱하지 않습니다.
- 목록 건수와 성공 건수가 같고 실패가 없을 때만 슬라이스가 `complete`입니다.
- 남은 슬라이스는 `/admin/catalog/resume`이나 Admin 화면의 「이어하기」로 채웁니다.

수집 작업은 uvicorn 프로세스 안에서 실행됩니다. 한 번에 하나의 수집·재개만 허용하며, 다른 수집 작업이 `pending` 또는 `running`이면 새 시작은 409로 거절됩니다.

## 본문 정제

Viewer 응답의 각 섹션은 문서 순서의 `blocks[]`를 담습니다. 블록은 `heading`, `paragraph`, `table` 세 종류입니다. 원문을 한 번 파싱해 `blocks`, `text`, `tables`를 만들며 `text`에는 표 내용을 넣지 않습니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

테스트는 실제 DART 서버를 호출하지 않습니다.

## 설정

`.env.example`을 참고해 `.env`를 만듭니다. 로컬 개발은 SQLite를 사용할 수 있고, 공개 앱은 Postgres `DATABASE_URL`이 필요합니다.

Admin 수집 설정은 `ADMIN_TOKEN`, `DISCLOSURE_MAX_RETRIES`, `BLOCK_STREAK_THRESHOLD`, `BLOCK_WAIT_SECONDS`, `HEATMAP_REPORT_TYPES`, `DART_FETCH_MIN_INTERVAL_SECONDS`입니다.
