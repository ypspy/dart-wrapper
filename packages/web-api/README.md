# web-api

DART 공시 파이프라인의 FastAPI 서비스입니다. Admin 카탈로그 수집과 Public Viewer(Lazy Retrieval)를 제공합니다.

## 구조

| 레이어 | 위치 | 역할 |
|--------|------|------|
| API | `app/api` | 라우터·의존성 |
| Service | `app/services` | 수집 오케스트레이션, Viewer 파이프라인, 감사 추출 잡 |
| Extracting | `app/extracting` | 감사 표지·의견·실시내용·첨부 제표 계정·내부회계·계속기업·종속기업 순수 추출·해소 (`audit_opinion.v17`) |
| Port/Adapter | `app/ports`, `app/adapters` | 엔트리 수집기, DART HTTP |
| Parsing | `app/parsing` | 본문 정제, 표 → JSON |
| DB | `app/models`, `app/repositories`, `app/db` | 엔트리·작업 메타데이터 |

DB에는 entry 메타데이터만 저장하고, 본문·표는 조회 시점에 `viewer_url`로 가져옵니다.

## 설치

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

PostgreSQL로 배포할 때는 `.venv\Scripts\python.exe -m pip install -e ".[postgres]"`를 추가합니다.

## 실행

`packages/web-api` 디렉터리에서 실행합니다. PowerShell은 `.\.venv\...`처럼 **`.\` 접두사**가 필요합니다.

```powershell
cd packages/web-api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
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
| POST | `/admin/extract/audit-opinion` | 감사 표지·의견 추출 트리거 (202, `job_id`) |
| GET | `/admin/extract/status?job_id=` | 추출 작업 현황·로그 |
| POST | `/admin/extract/jobs/{job_id}/soft-stop` | 다음 접수 경계에서 추출 중단 |
| POST | `/admin/extract/jobs/{job_id}/force-finish` | 멈춘 추출 잡 강제 종료(DART 잠금 해제) |
| GET | `/admin/extract/audit-opinion/completeness` | 기간·유형별 추출 완전성 집계 |
| POST | `/admin/corps/enrich` | 빠진 회사 OpenDART 개황 채우기 (202, `job_id`) |
| GET | `/admin/corps/status?job_id=` | 회사 업종 잡 현황·로그 |
| GET | `/admin/corps/summary` | 공시 distinct / ok / 남음 |
| POST | `/admin/corps/jobs/{job_id}/soft-stop` | 다음 회사 경계에서 중단 |
| POST | `/admin/corps/jobs/{job_id}/force-finish` | 강제 마감 |
| PATCH | `/admin/extract/audit-opinion/{rcept_no}/{dcm_no}/date` | 감사보고서일 수동 보정 |
| POST | `/admin/extract/resolve-dates` | ambiguous 감사보고서일 LLM 해소 |
| GET | `/api/v1/catalog/disclosures` | 공시 목록 (cursor 페이지네이션) |
| GET | `/api/v1/catalog/disclosures/{rcp_no}` | 공시 단건 요약 |
| GET | `/api/v1/catalog/disclosures/{rcp_no}/entries` | entry 목록 (전 feature, `all_entries`) |
| GET | `/api/v1/facts` | 감사 추출 결과 목록 (인증 없음, cursor) |
| GET | `/api/v1/disclosures/{rcp_no}/audit-facts` | 공시별 감사 추출 결과 (인증 없음) |
| GET | `/api/v1/viewer/{rcp_no}` | 접수번호의 모든 entry 섹션 원문 (종합 분석용) |
| GET | `/api/v1/viewer/{rcp_no}/sections/{entry_id}` | 특정 entry 섹션 원문 (단건 조회) |
| GET | `/facts` | 추출 문서 납작 표 (조인 메타 + facts 공개 컬럼). `rcept_no`는 Catalog 링크 |
| GET | `/catalog` | 공시 목록 표 (`DisclosureSummary` 전 컬럼). `disclosure_url`은 「원문」 링크(새 탭) |
| GET | `/catalog/{rcp_no}` | 공시 메타 + entry 표. `disclosure_url`「원문」·`viewer_url`「viewer」 링크. attachment는 `rcpNo`+`dcm_no`로 해당 문서 main.do에 연결 |

