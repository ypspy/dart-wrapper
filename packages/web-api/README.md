# web-api

DART 공시 파이프라인의 FastAPI 서비스입니다. Admin 카탈로그 수집과 Public Viewer(Lazy Retrieval)를 제공합니다.

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

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

PostgreSQL로 배포할 때는 `.venv\Scripts\python.exe -m pip install -e ".[postgres]"`를 추가합니다.

## 실행

```bash
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

문서: http://127.0.0.1:8000/docs

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
| GET | `/api/v1/catalog/disclosures/{rcp_no}/entries` | leaf 목차 (`primary_entries` + `all_entries`) |
| GET | `/api/v1/viewer/{rcp_no}` | 접수번호의 모든 leaf 섹션 원문 (종합 분석용) |
| GET | `/api/v1/viewer/{rcp_no}/sections/{entry_id}` | 특정 leaf 섹션 원문 (단건 조회) |

목록 쿼리: `corp_code`, `corp_name`, `report_nm`, `report_type`, `start_date`, `end_date`, `limit`(1–100), `cursor`.
총건수는 반환하지 않으며, 다음 페이지는 `next_cursor`로 이어갑니다.

목차의 `primary_entries`는 `report_type`별 섹션명 allowlist(현재 `F001`)로 선별합니다.
기본 UI는 primary를, “전체 보기”는 `all_entries`를 쓰면 됩니다. `entry_id`로 Viewer 단건 조회에 바로 이어갈 수 있습니다.

전체 Viewer 조회는 일부 섹션이 실패하면 해당 섹션에만 `error`를 담고 나머지는 정상 반환합니다. 모든 섹션이 실패하면 502입니다.

## 불연속 수집과 완전성

DART는 차단·점검·지연으로 수집이 자주 끊깁니다. 그래서 수집은 다음 규칙으로 동작합니다.

- 요청 기간을 **하루 단위 슬라이스**로 나눕니다. 페이지 번호는 시간이 지나면 다른 공시를 담으므로 재개 기준으로 쓰지 않습니다.
- 슬라이스 안에서는 공시(접수번호) 하나를 처리할 때마다 저장을 확정합니다. 중간에 끊겨도 성공분은 남습니다.
- 이미 성공한 공시는 다시 파싱하지 않습니다. 같은 기간을 여러 번 돌려도 중복이 생기지 않습니다.
- 일시 오류는 `DISCLOSURE_MAX_RETRIES`만큼 지수 백오프로 재시도하고, 차단으로 보이는 응답이 `BLOCK_STREAK_THRESHOLD`회 연속되면 슬라이스를 `blocked`로 두고 접습니다.
- 목록 건수(`listed_count`)와 성공 건수가 같고 실패가 없을 때만 슬라이스가 `complete`입니다.

작업 상태는 `succeeded`(모든 슬라이스 완료), `partial`(미완료 슬라이스 남음), `failed`(예기치 못한 중단)입니다.
남은 슬라이스는 `POST /admin/catalog/resume`이나 화면의 "이어하기"로 채웁니다.

## Admin 화면

`http://127.0.0.1:8000/admin` 에서 수집 시작, 슬라이스 완전성 확인, 실패분 재시도를 할 수 있습니다.
처음 열면 토큰 입력 화면으로 이동하며, 입력한 토큰은 HttpOnly 쿠키에 저장됩니다.
기본 수집 기간은 지연 등록·정정 공시를 잡기 위해 최근 7일을 겹쳐 잡습니다.

### 연간 완전성 히트맵

대시보드는 GitHub contribution 그래프처럼 최근 53주 수집 상태를 보고서 유형별로 보여줍니다.

- **초록**: 목록 건수와 성공 건수가 일치하고 실패가 없는 `complete`
- **빨강**: 슬라이스가 있으나 아직 미완성
- **회색**: 슬라이스가 없어 아직 입수하지 않은 날짜

회색 칸을 선택하면 해당 보고서·날짜 수집 폼의 시작일·종료일이 채워지고, 색이 있는 칸을 선택하면
슬라이스 상세로 이동합니다. 항상 표시되는 유형은 `.env`의
`HEATMAP_REPORT_TYPES=A001,F001`로 지정합니다.

월·수·금 요일 라벨과 월 표시가 GitHub 스타일 그리드에 맞춰지며, 창이 좁으면 히트맵 영역만 가로 스크롤됩니다.
30초마다 HTMX로 `/admin/heatmap`을 갱신합니다.

## disclosures backfill

이미 `entries`만 있는 DB에는 한 번 실행합니다.

```bash
.venv\Scripts\python.exe scripts/backfill_disclosures.py
```

수집(`POST /admin/catalog/extract`) 이후부터는 disclosure가 자동 갱신됩니다.

## 엔트리 수집 경로

수집은 Node `@dart-wrapper/entry-extractor`의 CLI 브릿지를 서브프로세스로 호출합니다.
사전에 모노레포 루트에서 `npm install`이 완료되어 있어야 합니다.

## 테스트

```bash
.venv\Scripts\python.exe -m pytest -v
```

테스트는 실제 DART 서버를 호출하지 않습니다(인메모리 SQLite + httpx MockTransport).

## 설정

`.env.example`을 참고해 `.env`를 만듭니다. 개발은 SQLite, 배포는 Neon PostgreSQL을 쓰며 `DATABASE_URL`만 교체하면 됩니다.

Admin 운영 관련 설정은 `ADMIN_TOKEN`, `DISCLOSURE_MAX_RETRIES`, `BLOCK_STREAK_THRESHOLD`, `BLOCK_WAIT_SECONDS`, `HEATMAP_REPORT_TYPES`입니다.
`HEATMAP_REPORT_TYPES`는 히트맵에 고정 표시할 보고서 유형(쉼표 구분, 기본 `A001,F001`)입니다.
