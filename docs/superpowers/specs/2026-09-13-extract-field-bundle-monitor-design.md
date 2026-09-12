# 추출 12묶음 성공·실패 모니터 설계

날짜: 2026-09-13  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` Admin — `/admin/extract`에서 **필드 묶음 12개**의 성공/실패를
연구 창과 실행 중 잡에서 보고, 실패 목록을 개선 작업용 TSV로 받는다.  
구현 계획이 아니라 **화면·집계 규칙·API·잡 카운터·테스트 경계**다.

선행: [`2026-09-11-extract-admin-monitor-design.md`](2026-09-11-extract-admin-monitor-design.md),
연구 창 [`research-data-completion.md`](../../paper/research-data-completion.md) §1·E,
변수 측정 [`variable-measurement.md`](../../paper/variable-measurement.md) §4·§7.

## 1. 목표

운영자가 문서 fetch 완전성(미추출·구버전·차단)과 **구성개념 12개의 추출 품질**을 섞지 않고 본다.
실패 행은 파서 개선 시드로 쓴다. 제도상 없는 칸과 설계상 해당 없음은 실패 큐에 넣지 않는다.

성공 기준:

- 왼쪽 연구 창에 기존 F001/F002/A001 **문서 카드가 유지**되고, 그 아래 **12줄 표**가 있다.
- 각 줄은 성공 / 해당없음 / 제도상없음 / 실패와 성공률(`성공/(성공+실패)`)을 보여 준다.
- 실패 칸 → 문서 목록(viewer 링크)과 같은 필터의 TSV.
- 오른쪽 잡은 기존 처리 n/m에 더해, **이번 잡이 쓴 ok 문서**의 12묶음 카운터를 보여 준다.
- 원문 HTML은 저장하지 않는다 (기존 Lazy Retrieval).

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 묶음 | facts의 12개 `*_status` (아래 §3). JSON 칸 단위가 아님. 묶음 상태가 `ok`가 아니면 그 묶음 실패 |
| 성공 | 해당 묶음 `*_status == "ok"` |
| 해당없음 | 종속기업만. `fs_scope != "consolidated"` → `not_applicable` |
| 제도상없음 | 커뮤니케이션만. `communications_status=not_found` 이고 `hours_status=ok` 이며 `activities_status=ok` |
| 실패 | 그 외 (`not_found`, `skipped`, `ambiguous`, `None`, 연결인데 종속 `not_found` 등) |
| 창 모집단 | 기간 안 `fetch_status=ok` **그리고** `extractor_version`이 현재 `EXTRACTOR_VERSION`인 facts. 미추출·차단·fetch 실패·구버전은 문서 카드에만 |
| 유형 | 창 표는 F001+F002+A001 **합산**. 유형별 12×3 표는 1차 없음. 목록·TSV에 `report_type` |
| 잡 카운터 | 이번 잡이 **새로 쓴** `fetch_status=ok` 행만 같은 네 칸으로 가산. 건너뛴 기존 ok는 창 표에만 |
| 실패 반출 | 화면 목록 + TSV + DART viewer URL. HTML 스냅샷 없음 |
| 경로 | 기존 `/admin/extract`. 새 Admin 페이지 없음 |
| JSON API | 문서 completeness는 유지. 필드 묶음은 별도 GET |
| 패키지 | `packages/web-api` |

1차에 **안 넣는 것:** 날짜 컷으로 제도상없음 판정, 성공/해당없음 목록, 유형별 12표,
HTML 아카이브, 골드셋 UI, 새 잡·facts 컬럼, 추출기 버전 올리기, 일별 히트맵.

## 3. 12묶음

API `bundle` 값과 화면 라벨.

| bundle | 컬럼 | 라벨 |
|--------|------|------|
| `auditor` | `auditor_status` | 감사인 |
| `opinion` | `opinion_status` | 감사의견 |
| `gaap` | `gaap_status` | GAAP |
| `audit_report_date` | `audit_report_date_status` | 감사보고서일 |
| `current_period` | `current_period_status` | 당기 |
| `hours` | `hours_status` | 감사시간 |
| `activities` | `activities_status` | 실시항목 |
| `communications` | `communications_status` | 커뮤니케이션 |
| `accounts` | `accounts_status` | 계정 |
| `icfr` | `icfr_status` | 내부회계 |
| `going_concern` | `going_concern_status` | 계속기업 |
| `subsidiary` | `subsidiary_status` | 종속기업 |

실시내용 JSON의 칸 하나가 아니라 **상태 컬럼 하나**가 묶음이다.

## 4. 화면

기존 `ops-grid`. 기간 폼은 문서 카드와 12줄이 **같은** `start_date`/`end_date`를 쓴다.

```text
왼쪽 (60초 폴링)                         오른쪽 (5초 폴링)
기간 폼                                  작업 처리 n / 대상 m
F001 / F002 / A001 문서 카드             이번 잡 12묶음 (성공/실패/해당없음)
12묶음 표 (창 전체, 세 유형 합)           소프트 스톱 · 강제 종료
  라벨  성공  해당없음  제도상없음  실패 성공률