목록 쿼리: `corp_code`, `corp_name`, `report_nm`, `report_type`, `start_date`, `end_date`, `limit`(1–100), `cursor`.
총건수는 반환하지 않으며, 다음 페이지는 `next_cursor`로 이어갑니다.

`all_entries`는 `ordinal` 순 entry이며, entry-extractor 스키마와 같은 feature
(`viewer_url`, `path`, `is_leaf`, 공시 features 등)를 담습니다. 응답의 `disclosure`에는
공시 메타(`correction_type`, `submitter`, `year_end`, `bsns_year` 포함)가 들어 있습니다.
`entry_id`로 Viewer 단건 조회에 바로 이어갈 수 있습니다.

수집기는 Node entry-extractor 기본값을 따릅니다(목록 이력 포함·첨부 접수 스코프·TOC 중간 노드 포함).
상세는 [`../entry-extractor/README.md`](../entry-extractor/README.md)를 보세요.

전체 Viewer 조회는 일부 섹션이 실패하면 해당 섹션에만 `error`를 담고 나머지는 정상 반환합니다. 모든 섹션이 실패하면 502입니다.

## 감사보고서 추출

카탈로그에 있는 `viewer_url`로 감사 표지·의견 5필드(감사인, 의견, 보고일, GAAP, 당기)를
뽑아 `audit_report_facts`에 저장합니다. 같은 행에 외부감사 실시내용 1~4절 JSON
(`hours`, `activities`, `communications`)과 첨부 제표 계정 JSON(`accounts`)도 붙입니다.
같은 행에 내부회계관리제도 감사·검토 의견(`icfr_engagement`, `icfr_opinion_code`, `icfr_status`)과
당기 계속기업 중요한 불확실성(`going_concern`, 적정 의견의 제목·강조사항만)·연결 종속기업 수(`subsidiary_count`)도 붙입니다.
`accounts`에는 부채총계(`total_liability`) 당기·전기 금액도 포함합니다.
별도 문서(`fs_scope=separate`)의 종속기업 수는 `subsidiary_status=not_applicable`이며 카운트는 null입니다.
연결 문서는 주석 표를 1차로 세고, 같은 접수 A001 계열회사 표에서 종속 구분 칸을 읽을 수 있을 때만 2차로
보강합니다. 감사는 적정·부적정·거절, 검토는 거기에 한정·중요한취약점입니다. 회사 운영보고서는 읽지 않습니다.
5절(중요성 금액)은 추출하지 않습니다. 추출기 버전은 `audit_opinion.v17`입니다.
원문 HTML은 저장하지 않습니다. 추출 전용 히트맵 UI는 없습니다. 완전성은 아래 집계 API로 확인합니다.

카탈로그 수집과 추출 잡은 둘 다 DART를 치므로 **한 프로세스에서 동시에 돌리지 않습니다.**
날짜 LLM 해소는 DART를 쓰지 않아 수집과 병행할 수 있습니다.

대상은 F001·F002와 A001 첨부 감사·연결감사입니다. 저장 단위는 문서 하나(`rcept_no`+`dcm_no`)이고,
정정 전·후 접수는 각각 행입니다.

### 버전과 재추출

| 모드 | 동작 |
|------|------|
| `extract` / `resume` | 같은 버전이고 `fetch_status=ok`인 행은 건너뜁니다 |
| `reparse` | `fetch_status=ok`여도 필드가 `not_found`이면 다시 fetch합니다. override·LLM 보고일은 유지합니다 |

버전을 올리지 않은 규칙 변경(아래 목록 감사인 최후 해소 등)은 `extract`만으로는 기존 `ok` 행에
반영되지 않습니다. 감사인만 비어 있는 행은 `reparse`로 다시 넣습니다.

### 필드 해소

**감사인** (`auditor_source`)

