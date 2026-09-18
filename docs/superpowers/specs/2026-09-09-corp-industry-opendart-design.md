# 회사 마스터 업종 보강 (OpenDART 기업개황) 설계

날짜: 2026-09-09  
상태: 승인 (구현)  
범위: `packages/web-api` — `corps` 테이블에 공시 distinct `corp_code`의 현재 업종·식별자를
붙이고, Admin에서 빠진 회사만 채우는 잡을 돌린다.  
구현 계획이 아니라 **아키텍처·스키마·OpenDART 계약·잡/Admin UI·테스트 경계**다.

선행: 카탈로그는 `disclosures`/`entries`에 `corp_code`를 중복 저장한다. 회사 마스터 테이블은
없다. 공시 HTML은 OpenDART를 쓰지 않는다
([AGENTS.md](../../../AGENTS.md)). 이번만 [기업개황 API](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019002)
(`GET /api/company.json`)를 **보강 예외**로 쓴다.

## 1. 목표

DB에 이미 있는 회사마다 **현재 스냅샷** 업종 1개를 붙인다. Catalog/Facts 필터와 공시 행
표시는 후속이며, 그때는 `corps`를 `JOIN`한다. 1차는 적재와 Admin 잡뿐이다.

성공 기준:

- `disclosures`의 비어 있지 않은 distinct `corp_code`가 `corps` 후보가 된다.
- 잡은 `fetch_status=ok`를 건너뛰고 미적재·실패만 OpenDART에 넣는다.
- 원문 `induty_code`와 KSIC 10차 이름(있는 계층만), `stock_code`/`corp_cls` 등 식별자가
  회사 1행에 남는다.
- `/admin`에서 문서 수집과 **다른 칸**으로 대상 수·진행을 본다. 단위는 회사다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 저장 단위 | 회사 1행 (`corp_code` PK). 공시·entry에 업종 컬럼을 복제하지 않음 |
| 시점 | 현재 스냅샷만. 업종 이력 없음 |
| 대상 | `disclosures.corp_code` DISTINCT. NULL·빈 문자열 제외. 고유번호 ZIP·상장사 전수 아님 |
| API | OpenDART 기업개황 JSON만. 재무·목록·HTML 스크래핑 아님 |
| 업종명 | API는 코드만 줌. KSIC 제11차 우선·없으면 제10차. 표는 저장소에 고정 |
| 1차 UI | Admin 적재 잡. 회사 목록 HTML·Public API·Catalog/Facts 필터 없음 |
| 실행 | `/admin` 폼 + 전용 Admin API. 카탈로그 종료 후 자동 실행 없음 |
| 모드 | `fill_missing`만. 성공 행 재조회(refresh) 없음 |
| 잠금 | `dart_job_lock`(수집↔감사 추출)과 공유하지 않음. `corp_industry` 잡끼리만 1개 |
| 패키지 | `packages/web-api`. 새 npm 패키지 없음 |

공시 목록의 `corp_name`은 **그 접수 시점 상호**다. `corps.corp_name`은 API 정식명칭(현재
개황)이며, 둘이 달라도 오류가 아니다.

## 3. 아키텍처

공시 스크래핑 파이프라인은 그대로 둔다. 보강은 추출 잡과 같은 층이다.

| 단위 | 역할 | 의존 |
|------|------|------|
| `Corp` 모델 | `corps` 현재 스냅샷 | SQLAlchemy |
| KSIC 로더 | 고정 JSON에서 코드 → 대/중/소/세/세세 이름 | 파일 I/O, 네트워크 없음 |
| `OpenDartCompanyClient` | `company.json` 1호출 | httpx. OpenDART 전용 클라이언트(DART `Referer` 없음) |
| `CorpIndustryService` | 대상 집합, upsert, 잡 수명 | 위 + `ExtractionJobRepository` |
| Admin UI 칸 | 회사 단위 숫자·진행·시작/중단 | 서비스 |

잡은 새 테이블을 만들지 않는다. 기존 `extraction_jobs` / `extraction_job_logs`를 쓰고
`extractor_id=corp_industry`로 가른다. 날짜 LLM 잡(`resolve_dates`)과 같은 재사용이다.