실패 숫자 → 목록                         추출 시작 폼
「이 필터 TSV」                          로그
```

성공률은 `성공 / (성공+실패)` 이다. 해당없음·제도상없음은 분모에서 뺀다.
성공+실패가 0이면 성공률은 「—」.

실패 칸만 누를 수 있다. 목록은 최대 50, `next_cursor`로 더 보기.
   행: `report_type`(`source_report_type`), `rcept_no`, `dcm_no`, `fs_scope`, 필드 `status`, DART `viewer_url`.
`viewer_url`은 해당 `rcept_no`+`dcm_no`의 카탈로그 entry에서 고른다(대표 leaf 하나).
없으면 접수 상세 URL (`rcpNo`)만.

오른쪽 12묶음과 왼쪽 창 표의 숫자가 달라도 오류가 아니다.

## 5. 아키텍처

추출 파이프라인·selector·facts 스키마는 그대로다. 새 컬럼 없음.

| 단위 | 역할 | 의존 |
|------|------|------|
| `CompletenessService` | 창 기간 12줄 SQL 집계, 실패 목록, TSV 행 | `disclosures` 기간 조인 + `audit_report_facts` |
| HTML `/admin/extract` | 문서 카드 + 12줄 + 실패 목록 | 기존 HTMX. 12줄은 **문서 카드와 같은** `completeness-cards` 응답에 포함 |
| `ExtractionService.run_job` | `params.field_bundles` 가산 | 문서를 upsert한 뒤, `fetch_status=ok`일 때만 |
| JSON field-bundles | `/docs`에 공개 | Admin 토큰 |

12줄 집계는 컬럼마다 `SUM(CASE …)` 한 번의 GROUP 없는 집계(또는 단일 스캔)로 센다.
문서 카드의 `summarize_many`와 **같은 세션·같은 요청**에서 이어서 호출한다.
브라우저가 60초마다 JSON을 12번 치지 않는다.

잡 카운터 키 (`job.params.field_bundles`):

```json
{
  "auditor": {"ok": 0, "not_applicable": 0, "expected_missing": 0, "fail": 0},
  "opinion": {}
}
```

12키 모두 같은 네 칸. 화면 「해당없음」=`not_applicable`, 「제도상없음」=`expected_missing`.

분류 함수는 서비스 한곳에 둔다. 창 SQL CASE와 잡 가산이 **같은 규칙**을 쓴다
(테스트가 양쪽을 같은 픽스처로 검증).

### 5.1 분류 의사코드

문서가 창 모집단이 아니면 12줄에 넣지 않는다.

각 bundle:

1. `subsidiary`이고 `fs_scope != "consolidated"` 이고 상태가 `not_applicable` → `not_applicable`
2. `communications`이고 상태가 `not_found`이고 `hours_status==ok`이고 `activities_status==ok` → `expected_missing`
3. 상태가 `ok` → `ok`
4. 그 외 → `fail`

1·2가 3보다 앞선다. 별도 문서의 종속 `not_applicable`을 성공으로 세지 않는다.

연결 문서의 종속 `not_found`는 실패다. `hours`가 `skipped`이면 커뮤니케이션 `not_found`여도
제도상없음이 아니다(실패).

## 6. 백엔드 계약

기존 `GET /admin/extract/audit-opinion/completeness`는 유지한다.

추가 JSON (Admin 토큰):

1. `GET /admin/extract/audit-opinion/field-bundles?start_date=&end_date=`  
   연구 창 기본값을 강제하지 않는다. 화면이 기간을 넘긴다.  
   응답: `{ "start_date", "end_date", "extractor_version", "eligible": N, "bundles": [ { "bundle", "label", "ok", "not_applicable", "expected_missing", "fail" } ] }`  
   `eligible`은 모집단 문서 수. `bundles`는 §3 순서 12개.

2. `GET /admin/extract/audit-opinion/field-bundles/items?start_date=&end_date=&bundle=&outcome=fail&cursor=&limit=`  
   `bundle`은 §3 키. `outcome`은 1차 `fail`만. 그 외 400.  
   응답: `{ "items": [ { "report_type", "rcept_no", "dcm_no", "fs_scope", "bundle", "status", "extractor_version", "viewer_url" } ], "next_cursor" }`  
   목록 기본 `limit=50`, 최대 50.

3. `GET /admin/extract/audit-opinion/field-bundles/export?start_date=&end_date=&bundle=&outcome=fail&cursor=`  
   `text/tab-separated-values`. 헤더는 items와 같다. **한 응답 최대 5,000행.**  
   더 있으면 응답 본문 마지막에 `# next_cursor=<opaque>` 한 줄을 붙이거나,
   `X-Next-Cursor` 헤더를 준다. 구현은 헤더+주석 둘 다 허용하되 테스트는 헤더를 단언한다.  
   전 창 무제한 덤프 없음.