1. 표지 D-2-2 (`cover`). compact 텍스트에 한글 `회계법인`/`감사반`이 있을 때만 채택합니다. 한자 상호(`會計法人` 등)는 표지에서 잡지 않습니다.
2. A001만 「1. 외부감사에 관한 사항」 당기 칸 (`a001`)
3. 의견 본문 D-3-1 사전 (`body`)
4. F001·F002만, 표지·본문을 **읽었는데** 둘 다 `not_found`이고 목록 `submitter`가 비어 있지 않을 때 (`listing`). `normalize_firm_name`을 적용합니다.

문서 출처(1–3)가 하나라도 `ok`이면 listing은 쓰지 않고, auditor `conflicts`에도 넣지 않습니다.
문서를 읽지 못한 `skipped`(captcha·섹션 없음 등)에도 listing을 쓰지 않습니다.
A001 목록 `submitter`는 회사명이라 감사인 해소에 쓰지 않습니다.
F001·F002 listing은 **현재 상호**일 수 있습니다. `auditor_listing`에는 항상 그 이름을 남기고,
resolved에 쓰는 것은 4순위일 때뿐입니다.

**의견** — 의견서 본문이 `ok`이면 그것을 쓰고, 없으면 A001 당기 칸입니다. 둘이 달라도 코드는 의견서를 유지하고 `conflicts`만 남깁니다.

**보고일** — 의견서에서 후보를 모은 뒤 `period_end < iso ≤ rcept_dt`를 통과한 값이 하나면 ISO, 여러 개면 `ambiguous`(ISO는 null). 후보는 `{date, snippet}`으로 저장합니다. 수동 보정과 LLM 해소는 아래 API입니다.

### 의견 서식 (v3)

2018년 감사기준서 700 전후 서식을 compact 본문으로 가릅니다. 접수일·자산 규모로 가르지 않습니다.

- **선행형**(의견·근거가 앞): `재무제표감사에대한보고` / `핵심감사사항` / `감사의견근거`가 있으면 그 표지 **앞**만 검색합니다. 강조사항의 과거 거절 인용이 당기 의견으로 잡히지 않게 합니다.
- **후행형**(종전): 선행 표지가 없고 `경영진의책임` 뒤에 한정·거절·부적정 근거가 있으면 **전문**에서 D-3-2 키워드를 찾습니다. 표지를 앞에서 자르면 근거 단락이 창 밖으로 나갑니다.
- 구간 안에서도 `일자로발행한감사보고서에서` / `비교표시목적으로` 인용(±80자)은 무시합니다.

의견 분류에 LLM을 쓰지 않습니다. 키워드 튜플은 옛 D-3-2를 유지합니다.

### Admin 추출

운영 화면 `/admin/extract`에서 연구 창 완전성(F001/F002/A001)과 추출 잡을 봅니다.
JSON 트리거(`POST /admin/extract/audit-opinion`)는 그대로입니다.

`POST /admin/extract/audit-opinion`에 기간·유형·모드를 보냅니다.

```json
{
  "start_date": "20200301",
  "end_date": "20200331",
  "report_types": ["F001", "F002", "A001"],
  "mode": "extract"
}
```

`mode`는 `extract`(신규), `resume`(행 없음·fetch 실패 재시도), `reparse`(필드 `not_found` 재파싱)입니다.
바로 `job_id`를 돌려주고 실제 추출은 백그라운드에서 진행됩니다.
현황은 `GET /admin/extract/status?job_id=`로 봅니다.
워커가 살아 있으면 `POST /admin/extract/jobs/{job_id}/soft-stop`으로 다음 접수에서 멈춥니다.
프로세스가 죽은 채 `pending`/`running`이면 `force-finish`로 잠금을 풉니다.

감사보고서일만 손으로 고치려면
`PATCH /admin/extract/audit-opinion/{rcept_no}/{dcm_no}/date`에 `{"iso": "2020-02-20"}`를 보냅니다.

### 완전성

`GET /admin/extract/audit-opinion/completeness?start_date=&end_date=&report_type=`
한 유형의 기간 집계입니다. 문서 단위는 `rcept_no`+`dcm_no`입니다.

