# 수집·열람과 연구 흐름 분리 설계

날짜: 2026-10-10  
상태: 브레인스토밍 승인  
범위: `packages/web-api`를 수집·카탈로그·Viewer로 한정하고, 추출·검토·사이클·업종·Facts는 `packages/research`로 옮긴다. 로컬은 수집을 실행하고, 공개 서버는 카탈로그 조회와 Viewer만 제공한다.  
구현 계획이 아니라 **프로세스·모듈·DB·기동·오류·테스트 경계**다.

## 1. 목표

저장소는 하나다. 실행되는 앱은 둘이고, 연구 코드는 그 둘의 import 밖에 둔다.

성공 기준:

- 로컬 진입점은 수집 Admin, `/catalog`, 공개 목록 API, Viewer, `/health`를 제공한다.
- 공개 진입점은 `/catalog`, 공개 목록 API, Viewer, `/health`만 제공한다.
- 두 진입점 모두 `packages/research`를 import하지 않는다.
- 로컬 수집과 공개 열람은 같은 PostgreSQL의 카탈로그 테이블을 본다. 원문 HTML은 저장하지 않고, Viewer는 요청 때 DART에서 가져온다.
- 연구 테이블은 그대로 남는다. 두 앱의 기동은 그 테이블을 만들거나 고치거나 지우지 않는다.
- 카탈로그 테이블과 `dart_catalog.db` 파일도 지우지 않는다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 제품 범위 | 수집, 카탈로그 조회, Viewer |
| 연구 흐름 | 추출, 검토, 사이클, 회사 업종, Facts. 코드와 테이블은 남기고 실행하지 않는다 |
| 패키지 | `packages/web-api`, `packages/entry-extractor`, `packages/research` |
| import | research가 web-api를 import할 수 있다. web-api는 research를 import하지 않는다 |
| 세 번째 앱 | 연구 라우트까지 올리는 통합 앱은 두지 않는다 |
| 로컬 | 수집 Admin과 읽기 경로. Node 수집기를 붙인다 |
| 공개 | Render 웹 서비스. 읽기 경로만. `0.0.0.0:$PORT` |
| DB | 운영은 공유 PostgreSQL. 테스트는 임시 SQLite |
| 원문 | Lazy Retrieval. 본문은 DB에 쓰지 않는다 |
| 요청 간격 | 프로세스 안의 연속 요청만 1초. 로컬 수집과 공개 Viewer는 시계를 공유하지 않는다 |
| 과거 spec | `docs/superpowers/`의 추출·검토·사이클 문서는 당시 기록으로 둔다. 이 스펙이 지금 실행 범위를 대체한다 |

회사 업종(OpenDART)과 감사보고서일 LLM은 연구 흐름이다. web-api 설정에 키를 두지 않는다.

## 3. 프로세스

| 자리 | 역할 |
|------|------|
| `packages/entry-extractor` | 지금과 같은 Node 수집기. 로컬 수집만 호출한다. 동작은 바꾸지 않는다 |
| `packages/web-api` | 카탈로그와 Viewer. 진입점이 둘이다 |
| `packages/research` | 추출, 검토, 사이클, 업종, Facts. 어느 진입점도 불러오지 않는다 |

로컬 모듈은 `app.local:app`이다. 수집 Admin(`/admin`, `/admin/catalog`), 카탈로그 HTML(`/catalog`, `/catalog/{rcp_no}`), 공개 목록 API(`/api/v1/catalog/disclosures`, 단건, entry 목록), Viewer(`/api/v1/viewer/{rcp_no}`, 섹션 단건), `/health`를 올린다. Node 수집기, `ADMIN_TOKEN`, DART HTTP가 있다.

공개 모듈은 `app.public:app`이다. 카탈로그 HTML, 공개 목록 API, Viewer, `/health`만 올린다. DART HTTP는 열람용이다. `/admin`, `/admin/extract`, `/admin/reviews`, `/admin/cycle`, `/admin/corps`, `/facts`, `/api/v1/facts`는 이 프로세스에 없다. Node, OpenDART, LLM도 없다. Admin 라우트가 없으므로 토큰이 있어도 공개 서버에서 수집은 시작되지 않는다.

로컬에도 같은 읽기 경로가 있어, 수집하면서 그 자리에서 열람할 수 있다.

## 4. 모듈

### web-api에 남는 것

- 모델: `entries`, `disclosures`, `catalog_jobs`, 작업 로그, `slice_progress`, `disclosure_attempts`
- 서비스: 수집, 카탈로그 조회, 슬라이스 조회, Viewer, DART 잡 잠금
- 어댑터: DART HTTP, Node 수집기
- 정제: `parsing`의 본문 블록·표. Viewer가 쓴다
- 화면·API: 수집 Admin, 카탈로그 HTML, 공개 목록 API, Viewer. 템플릿은 `admin`의 수집 화면과 `catalog`다
- 스크립트: `scripts/backfill_disclosures.py`는 카탈로그 보정으로 남긴다
- 로컬 Admin 메뉴: **수집**만

### research로 옮기는 것

