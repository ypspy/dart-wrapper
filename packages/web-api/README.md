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

`http://127.0.0.1:8000/admin` 은 좌우 2열 운영 콘솔입니다.
처음 열면 토큰 입력 화면으로 이동하며, 입력한 토큰은 HttpOnly 쿠키에 저장됩니다.

- **왼쪽(완전성 탐색)**: 연도 요약 바 → 선택 연도의 일별 히트맵 → 선택 연도 슬라이스 요약
- **오른쪽(실행 컨트롤)**: 최근 작업 상태 카드(항상 표시) → 수집 폼(기본 접힘) → 로그
- **상단 유형 칩**: `HEATMAP_REPORT_TYPES`(기본 `A001,F001,F002`)를 눌러 보고서 유형을 전환합니다.

창이 좁으면(1100px 미만) 두 열이 세로로 쌓입니다.

수집 작업은 uvicorn 프로세스 안에서 돌아가므로, PC가 절전(슬립)되면 작업도 멈춥니다.
절전 없이 오래 돌리거나, 나중에 별도 워커로 분리하는 편이 안전합니다.

### 연도 요약 바

1999년(또는 가장 오래된 슬라이스 연도)부터 올해까지 한 해에 막대 하나를 그립니다.
그 해에 미완료 슬라이스가 하나라도 있으면 빨강, 모두 완료면 초록, 슬라이스가 없으면 회색입니다.
막대를 누르면 `?year=`가 붙어 아래 히트맵과 슬라이스 요약이 그 해로 바뀝니다.
기본 선택은 가장 최근 미완성 연도이고, 없으면 올해입니다.

### 선택 연도 히트맵

GitHub contribution 그래프와 같은 날짜×요일 격자를 선택한 연도 한 해에 대해 그립니다.
창은 1월 1일이 속한 주의 일요일부터 12월 31일이 속한 주까지이며,
**한국 시간(UTC+9) 기준 당일은 미도래(투명)** 로 두고 다음 날 0시가 지난 뒤에야 엽니다.
일중 공시 누락을 막기 위한 규칙입니다.

- **초록**: 목록 건수와 성공 건수가 일치하고 실패가 없는 `complete`
- **빨강**: 슬라이스가 있으나 아직 미완성
- **회색**: 슬라이스가 없어 아직 입수하지 않은 날짜

완료 칸은 슬라이스 상세로 이동하고, 미완성·미입수 칸은 오른쪽 수집 폼을 펼치면서
해당 유형·날짜를 채웁니다(`?expand_form=1`). 항상 표시하는 유형은 `.env`의
`HEATMAP_REPORT_TYPES=A001,F001`로 지정합니다.

### 작업 카드와 로그

상태 카드는 최근 작업의 상태·진행률·기간·저장 건수를 보여주고, 진행 중이면 깜빡이는 표시와 소프트 스톱 버튼을 노출합니다.
작업 이력이 없으면 "대기 중"으로 표시합니다. 로그는 실행 중일 때 `info/warn/error`, 대기 중일 때 `warn/error`를 보여줍니다.

HTMX가 작업 카드·로그·슬라이스 요약·히트맵은 5초, 연도 바는 60초마다 갱신합니다.

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