| 키 | 의미 |
|----|------|
| `target` | selector가 고른 대상 문서 수 |
| `ok` | `fetch_status=ok` |
| `fetch_failed` / `blocked` / `section_missing` | 해당 fetch 상태 |
| `unextracted` | 대상인데 facts 행이 없음 |
| `ambiguous_dates` | `audit_report_date_status=ambiguous` |
| `field_partial` | fetch는 됐지만 핵심 필드(의견 5필드·실시내용 3상태·`accounts_status`·`icfr_status`·`going_concern_status`) 중 `ok`가 아닌 것이 있음. 연결 문서의 `subsidiary_status`는 `skipped`/`not_found`만 부분실패이며 `not_applicable`은 아님 |

같은 경로에 `status`와 `cursor`/`limit`을 주면 해당 문서 식별자 목록을 받습니다.
4절이 없는 옛 공시는 의견 필드가 `ok`여도 `communications_status=not_found`라 `field_partial`입니다.
첨부 제표에서는 E-4 연구 계정 8개(자산총계·자본총계·당기순손익·재고·매출채권·장기매출채권·계약자산·미청구공사)와
유동자산·유동부채·부채총계(`total_liability`)의 당기·전기 금액을 읽으며, `제N기` 비교열 헤더는 큰 기수를 당기·작은 기수를 전기로 해석합니다.
`당기순손실` 과목은 칸 괄호가 없어도 음수로 읽습니다.
`비유동`·`기타` 과목과 `유동화부채`는 유동 소계로 쓰지 않습니다. `부채와자본총계`는 부채총계로 쓰지 않습니다.

### 필드 묶음 모니터

`/admin/extract` 왼쪽 문서 카드 아래에 현재 추출기 `fetch_status=ok` 행의 12묶음
(감사인·의견·GAAP·감사보고서일·당기·감사시간·실시항목·커뮤니케이션·계정·내부회계·계속기업·종속기업)
성공 / 해당없음 / 제도상없음 / 실패를 보여 줍니다. 성공률은 `성공/(성공+실패)`입니다.

- 별도·unknown 문서의 종속기업 `not_applicable`은 해당없음(분모 제외)
- 실시내용 1–3절 ok이고 4절만 `not_found`이면 커뮤니케이션은 제도상없음
- 구버전·미추출·fetch 실패는 이 표에 넣지 않습니다 (문서 카드)

JSON: `GET /admin/extract/audit-opinion/field-bundles`, 실패 목록
`.../field-bundles/items?bundle=&outcome=fail`, TSV
`.../field-bundles/export` (최대 5000행, `X-Next-Cursor`).
실행 중 잡은 `params.field_bundles`에 이번 처리분만 가산합니다.

### Public 조회

`GET /api/v1/disclosures/{rcp_no}/audit-facts`는 인증 없이 해당 접수의 추출 행을 반환합니다.
행이 없으면 404가 아니라 빈 목록입니다. 실시내용·계정 JSON과 `hours_status`·`accounts_status`
·`icfr_engagement`·`icfr_opinion_code`·`icfr_status`·`going_concern`·`subsidiary_count`·
`subsidiary_status` 등도 본문에 포함합니다.
회사명·접수일 등은 facts에 없고, 아래 export가 `entries`/`disclosures`와 조인합니다.

`GET /api/v1/facts` 목록에도 같은 공개 컬럼(`going_concern`, `subsidiary_count` 등)이 포함됩니다.

### DATE_RESOLVER

ambiguous 감사보고서일은 `POST /admin/extract/resolve-dates`로 LLM이 후보 인덱스를 고릅니다.
설정은 `.env`의 `DATE_RESOLVER_API_KEY`, `DATE_RESOLVER_MODEL`(기본 `gpt-4o-mini`),
`DATE_RESOLVER_PROMPT_VERSION`(기본 `v1`)입니다. API 키가 비어 있으면 400입니다.

### CSV/TSV export

연구용 TSV는 facts와 카탈로그를 조인해 회사명·결산월·접수일·정정구분을 붙입니다.
정정 전·후 접수를 모두 넣으며, 최종 접수만 남기는 플래그는 없습니다.
`correction_type`과 `rcept_dt`로 고르면 됩니다.

