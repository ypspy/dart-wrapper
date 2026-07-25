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

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/admin/catalog/extract` | 기간/기업별 수집 트리거 (202, `job_id` 반환) |
| GET | `/admin/catalog/status?job_id=` | 수집 현황·로그 |
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
