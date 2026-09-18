# 감사 추출 Admin 모니터 설계

날짜: 2026-09-11  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` Admin HTML — `/admin/extract`에서 추출 **완전성**과 **잡 진행**을
한 화면에서 본다.  
구현 계획이 아니라 **화면 단위·기존 API 재사용·잠금·폴링·테스트 경계**다.

선행: 추출 트리거·상태·완전성은 JSON Admin API로만 있다
(`POST /admin/extract/audit-opinion`, `GET /admin/extract/status`,
`GET /admin/extract/audit-opinion/completeness`). `/admin`은 수집 히트맵·수집 폼·회사 업종만
HTMX로 돌린다. 연구 창은
[`research-data-completion.md`](../../paper/research-data-completion.md) §1
(접수 2016-01-01~2026-09-09 × F001/F002/A001).

## 1. 목표

운영자가 추출이 **지금 도는지**와 연구 창이 **찼는지**를 같은 토큰으로 본다.
JSON `/docs`를 폴링하지 않아도 2.2(E)를 판정할 수 있다.

성공 기준:

- `/admin/extract`가 수집 `/admin`과 **형제 페이지**다. 위쪽에 수집 | 추출 전환이 있다.
- 왼쪽은 기간×유형 완전성 숫자(문서 `rcept_no`+`dcm_no`). 일별 히트맵이 아니다.
- 오른쪽은 최근 `audit_opinion` 잡 카드·시작 폼·중단. 수집 카드와 같은 운영 습관이다.
- 수집↔추출 DART 잠금은 양쪽 상단 배너로 보인다. 새 잠금 테이블은 없다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 경로 | `GET /admin/extract`. 수집은 `/admin` 유지 |
| 인증 | 기존 Admin 쿠키 토큰. 없으면 `/admin/token` |
| 기본 기간 | `20160101`–`20260909` (연구 창). 쿼리/폼으로 좁힐 수 있음 |
| 유형 | F001, F002, A001만. 수집 히트맵의 A002 등은 없음 |
| 완전성 단위 | 감사 문서. 날짜 칸·슬라이스 히트맵 없음 (1차) |
| 잡 | 기존 `extraction_jobs` `extractor_id=audit_opinion`. 날짜 LLM 잡 화면 없음 |
| 시작 | HTML 폼 POST → 기존 `ExtractionService.start` + 백그라운드 `run_job` |
| 모드 | `extract` / `resume` / `reparse`. 기본 `extract` |
| 잠금 | 기존 `assert_dart_idle`. 회사 업종과는 무관 |
| JSON API | 유지. HTML은 파사드 |
| 패키지 | `packages/web-api`. 새 npm 패키지 없음 |

1차에 **안 넣는 것:** 날짜 LLM(`resolve-dates`), 수동 날짜 PATCH, 일별 추출 히트맵,
Catalog/Facts 화면 조인, 회사 업종(그건 `/admin`), 실시내용 5절.

## 3. 아키텍처

추출 파이프라인·selector·facts 스키마는 그대로다.

| 단위 | 역할 | 의존 |
|------|------|------|
| Admin HTML `/admin/extract` | 완전성 카드 + 잡 카드 + 폼 | Jinja2, HTMX, 쿠키 토큰 |
| `CompletenessService.summarize` | 유형 하나 집계·목록 | 기존. 화면이 유형당 1회 호출(서버에서 3유형) |
| `ExtractionService` | 시작·실행·상태·soft-stop·force-finish | 기존. 상태 조회는 최근 잡 허용 |
| DART 잠금 | 수집 활성 ↔ 추출 시작 상호 배타 | `assert_dart_idle` |

새 facts 컬럼·새 extractor_id는 없다.

## 4. 화면

수집과 같은 `ops-grid`: 왼쪽 완전성, 오른쪽 실행.

```text
[수집] [추출]
추출 · 완전성
기간 20160101 ~ 20260909 (입력 가능). 유형 세 카드는 항상 같이 본다.

왼쪽                              오른쪽
F001 대상 / ok / 미추출 / 실패     작업 현황 (최근 audit_opinion)
F002 ...                          처리 n / 대상 m · 최근 로그
A001 ...                          소프트 스톱 · 강제 종료
숫자 클릭 → 해당 상태 문서 목록     추출 시작 폼 (기간·유형·모드)
                                  로그