`packages/web-api`에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe scripts/export_audit_report_facts.py
.\.venv\Scripts\python.exe scripts/export_audit_report_facts.py --out facts.tsv
.\.venv\Scripts\python.exe scripts/export_audit_report_facts.py --database-url sqlite+aiosqlite:///./dart_catalog.db --out facts.tsv
```

`--database-url` 기본값은 앱 `DATABASE_URL`과 같고, `--out`이 없으면 표준 출력으로 씁니다.

## 회사 업종 (OpenDART)

공시 HTML 수집·감사 추출과 달리, 회사 마스터 보강만 [OpenDART 기업개황 API](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019002)
(`GET /api/company.json`)를 씁니다. `.env`의 `OPENDART_API_KEY`가 없으면 잡을 시작하지 않습니다.
대상은 `disclosures`에 있는 distinct `corp_code`이며, `fetch_status=ok`인 회사는 건너뜁니다.
수집·감사 추출의 `dart_job_lock`과 **공유하지 않아** 동시에 돌릴 수 있습니다.

`POST /admin/corps/enrich`로 잡을 등록하면 202와 `job_id`를 받고, 현황은
`GET /admin/corps/status?job_id=`·집계는 `GET /admin/corps/summary`로 확인합니다.
운영 화면 `/admin` 오른쪽 **회사 업종** 칸에서 공시 회사 수·완료·잔여와 「빠진 회사 채우기」 버튼을 제공합니다.
HTML 폼은 `POST /admin/corps/start`(303)이고, JSON API와 경로를 나눕니다.

## 본문 정제 (blocks)

Viewer 응답의 각 섹션은 문서 순서의 `blocks[]`를 담습니다. 블록 종류는 `heading`
(`level` 1–3), `paragraph`, `table`(`headers`/`rows`) 세 가지입니다. 원문을 한 번만
파싱해 `blocks`·`text`·`tables`를 함께 만들며, 하위호환 필드인 `text`에는 **표 내용을 넣지
않습니다**(표는 `tables` 또는 `table` 블록으로만 제공).

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
- **오른쪽(실행 컨트롤)**: 최근 작업 상태 카드(항상 표시) → **회사 업종** 패널(공시 distinct 회사 수·완료·잔여, 「빠진 회사 채우기」) → 수집 폼(기본 접힘) → 로그
- **상단 유형 칩**: `HEATMAP_REPORT_TYPES`(기본 `A001,A002,A003,F001,F002,F004`)를 눌러 보고서 유형을 전환합니다.
  칩에는 코드와 한국어 명칭(A001 사업보고서, A002 반기보고서, A003 분기보고서, F001 감사보고서,
  F002 연결감사보고서, F004 회계법인사업보고서)이 함께 나옵니다.

창이 좁으면(1100px 미만) 두 열이 세로로 쌓입니다.

수집 작업은 uvicorn 프로세스 안에서 돌아가므로, PC가 절전(슬립)되면 작업도 멈춥니다.
절전 없이 오래 돌리거나, 나중에 별도 워커로 분리하는 편이 안전합니다.
한 번에 하나의 수집·재개만 허용합니다. 다른 작업이 `pending`/`running`이면
새 시작은 409로 거절되고 Admin 화면의 시작 버튼도 비활성화됩니다.

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
해당 유형·날짜를 채웁니다(`?expand_form=1`). 수집 폼의 공시 유형은 선택 목록으로 제공합니다.
항상 표시하는 유형은 `.env`의 `HEATMAP_REPORT_TYPES`로 지정합니다.

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
`HEATMAP_REPORT_TYPES`는 히트맵·유형 토글에 고정 표시할 보고서 유형(쉼표 구분, 기본 `A001,A002,A003,F001,F002,F004`)입니다.
코드별 한국어 명칭은 `app/report_types.py`에 있으며, 목록에 없는 코드는 코드 그대로 표시합니다.

감사보고서일 LLM 해소는 `DATE_RESOLVER_API_KEY`, `DATE_RESOLVER_MODEL`, `DATE_RESOLVER_PROMPT_VERSION`입니다.
키가 비어 있으면 `POST /admin/extract/resolve-dates`는 시작하지 않습니다.

회사 업종 보강은 `OPENDART_API_KEY`입니다. 키가 비어 있으면 `POST /admin/corps/enrich`와 Admin 「빠진 회사 채우기」가 시작되지 않습니다.
