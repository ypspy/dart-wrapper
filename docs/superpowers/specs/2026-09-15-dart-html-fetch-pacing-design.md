# DART HTML 요청 간격 공유 설계

날짜: 2026-09-15  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` — 추출과 Viewer가 **같은 DART HTML GET 줄**을 써서
집 IP 차단을 줄인다.  
구현 계획이 아니라 **클라이언트 수명·간격·동시성·실패 정책·테스트 경계**다.

선행: 추출 Admin [`2026-09-11-extract-admin-monitor-design.md`](2026-09-11-extract-admin-monitor-design.md).
카탈로그 수집(Node `safeGet`)과 OpenDART 한도는 이번 범위가 아니다.

## 1. 목표

운영자가 연구 창 추출을 **막히지 않을 만큼 천천히** 돌릴 수 있다.
Public Viewer로 공시를 열어봐도 추출 간격을 깨지 않는다.

성공 기준:

- 프로세스 안 DART HTML GET(추출 원문 + Viewer 섹션)이 **하나의** `DartHttpClient`를 지난다.
- 연속 GET 시작 시각 간격은 `DART_FETCH_MIN_INTERVAL_SECONDS`(기본 **1초**) 이상이다.
- Viewer는 한 접수의 여러 섹션을 **동시에 4개** 치지 않는다 (`concurrency=1`).
- 한 문서 `fetch_failed`여도 잡은 **다음 문서로 진행**한다.
- Live DART 호출 테스트는 없다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 정책 | 요청을 천천히 보낸다. 연결 끊김·`fetch_failed`로 잡을 멈추지 않는다 (선택 A) |
| 게이트 | `app.state`의 `DartHttpClient` **하나**. 추출·Viewer가 공유 |
| 간격 | `DART_FETCH_MIN_INTERVAL_SECONDS`, 기본 `1.0`. 수집기 `safeGet delayMs=1000`과 맞춤 |
| Viewer 동시성 | `1`. 같은 락 앞에서 4개를 세워 두는 것은 무의미 |
| 403/429·캡차 | 기존과 같음. `blocked` 연속 `BLOCK_STREAK_THRESHOLD`(5)면 60초 뒤 잡 중단 |
| 수집 vs 추출 | 기존 `dart_job_lock` 유지. 수집기는 별도 Node 프로세스라 Python 락을 공유하지 않음 |
| 패키지 | `packages/web-api` |

1차에 **안 넣는 것:** 수집기 User-Agent를 브라우저로 바꾸기, 연속 `fetch_failed`/연결 종료로 잡 중단, 기본 간격을 2초로 올리기, OpenDART 분당 한도 변경, 새 Admin 화면.

## 3. 구성

`lifespan`에서 `httpx.AsyncClient`(기존 브라우저형 User-Agent·Referer)로 `DartHttpClient`를 만들고 `app.state.dart_http`에 둔다.

- `timeout_seconds` / `max_retries` / `min_interval_seconds`는 `Settings`에서 읽는다.
- `get_extraction_service`는 요청마다 새 `DartHttpClient`를 만들지 않고 `app.state.dart_http`를 쓴다. 잡 싱글톤은 지금처럼 `app.state.extraction_service`에 둔다.
- `get_viewer_service`도 `app.state.dart_http`를 쓰고, `ViewerService(..., concurrency=1)`이다.
- 테스트·스크립트가 `DartHttpClient(...)`를 직접 만드는 것은 허용한다. 기본 `min_interval_seconds`는 클래스에서 `0.0`으로 남겨 단위 테스트가 빨라야 한다. **앱 배선만** 설정값 1초를 넣는다.

간격 락은 인스턴스 필드(`_pace_lock`, `_last_request_at`)다. 공유 인스턴스가 곧 프로세스 게이트다.

## 4. 흐름

1. 추출 `_extract_document`가 leaf `viewer_url`마다 `fetch_html`을 순차로 호출한다.
2. Viewer `get_disclosure` / `get_section`도 같은 `fetch_html`을 호출한다.
3. `fetch_html`은 직전 GET **시작** 시각으로부터 최소 간격만큼 쉰 뒤 GET한다. 재시도 횟수마다 간격 대기를 다시 탄다.
4. Admin 추출 화면의 HTMX 폴링(잡 현황 5초, 완전성 60초)은 DB만 치며 DART를 치지 않는다.

카탈로그 수집은 Node `safeGet`(요청 전 1초, UA `dart-wrapper/0.1`)이다. 이 스펙은 그 프로세스를 바꾸지 않는다. 수집과 추출을 동시에 켜지 않는 잠금은 그대로다.

## 5. 실패 정책

| 상황 | 동작 |
|------|------|
| 네트워크 오류·타임아웃·5xx | 기존처럼 재시도 후 `SourceFetchError` → 문서 `fetch_failed`, **다음 문서** |
| HTTP 403/429 | `blocked`. 연속 임계값이면 기존처럼 잡 중단 |
| 캡차성 HTML | 기존 `html_looks_blocked` |
| Viewer 섹션 실패 | 기존처럼 해당 섹션 `error`, 다른 섹션은 계속. 다만 동시 4개가 아니라 1개씩 |

연결이 바로 끊겨도 연속 `fetch_failed`로 잡을 멈추지 않는다. 운영자는 소프트 스톱으로 멈춘다.

## 6. 테스트

워킹 디렉터리 `packages/web-api`, `.\.venv\Scripts\python.exe -m pytest …`. Live DART 없음.

- 앱(또는 deps)이 Viewer·추출에 **같은** `DartHttpClient` 인스턴스를 넘기는지.
- Viewer `concurrency == 1`.
- `DartHttpClient` 간격 테스트는 기존 `test_fetch_html_waits_min_interval_between_requests` 유지.
- 추출 서비스 테스트는 지금처럼 간격 0 클라이언트를 직접 넣어도 된다 (속도).

## 7. README

Admin/추출 절에 한 줄: 추출·Viewer 원문 GET은 기본 1초 간격이며 `DART_FETCH_MIN_INTERVAL_SECONDS`로 바꾼다. Viewer는 섹션을 한 번에 하나 가져온다.