HTML:

- `GET /admin/extract/completeness-cards`가 문서 카드와 12줄 표를 **한 partial**로 반환.
- `GET /admin/extract/field-bundle-items?...` 실패 목록 조각 (기존 completeness-items와 같은 습관).
- TSV는 JSON export URL을 `다운로드` 링크로 (새 HTML POST 없음).

기간 검증은 completeness와 같다 (`YYYYMMDD`, disclosures의 dotted `rcept_dt` 조인).

## 7. 오류·폴링

| 상황 | 동작 |
|------|------|
| 토큰 없음 | `/admin/token` |
| 알 수 없는 bundle/outcome | 400. 한국어 안내 |
| 기간 형식 오류 | 기존 completeness `BadRequest`. 12줄은 빈 표+notice |
| 집계 중 | 문서 카드와 같이 인덱스 경로. 별도 캐시 테이블 없음 |
| 잡 없음 | 오른쪽 12묶음 생략. 왼쪽 창 표는 유지 |

폴링 주기는 기존과 같다. 12줄을 위해 5초 폴링을 추가하지 않는다.

## 8. 테스트

`CompletenessService` (또는 분류 순수 함수) + Admin API + HTML.

- 별도 facts → 종속 `not_applicable`, 성공률 분모에서 제외
- 1–3절 ok + 커뮤니케이션 `not_found` → `expected_missing`
- 연결 + 종속 `not_found` → `fail`
- 구버전 `fetch_status=ok` 행은 `eligible`·12줄에서 제외
- `fetch_failed` 행은 12줄에서 제외
- 목록 cursor, TSV 헤더·`Content-Type`, 알 수 없는 bundle 400
- UI: 12 라벨, 실패 링크, 잡 카드에 `field_bundles` 숫자가 보임
- 기존 문서 카드 집계 테스트는 유지

Live DART 호출 테스트 없음. `run_job`은 메모리 DB에서 ok 1건 후 `params.field_bundles.opinion.ok == 1` 정도만.

## 9. 비목표 (후속)

- 커뮤니케이션 제도상없음을 `rcept_dt` 연도로 자르기 (휴리스틱이 신규 4절 누락을 숨기면 그때)
- 유형 칩으로 12줄을 F001만 보기
- 성공·해당없음 목록
- 실패 HTML 스냅샷 / 골드셋 화면
- 계정 묶음을 자산총계 등으로 재분할
- 완전성 집계 캐시 테이블