```

수집 `/admin` 헤더에도 같은 **수집 | 추출** 링크를 둔다. 회사 업종 칸은 수집 페이지에 남긴다.

### 4.1 왼쪽 — 완전성

기본 `start_date=20160101`, `end_date=20260909`. 쿼리로 바꾸면 세 카드가 그 기간을 쓴다.

유형마다 카드 하나. 숫자는 기존 completeness 키다.

| 표시 | 키 | 읽는 법 |
|------|-----|---------|
| 대상 | `target` | selector가 고른 문서 |
| 추출 ok | `ok` | `fetch_status=ok` 이고 현재 추출기 버전. **부분실패를 포함** |
| 미추출 | `unextracted` | facts 행 없음 |
| 구버전 | `stale_version` | `fetch_status=ok` 인데 옛 파서. `extract`/`resume` 재추출 대상 |
| 실패 | `fetch_failed`+`blocked`+`section_missing` | 세 키를 합쳐 보여 주고, 펼치면 세분 |
| 부분실패 | `field_partial` | ok의 부분집합. 대상과 더해 100%가 아님 |
| 날짜 모호 | `ambiguous_dates` | 부분실패와 겹칠 수 있음 |

`ok`와 `field_partial`을 막대에서 배타 구간으로 쌓지 않는다. 부분실패는 「ok 중 구멍」이라고
적는다.

숫자를 누르면 그 유형·상태의 문서 목록(최대 50, `next_cursor`로 더 보기)을 HTMX로 붙인다.
식별자는 `rcept_no` / `dcm_no`만. Viewer·날짜 PATCH 링크는 1차에 없다.

목록 `status`는 JSON과 같다. 합친 「실패」를 누르면 세 상태를 이어 보여도 되고, 세 링크를
카드 안에 두어도 된다. 구현은 **세 키를 카드에 나눠 두고** 합계 한 줄만 크게 보여도 된다.

### 4.2 오른쪽 — 잡

최근 `extractor_id=audit_opinion` 잡. `job_id` 쿼리 없이 최신 1개(회사 업종 패널과 같음).
JSON `GET /admin/extract/status`는 `job_id` 필수를 유지해도 된다. HTML만 `find_latest`를 쓴다.

카드:

- `job_id` 앞 8자, `mode`, 상태 칩, 기간·유형
- 처리 / 대상 막대. `job.params.processed_count` / `target_count`
- 최근 로그 1줄 + 아래 로그 목록(수집과 같이 실행 중이면 info 포함)
- 실행 중이면 소프트 스톱·강제 종료. POST 뒤 303으로 `/admin/extract`로 돌아옴

`target_count`: 잡 시작 시 그 기간·유형의 selector 대상 문서 수.  
`processed_count`: 이번 잡이 **방문**한 문서 수(이미 `ok`라 건너뛴 것도 포함). 막대가 멈추지
않게 한다. 종료 로그의 「문서 N건」은 지금처럼 **실제 추출/실패만** 센다(스킵 제외).

시작 폼: 기간(기본 연구 창), 유형 체크(기본 세 유형), 모드. POST
`/admin/extract/start` → `ExtractionService.start` → `run_job`. 잠금이면 303 + `notice`.

수집이 활성일 때 시작 버튼 비활성 + 상단 「수집 중이니 추출을 시작할 수 없습니다」.  
추출이 활성일 때 `/admin` 수집 시작은 기존처럼 막히고, 추출 페이지 상단은 「추출 실행 중」.

### 4.3 폴링

완전성 집계는 기간 안 접수를 순회하므로 **5초 폴링 금지**.

| 조각 | 주기 |
|------|------|
| 잡 카드·로그·시작 폼(잠금/비활성) | 5초 (수집과 같음) |
| 왼쪽 완전성 카드 | 60초. 기간 변경·잡 종료 직후 전체 페이지 로드로도 갱신 |

세 유형 집계는 **한 HTML partial**에서 서버가 `summarize`를 세 번 호출한다. 브라우저가
completeness JSON을 세 번 치지 않는다.

## 5. 백엔드 계약

기존 JSON은 유지한다. HTML을 위해 아래만 추가·조정한다.

1. `GET /admin/extract` 및 HTMX partial (`completeness-cards`, `extract-job`, `extract-form`,
   `extract-logs`). `include_in_schema=False`.
2. `POST /admin/extract/start` (폼), `POST /admin/extract/jobs/{job_id}/soft-stop`,
   `POST /admin/extract/jobs/{job_id}/force-finish`. JSON 경로와 폼 경로를 나눈다
   (회사 업종 `/admin/corps/start` vs `/admin/corps/enrich`와 같음).
3. `ExtractionService.get_status`를 HTML이 쓰려면 `job_id=None`이면 최신 `audit_opinion`을
   보게 하거나, UI 레이어에서 `find_latest`만 호출한다. JSON의 `job_id` 필수는 깨지 않는다.
4. `run_job`이 `params.target_count`를 시작 때 넣고, 문서 방문마다 `processed_count`를
   갱신한다. 새 테이블 없음.

기간·유형 검증은 기존과 같다. 화면 기본값만 연구 창이다.

## 6. 오류·잠금

| 상황 | UI |
|------|-----|
| 토큰 없음 | `/admin/token` |
| 수집 활성인데 추출 시작 | 버튼 비활성. 제출해도 `CatalogConflict` → `notice` |
| 추출 활성인데 또 시작 | 동일 |
| 잡 없음 | 카드 idle. 완전성 숫자는 그대로 |
| completeness 기간 오류 | 기존 `BadRequest` 메시지. 폼을 연구 창으로 되돌리지 않고 표시 |

워커가 죽은 `running`은 기존 stale 처리(1시간)와 `force-finish`를 쓴다. 화면이 새 규칙을
만들지 않는다.

## 7. 테스트

`tests/test_extract_admin_ui.py` (회사 업종 UI 테스트와 같은 패턴).

- 토큰 없으면 추출 페이지가 토큰으로 보낸다
- 토큰 있으면 세 유형 카드에 Fake completeness 숫자가 보인다
- 기본 기간이 `20160101`–`20260909`
- 시작 폼이 서비스를 호출하고 303으로 `/admin/extract`로 돌아온다
- 수집 잠금이면 시작이 `notice`를 붙인다
- `/admin`과 `/admin/extract`에 수집|추출 링크가 있다

추출 엔진·completeness SQL 테스트는 새로 짜지 않는다. 진행 카운터를 `params`에 넣으면
`test_extraction_service`에 방문 수 갱신 1건을 추가한다.

Live DART 호출 테스트 없음.

## 8. 비목표 (후속)

- 일×유형 추출 히트맵
- 완전성 집계 캐시 테이블 (연구 창 전수가 느리면 그때)
- 날짜 LLM / PATCH를 이 화면에 붙이기
- Public `/facts` HTML과 이 운영 화면을 합치기