- `extracting`, `reviewing`
- 서비스: 추출, 완전성, 검토, 수집 사이클, 회사 업종, 날짜 해소, facts 조회
- 모델: `audit_report_facts`, 추출 잡과 로그, `extraction_reviews`, `failure_shape_judgments`, `corps`
- 어댑터와 포트: OpenDART, 날짜 LLM, `ports/date_resolver.py`. KSIC 표와 적재 스크립트. 진단 TSV·facts 보내기 스크립트
- 화면·API: 추출, 검토, 사이클, 업종, `/facts`, facts API. 템플릿은 추출·검토·사이클·업종 조각과 `facts`다
- 위 모듈의 테스트

research의 패키지 이름은 `research`다. 내부 import는 `research.*`로 맞춘다. 카탈로그 모델, DART HTTP, `parsing`, `rcept_dt`, `report_types`처럼 web-api에 남는 것은 `app.*` import로 둔다.

`admin/ui.py`는 가른다. 수집 화면과 라우트는 web-api에 둔다. 추출 화면과 회사 업종 패널은 research로 간다.

`app/models/__init__.py`는 카탈로그 모델만 등록한다. `app/api/deps.py`는 모듈을 열 때 추출, Facts, OpenDART, 날짜 LLM을 불러오지 않는다. web-api `Settings`에서 OpenDART·날짜 LLM 필드를 뺀다. 기존 `.env`에 그 키가 남아 있어도 `extra=ignore`로 기동은 된다.

## 5. 공유 DB

운영 DB는 하나다. 로컬 수집과 공개 열람의 `DATABASE_URL`은 같은 PostgreSQL이다. 로컬 SQLite 파일은 테스트와, Postgres를 지정하지 않은 로컬 기동용으로 남는다. 공개 서버는 그 파일을 읽지 않는다.

카탈로그 테이블은 `entries`, `disclosures`, `catalog_jobs`, 작업 로그, `slice_progress`, `disclosure_attempts`다. 로컬 수집만 여기에 쓴다. 공시 한 건의 entry, 공시 행, 시도 결과는 한 트랜잭션으로 커밋된다. 그 커밋 뒤에 공개 서버가 그 공시를 읽는다. 진행 로그와 건수 갱신은 그 트랜잭션과 따로 커밋된다.

공개 프로세스는 카탈로그를 읽기만 한다. Viewer는 `viewer_url`로 DART 원문을 가져오고, DB에 본문을 쓰지 않는다.

같은 DB에 이미 있는 연구 테이블은 그대로 둔다. `audit_report_facts`, 추출 잡과 로그, `extraction_reviews`, `failure_shape_judgments`, `corps`다.

`ensure_schema`는 카탈로그 모델만 `create_all`한다. 열 보정은 카탈로그 열만 한다. 지금 코드 기준으로 그 보정은 `catalog_jobs.mode`와 `entries.ordinal`이다. `audit_report_facts` 열 보정은 research로 옮기고, 두 앱의 기동에서는 호출하지 않는다. `create_all`은 메타데이터에 없는 테이블을 지우지 않으므로, 연구 테이블은 이미 있으면 남고 없으면 생기지 않는다.

이번 작업은 카탈로그를 비우거나 `dart_catalog.db`를 삭제하지 않는다.

## 6. 기동

진입점은 둘이다.

로컬은 `packages/web-api`에서 `uvicorn app.local:app`이다. SQLite 기본값과 PostgreSQL URL을 모두 받는다. 실제 수집은 공개 서버와 같은 Postgres URL을 쓴다. 이 프로세스의 설정은 `DATABASE_URL`, Node 실행 파일, 수집 스크립트 경로, 수집 제한 시간, `ADMIN_TOKEN`, 공시 재시도, 차단 연속 임계값, 차단 대기, 히트맵 유형, DART 조회 제한 시간·재시도·최소 간격이다.

공개는 Render 웹 서비스에서 `uvicorn app.public:app`이다. `0.0.0.0:$PORT`에 붙인다. 이 모듈을 불러울 때 `DATABASE_URL`이 `postgresql+asyncpg://`로 시작하지 않으면 프로세스를 시작하지 않는다. 서버 디스크의 SQLite로 떨어지지 않게 하기 위함이다. 테스트가 라우트만 볼 때는 `create_public_app(settings)`에 SQLite URL을 직접 넘긴다. 그 호출은 `app.public:app`가 아니다. 공개 서비스의 환경 변수는 Postgres `DATABASE_URL`과 DART 조회 제한 시간·재시도·최소 간격이다. Node, Admin 토큰, OpenDART, LLM 키는 넣지 않는다. 의존성은 `postgres` extra(`asyncpg`)를 포함한다.

DART 간격은 프로세스마다 따로다. Python Viewer는 그 프로세스의 `DartHttpClient`가 직전 요청 시각을 기억하고, 섹션은 한 번에 하나씩, 최소 1초 간격으로 가져온다. Node 수집기는 그 프로세스의 `safeGet`이 요청 전에 1초를 쉰다. 로컬과 공개 서버는 이 시계를 공유하지 않는다. `entry-extractor`의 간격 구현은 바꾸지 않는다.

## 7. 오류