OpenDART HTTP는 앱 수명의 DART 클라이언트와 분리한다. DART 기본 헤더의 `Referer:
https://dart.fss.or.kr/`를 기업개황에 붙이지 않는다.

## 4. 데이터 모델

### 4.1 `corps`

| 컬럼 | 타입 | 출처 | 설명 |
|------|------|------|------|
| `corp_code` | PK, 8자리 | 요청 키 | DART 고유번호 |
| `corp_name` | string null | API 정식명칭 | 현재 상호 |
| `stock_name` | string null | API | 종목명 또는 약칭 |
| `stock_code` | string null | API | 상장 6자리. 비상장은 빈 값 → NULL |
| `corp_cls` | string null | API | `Y` 유가, `K` 코스닥, `N` 코넥스, `E` 기타 |
| `bizr_no` | string null | API | 사업자등록번호 |
| `acc_mt` | string null | API | 결산월 `MM` |
| `induty_code` | string null | API 업종코드 | 원문 그대로. 자릿수는 회사마다 다를 수 있음 |
| `induty_name_div` | string null | KSIC | 대분류 이름 |
| `induty_name_group` | string null | KSIC | 중분류 이름 |
| `induty_name_class` | string null | KSIC | 소분류 이름 |
| `induty_name_subclass` | string null | KSIC | 세분류 이름 |
| `induty_name_item` | string null | KSIC | 세세분류 이름 |
| `fetch_status` | string not null | 우리 | `ok` / `not_found` / `api_error` |
| `opendart_status` | string null | API `status` | `000`, `013` 등 원문 |
| `fetched_at` | timestamptz | 우리 | 마지막 시도(성공·실패) |
| `created_at` / `updated_at` | timestamptz | 우리 | 기존 모델과 동일 |

1차에 넣지 않는 API 필드: `corp_name_eng`, `ceo_nm`, `jurir_no`, `adres`, `hm_url`,
`ir_url`, `phn_no`, `fax_no`, `est_dt`.

`ensure_schema`의 `create_all`로 새 테이블을 만든다. 기존 테이블 ALTER는 없다.

재실행 대상: 행이 없거나 `fetch_status`가 `ok`가 아닌 `corp_code`. `ok`는 코드가 비어
있어도(API `000` + 업종 없음) 건너뛴다.

### 4.2 KSIC 제11·10차 코드표

경로: `packages/web-api/app/data/ksic11.json`, `ksic10.json`. 런타임에 통계청을 치지 않는다.
조회는 **11차에 코드가 있으면 그 표만 따라가고**, 없으면 10차다. 같은 코드라도 차수마다
의미가 다를 수 있어 parent 사슬을 표 간에 이어 붙이지 않는다.
11차는 연계표 오른쪽 표준산업분류 칸에서 추출한 표(합 2,090: 대 21·중 77·소 234·세 501·세세 1,257)이다.
10차는 전 표(대 21·중 77·소 232·세 495·세세 1,196, 합 2,021)이다.
대분류 이름 끝의 `(10~34)` 범위 표기는 저장하지 않는다.

매퍼는 `induty_code`를 정규화(앞뒤 공백 제거, 숫자 코드는 자릿수 유지)한 뒤, 선택한 표에서
**정확 일치**와 **상위 계층** 이름을 채운다. 예: 10차만 있는 `264`이면 소분류 이름과 중분류 `26`,
그 대분류 이름을 채우고 세·세세는 NULL. 두 표 모두에 없으면 코드만 저장하고 이름은 NULL이며
`fetch_status`는 `ok`다(API가 정상이면).
이미 `ok`인 행은 OpenDART를 다시 치지 않고 `scripts/remap_corp_ksic_names.py`로 이름만 다시 붙인다.

## 5. OpenDART 계약

문서: [기업개황 개발가이드](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019002).

- 메서드: `GET`
- URL: `https://opendart.fss.or.kr/api/company.json`
- 인코딩: UTF-8
- 질의: `crtfc_key`(40자), `corp_code`(8자)
- 본문: `status`, `message`, 개황 필드. `status`는 최상위 또는 `result` 아래 둘 다 읽는다.

설정:

| 키 | 기본 | 설명 |
|----|------|------|
| `opendart_api_key` | `""` | 비어 있으면 잡 시작 거부. 쉼표로 여러 키를 넣을 수 있음 |
| `opendart_api_key_2` | `""` | 첫 키 일일 한도(`020`)가 차면 이 키로 이어 감 |
| `opendart_concurrency` | `2` | 동시 진행 상한 |
| `opendart_timeout_seconds` | `15` | 단건 타임아웃. DART fetch 설정과 공유하지 않음 |
| `opendart_max_retries` | `2` | HTTP 일시 오류만 |
| `opendart_max_per_minute` | `200` | HTTP 시작 간격. TCP 차단을 피하려고 분당 1,000보다 낮춤 |

가이드 메시지 `020`은 개인 키 기준 하루 2만 건(OpenAPI 전체) 한도다.
네트워크는 분당 1,000회 이상이면 제한될 수 있어 요청 시작을 200회/분·동시 2로 둔다.
빠진 회사만 치므로 distinct 공시 회사 규모에서는 한 번에 끝나는 것을 전제로 한다.
한도에 걸리면 다음 인증키로 같은 회사를 다시 치고, 키가 모두 한도면 그날 잡을 멈춘다.

`.env.example`에 키 이름만 넣고 값은 커밋하지 않는다.

## 6. 잡 흐름

1. Admin이 `POST`하면 먼저 키·충돌을 검사한다. 통과하면 `extraction_jobs`에
   `extractor_id=corp_industry`, `mode=fill_missing`, `status=pending` 행을 만들고
   `job_id`를 202로 반환한 뒤 백그라운드에서 `run_job`을 돌린다.
2. 키가 없으면 잡을 **만들지 않고** 400 (날짜 LLM과 같음).
3. 같은 `extractor_id`가 `pending`/`running`이면 잡을 만들지 않고 충돌(기존
   `CatalogConflict`와 같은 409 계열). 카탈로그·감사 추출 진행 여부는 보지 않는다.
4. 대상 = distinct `disclosures.corp_code` − (`corps`에서 `fetch_status=ok`).
   대상이 0이면 잡은 곧 `succeeded`로 끝난다.
5. 시작 때 `params.target_count`에 이번 잡 대상 회사 수를 넣는다. 동시성 제한 안에서
   회사마다 `company.json` → KSIC 매핑 → upsert하고, 끝날 때마다
   `params.processed_count`를 올리며 로그를 남긴다. 화면의 `처리 / 대상`은 이 값이다
   (공시 건수가 아니다). 칸 위의 distinct/`ok`/남음은 DB 전역 요약이며 잡 카운터와 별개다.
6. 다음 회사 시작 전에 소프트 스톱이면 `partial`로 마감. 이미 upsert한 행은 유지.
   중단 플래그는 `ExtractionService`와 같이 **프로세스 메모리**다. DB 컬럼이 아니다.
7. 워커가 죽은 `running`은 감사 추출과 같이 오래되면 실패 처리해 잠금을 푼다.
   Admin **강제 종료**도 추출과 같이 둔다.

회사 단위 오류(잡은 계속):

| 상황 | `fetch_status` | 비고 |
|------|----------------|------|
| HTTP 재시도 소진 | `api_error` | 행을 남기고 다음 회사 |
| API `013` | `not_found` | 조회 데이터 없음 |
| API `000`, 업종 코드 없음 | `ok` | 식별자는 저장, 업종 NULL |
| KSIC 미적중 | `ok` | 코드만 |

잡 중단(이미 저장한 행 유지):

| 상황 | 잡 상태 |
|------|---------|
| API `010`/`011`/`012`/`901` (키·IP·계정) | `failed` |
| API `020` (요청 한도) | 다음 키가 있으면 그 키로 같은 회사를 재조회. 없으면 `failed` |
| API `800` (점검) | `failed` |

그 외 `status`는 `api_error`로 회사만 기록하고 계속한다. `021`은 이 API가 회사 1건이라
나오지 않는 것을 전제로 한다. 나오면 `api_error`.

재개는 새 잡이다. `ok`가 아닌 행과 미적재만 다시 친다.

## 7. Admin UI · API

문서 수집 단위(접수)와 회사 단위를 한 카드에 섞지 않는다. `/admin` 오른쪽은 기존
**수집 작업 카드**를 유지하고, 그 아래(수집 폼 근처)에 **회사 업종** 칸을 둔다.