읽기 경로의 상태 코드는 로컬과 공개가 같다.

| 상황 | 응답 |
|------|------|
| 카탈로그에 없는 접수번호·섹션 | 404 |
| 목록 cursor가 깨짐 | 400 |
| 섹션 하나에 주소가 없거나 DART 조회·정제가 실패 | 그 섹션의 `error`. 단건 조회는 502 |
| 공시 전체 조회에서 일부 섹션만 실패 | 200. 실패한 섹션만 `error` |
| 공시 전체 조회의 모든 섹션이 실패 | 502 |

DART 4xx는 그 요청을 바로 실패로 둔다. 5xx와 연결 오류는 그 프로세스 안에서 재시도한 뒤 실패한다. 본문은 저장하지 않는다. 메시지는 지금처럼 한국어 JSON `detail`이다. 카탈로그 HTML의 없는 접수 화면은 지금 템플릿을 유지한다.

수집 오류는 로컬 Admin에만 있다.

- 이미 수집이 돌고 있으면 409.
- 토큰이 없거나 다르면 401.
- 공시 한 건은 `skipped`, `succeeded`, `failed`, `blocked` 중 하나로 시도 행에 남고, 다음 공시로 넘어간다.
- 목록을 가져오지 못한 날은 그 슬라이스만 `failed`이고, 다른 날은 계속한다.
- 메시지가 `403`, `429`, `503`, `차단`, `연결`, `Connection`, `Timeout`, `시간 초과`를 포함하면 `blocked`다. 연속으로 `BLOCK_STREAK_THRESHOLD`를 넘으면 그 슬라이스를 `blocked`로 두고 `BLOCK_WAIT_SECONDS`만큼 쉰 뒤, 작업을 `partial`로 마친다. 이어하기는 재개다.
- 예기치 못한 오류만 작업 전체를 `failed`로 둔다.
- 중단 요청은 다음 공시 경계에서 멈추고 `partial`로 남긴다.

공개 서버의 응답에는 409, 401, 차단 연속 중단이 없다. 연구 잡의 오류는 `packages/research`에 남는다.

## 8. 문서

구현할 때 살아 있는 문서를 이 경계에 맞춘다.

- 루트 `README.md`, `PRD.md`, `packages/web-api/README.md`는 수집, 카탈로그 조회, Viewer, 로컬 기동, 공개 기동만 적는다.
- `docs/collection-cycle.md` 맨 위에, 사이클 구현은 `packages/research`에 있고 두 앱은 그것을 제공하지 않는다고 적는다. `지금 앱에서 하는 일` 표는 그 문단으로 대체한다. 단계·분류 절차 본문은 유지한다.
- `AGENTS.md`에 기본 앱의 범위는 수집·열람이고, 추출기 버전·로직 메모 규칙은 `packages/research`를 다룰 때 적용한다고 적는다.
- 과거 spec·plan 본문은 고치지 않는다. 색인 한 줄은 이 스펙과 함께 들어가 있다.

## 9. 테스트

통과 기준은 `packages/web-api`에서 돌리는 기존 pytest다. DB는 임시 SQLite이고, DART와 Node에는 접속하지 않는다.

새로 고정하는 동작:

- 로컬 앱 라우트에 수집 Admin, `/catalog`, 공개 목록 API, Viewer, `/health`가 있다.
- 공개 앱 라우트에 `/catalog`, 공개 목록 API, Viewer, `/health`만 있다. 수집, 추출, 검토, 사이클, 업종, Facts 경로는 없다.
- `app.public:app`에 해당하는 가드는 SQLite URL에서 기동을 거부하고, `postgresql+asyncpg://` URL은 통과한다.
- 그 테스트가 `research`를 먼저 import하지 않은 상태에서 로컬 앱과 공개 앱을 만든 뒤 `sys.modules`에 `research`가 없다.
- 기동 스키마의 테이블 이름은 카탈로그뿐이고, `audit_report_facts` 열 보정을 호출하지 않는다.

이미 있는 수집, 카탈로그, Viewer, 정제, DART HTTP 테스트는 web-api에 남고 통과해야 한다. 추출, 검토, 사이클, 업종, Facts 테스트는 research로 옮긴다. web-api의 기본 pytest는 그 테스트를 수집하지 않는다. research 테스트의 import는 `research.*`와 `app.*`로 맞게 고친다. 이번 작업의 기본 통과 명령은 research pytest를 실행하지 않는다. 연구 동작의 새 테스트는 추가하지 않는다. `entry-extractor` 테스트는 그대로 둔다.

## 10. 하지 않는 것

- 연구 기능을 삭제하거나 연구 테이블을 DROP하지 않는다.
- 카탈로그를 비우지 않는다.
- 추출 칸의 수집·조립·집계를 한 단위로 다시 묶지 않는다.
- 공용 카탈로그 라이브러리 패키지를 web-api에서 따로 빼지 않는다.
- 공개 Viewer가 정제 결과를 저장하게 바꾸지 않는다.
- 로컬과 공개 사이의 요청 간격을 한 시계로 묶지 않는다.
- research를 기본 기동, Render 서비스, web-api 기본 테스트에 넣지 않는다.