쉬는 중:

- 숫자: 공시 distinct 회사 / `ok` / 남음(미적재+`ok` 아님)
- 버튼: 「빠진 회사 채우기」. 키 없음 또는 회사 업종 잡 진행 중이면 비활성
- 회사 행 표·이름 검색·기간/유형 입력 없음

진행 중 (HTMX 5초, 수집 카드와 동일 주기, **별도 부분 템플릿**):

- `실행 중`, `처리 n / 대상 m` (회사 수)
- 최근 로그 한 줄 (예: `00126380 ok · 264 …`)
- 소프트 스톱: 지금 호출 중인 회사 1건이 끝나면 멈춤
- 강제 종료: 잠금 해제(추출과 동일 목적)

끝나면 `succeeded` 또는 `partial`/`failed`와 갱신된 숫자를 보여 준다. 카탈로그에 새
`corp_code`가 들어온 뒤에도 같은 버튼이다.

HTML 폼은 수집처럼 POST 후 `/admin`으로 돌아온다. JSON API도 둔다 (`X-Admin-Token`).

| 메서드 | 경로 | 역할 |
|--------|------|------|
| `POST` | `/admin/corps/enrich` | 잡 등록, 202 |
| `GET` | `/admin/corps/status` | `job_id` 질의. 상태·카운터·최근 로그 |
| `POST` | `/admin/corps/jobs/{job_id}/soft-stop` | 다음 회사 경계 중단 |
| `POST` | `/admin/corps/jobs/{job_id}/force-finish` | 강제 마감 |
| `GET` | `/admin/corps/summary` | 화면용 distinct / ok / 남음. HTML 칸이 이 숫자를 씀 |

`GET /admin/corps/status`에 `job_id`가 없으면 가장 최근 `corp_industry` 잡을 보여 준다
(수집 job 카드와 같이 칸이 비지 않게).

Public `/api/v1/…` 회사 목록은 1차에 없다.

## 8. 오류 메시지 (사용자)

모두 한국어. 예:

- 키 없음: `OpenDART 인증키가 없습니다. OPENDART_API_KEY(와 필요하면 OPENDART_API_KEY_2)를 설정한 뒤 다시 시작해 주세요.`
- 잡 충돌: `회사 업종 작업이 이미 진행 중입니다. 현재 작업이 끝난 뒤에 다시 시작해 주세요.`
- 키 전환: 로그에 `다음 키(n번째)`만 남기고 키 문자열은 쓰지 않음
- 한도(모든 키 소진): 로그와 `error_message`에 `OpenDART 요청 한도를 넘었습니다. 이미 채운 회사는 유지됩니다. 다음 날 다시 실행해 주세요.`

## 9. 테스트

httpx 실호출 없이 고정 응답. DART HTML 픽스처와 섞지 않는다.

- KSIC 매퍼: `264` 계층, 5자리, 미적중 → 이름 NULL
- 클라이언트: `000` 매핑, `013`, 최상위/`result` `status`
- 서비스: `ok` 스킵, 대상 0건 즉시 성공, 한 키 `020`이면 다음 키로 재조회,
  모든 키 `020`/`010`이면 잡 중단, 키 없음 시작 거부,
  회사 단위 `api_error` 후에도 다음 코드 처리, 수집 잠금과 독립(카탈로그 running이어도
  시작 가능), `corp_industry` 중복 시작 거부
- Admin API: 202, 상태, 키 없을 때 400, 충돌 409
- 스키마: `ensure_schema` 후 `corps` 테이블 존재

## 10. 명시적 비범위

- Catalog/Facts 업종 컬럼·필터, 회사 마스터 열람 HTML
- `disclosures`/`entries`에 업종 복제
- 업종 이력, `ok` 행 refresh
- 카탈로그 슬라이스 종료 후 자동 채우기
- 회사 목록에서 공시 수집 트리거 (수집은 기간×유형 유지)
- OpenDART 재무·공시검색·고유번호 ZIP
- 기업개황의 대표자·주소·전화·URL·영문명·법인번호·설립일
- OpenDART 일일 한도 대시보드

후속 1: Catalog/Facts `JOIN` 필터. 후속 2: 회사 목록 표. 후속 3: 스냅샷 재조회.
