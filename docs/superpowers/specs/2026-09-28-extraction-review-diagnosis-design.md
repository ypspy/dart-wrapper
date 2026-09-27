# 추출 12묶음 진단 설계

날짜: 2026-09-28  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` — 현재 추출기 `fetch_status=ok` 행의 12묶음을 성공 이상치·범주 빈도·실패 그룹으로 진단하고, 사람 판정을 `extraction_reviews`에 남긴다.  
구현 계획이 아니라 **후보 규칙·검토 테이블·TSV 왕복·테스트 경계**다. 파서 규칙은 바꾸지 않는다.

선행: [`2026-09-13-extract-field-bundle-monitor-design.md`](2026-09-13-extract-field-bundle-monitor-design.md),
연구 설계 [`research-data-completion.md`](../../paper/research-data-completion.md) §1,
변수 측정 [`variable-measurement.md`](../../paper/variable-measurement.md) §7.

## 1. 목표

12묶음이 성공이어도 값이 이상할 수 있고, 실패여도 원문이 비어 있는 경우와 파서 실수가 섞여 있다. 이번 스펙은 그 둘을 가르기 위한 후보와 판정 기록을 만든다.

성공 기준:

- 숫자 후보는 문서 유형·별도/연결(계정은 계정까지)로 층화한 log1p 1.5 IQR과 금지 값으로 자른다.
- 범주 후보는 빈도만 보고, 드물다는 이유만으로 오류 판정을 넣지 않는다.
- 실패 후보는 `classify_outcome=fail`만, 상태·섹션 없음·`conflicts`로 묶어 대표를 연다.
- 사람은 viewer로 원문을 보고 `source` / `logic` / `hold`를 TSV로 되돌린다.
- `audit_report_facts`와 카탈로그는 읽기만 한다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 산출물 | 진단 절차. 파서 수정은 판정이 쌓인 뒤 묶음별 스펙 |
| 모집단 | 현재 `EXTRACTOR_VERSION`이고 `fetch_status=ok`인 fact 전체. 구버전·미추출·fetch 실패는 제외 |
| 연구 패널 | 모집단 안에서만 표시. 회귀 표본이 아닌 행도 후보는 된다 |
| 성공 숫자 | 감사시간 합, 계정 `value_won`, 종속기업 수, 보고일 간격. 실시항목·커뮤니케이션·당기 문자열은 숫자 분포에 넣지 않음 |
| 성공 범주 | 의견, GAAP, 내부회계 업무·의견, 계속기업은 비율 1% 미만만 후보. 감사인은 빈도표와 형식 깨진 이름만 |
| 실패 | 상태 + 섹션 entry 공백 + `conflicts` 유무. 해당없음·제도상없음은 제외 |
| 판정 | 자동 목록, 사람 원문 대조. 연구 패널 행을 먼저 연다 |
| 저장 | `extraction_reviews`. facts 측정 열은 그대로 |
| 입출력 | `scripts/extraction_reviews.py`의 `diagnose` / `export-tsv` / `import-tsv`. Admin 화면 없음 |
| 패키지 | `packages/web-api` |

## 3. 모집단과 연구 패널

진단 대상은 `extractor_version`이 현재 추출기이고 `fetch_status=ok`인 `audit_report_facts`다. 문서 유형은 `source_report_type`이다.

접수 메타는 `disclosures`(`rcept_no` PK)에서 `corp_code`, `year_end`, `rcept_dt`를 읽고, `corp_cls`는 `corps`를 `corp_code`로 조인한다. 회사 행이 없으면 `corp_cls`는 없다. 실패 분류는 모니터와 같은 `classify_outcome`이다. `hours_status`, `activities_status`, `report_type`, `corp_cls`, `period_year`를 넘긴다. `period_year`는 `icfr_period_year(year_end, rcept_dt)`다. `corp_cls`가 없으면 상장으로 보지 않는다.

연구 패널은 모집단 행만으로 고른 기업–연도 한 문서다.

- 결산월이 2016-01-31 이상 2025-12-31 이하이고, 접수일이 2016-01-01 이상 2026-09-09 이하인 행만 후보가 된다. 날짜를 읽지 못하면 그 행은 패널이 아니다.
- `corp_code`가 없으면 패널이 아니다.
- 같은 `corp_code`+`year_end`에서 연결(`fs_scope=consolidated`)이 하나라도 있으면 연결만 남긴다. 연결이 없고 별도(`separate`)가 있으면 별도만 남긴다. 둘 다 없으면 그 기업–연도는 패널에 넣지 않는다.
- 남은 행에서 `source_report_type`이 F001 또는 F002인 행이 있으면 A001을 뺀다.
- 그다음 가장 늦은 `rcept_dt`, 같으면 `rcept_no` 내림차순, 그래도 같으면 `dcm_no` 내림차순인 한 행이 패널이다.

결산일 파싱은 기존 `parse_year_end`를 쓴다. 접수일은 `YYYYMMDD` 문자열로 비교한다.

## 4. 후보 규칙

해당없음·제도상없음은 후보가 아니다. 사분위는 `statistics.quantiles(values, n=4, method="inclusive")`다. IQR이 양수이고 비교 값이 30개 이상일 때만 IQR 후보를 만든다. 금액·시간·종속기업 수는 0 초과 값의 `log1p`로 울타리를 계산하고, 그 눈금에서 1.5 IQR 밖을 고른다. 금지 값은 사분위에 넣지 않는다. 보고일 간격은 일수 그대로다. IQR이 0이면 그 층은 IQR 후보 없이 요약 건수만 남긴다.

층 키는 `문서유형|별도연결|대상`이다. 별도/연결을 쓰지 않으면 가운데는 `*`다.

### 4.1 숫자

| 신호 | 값 | 층 | 금지·결측 |
|------|----|----|-----------|
| `iqr_low` / `iqr_high` | 아래 네 값의 꼬리 | 표 참고 | 울타리 밖 |
| `hours_nonpositive` | 당기 감사 합계 | `유형\|범위\|audit_current_total` | `value` ≤ 0 |
| `hours_total_missing` | 같은 칸이 없음 | 같은 층 | 칸 없음 |
| `account_negative` | 당기 `value_won` | `유형\|범위\|계정` | 자산·부채 네 계정이 0 미만 |
| `unit_missing` | 당기 계정 레코드가 `ok`인데 `value_won`이 없음 | 같은 층 | 단위 미해석 |
| `subsidiary_negative` | `subsidiary_count` | `유형\|*\|subsidiary_count` | 0 미만. 0은 금지 아님 |
| `date_nonpositive` | 감사보고서일 − 결산일(일) | `유형\|범위\|lag_days` | 0 이하 |

감사시간 값은 `hours`에서 `role=total`, `metric=audit`, `period=current`인 칸의 `value`다. 그 칸이 둘 이상이면 그 행은 시간 후보를 만들지 않고 요약에 `hours_total_duplicate`로 센다. 분포·IQR 층은 문서 유형 × `fs_scope`다. 0은 log1p 분포에 넣지 않는다. 감사시간 0 이하는 `hours_nonpositive`로만 잡는다. 계정·종속기업 수의 0은 금지 후보도 IQR 분포도 아니다.

계정은 `accounts`의 `period=current`이고 레코드 `status=ok`인 행이다. IQR은 `value_won`이 0 초과인 값만, 계정마다 따로 한다. 음수 금지는 `total_asset`, `current_asset`, `total_liability`, `current_liability`만이다. `total_equity`와 `net_income`의 음수는 금지하지 않는다.

종속기업 수는 `fs_scope=consolidated`이고 `subsidiary_status=ok`이며 값이 있는 행만 분포에 넣는다. 층은 문서 유형뿐이다.

보고일 간격은 `audit_report_date_status=ok`이고 보고서일과 결산일이 모두 파싱될 때다. 결산일이 없으면 그 행은 간격 후보가 아니고, 다른 신호는 계산한다. 수동 보정·LLM 해소도 상태가 `ok`이면 포함한다.

IQR 행의 `subject`는 시간 `audit_current_total`, 계정은 계정 코드, 종속기업 `subsidiary_count`, 간격 `lag_days`다. `tail`은 `low` 또는 `high`다.

### 4.2 범주

분모는 그 묶음 `*_status=ok`인 모집단 행 수다. 비율이 1% 미만인 코드만 `rare_code` 후보다. 의견·GAAP·계속기업 코드가 비어 있으면 `subject`는 빈 문자열이다.

| 묶음 | 코드 |
|------|------|
| `opinion` | `opinion_code` |
| `gaap` | `gaap_code` |
| `icfr` | `icfr_engagement`와 `icfr_opinion_code`를 `engagement/opinion`으로 잇는다 |
| `going_concern` | `going_concern`을 문자열로. 없으면 빈 문자열 |

내부회계에서 한쪽이 없으면 그 자리는 빈 문자열이다. 둘 다 없으면 `subject`는 `/`다.

감사인(`auditor_resolved`)은 건수 내림차순 요약만 만들고, 1건 상호를 `rare_code`로 넣지 않는다. `auditor_invalid`는 값이 없거나, 공백을 뺀 길이가 2 미만이거나, 한글 음절(`가`–`힣`)이 없을 때다. `subject`는 해소된 이름이고, 없으면 빈 문자열이다.

희귀 코드·감사인 형식 오류의 `stratum`은 `*|*|{bundle}`이다. 판정 초기값은 `hold`다.

### 4.3 실패

`classify_outcome`이 `fail`인 칸만 본다. 그룹 키(`subject`)는 `{status}|missing={0 또는 1}|conflicts={0 또는 1}`이다. `conflicts`는 리스트가 비어 있지 않으면 1이다. 리스트가 아니면 0으로 보고 요약에 건수를 남긴다. entry는 `None`과 빈 문자열을 모두 빈 것으로 본다.

섹션 없음은 다음 entry가 모두 비었을 때다.

| 묶음 | 비어 있어야 하는 entry |
|------|------------------------|
| `auditor` | `cover_entry_id`, `opinion_entry_id`, `a001_opinion_entry_id` |
| `opinion` | `opinion_entry_id`, `a001_opinion_entry_id` |
| `gaap` | `cover_entry_id`, `opinion_entry_id` |
| `audit_report_date` | `opinion_entry_id` |
| `current_period` | `cover_entry_id`, `a001_cover_entry_id` |
| `hours`, `activities`, `communications` | `activity_entry_id` |
| `accounts` | `bs_entry_id`, `is_entry_id` |
| `icfr` | `icfr_entry_id` |
| `going_concern` | `opinion_entry_id` |
| `subsidiary` | `notes_entry_id`, `a001_affiliate_entry_id` |

신호는 `fail`이고 `stratum`은 `*|*|{bundle}`이다.

### 4.4 테이블에 넣는 수와 TSV로 여는 수

- 금지 값(`hours_nonpositive`, `hours_total_missing`, `account_negative`, `unit_missing`, `subsidiary_negative`, `date_nonpositive`)은 해당 행을 모두 저장하고 기본 TSV에도 모두 넣는다.
- IQR 밖은 모두 저장한다. 연구 패널 행만 `queue_order`를 매긴다. 비교 눈금(금액·시간·건수는 log1p, 간격은 일수)이 작은 쪽이 `low`의 1이고, 큰 쪽이 `high`의 1이다. 비패널 IQR 행의 `queue_order`는 null이다. 기본 TSV는 층·꼬리마다 `queue_order` 1–5다.
- 실패 그룹과 희귀 코드·`auditor_invalid`는 대표만 저장한다. 정렬은 패널 우선, 그다음 `rcept_dt`·`rcept_no`·`dcm_no` 내림차순이다. 패널 행이 있으면 패널 5건, 없으면 비패널 5건이다. 대표의 `queue_order`는 1부터다. 그룹 전체 건수는 요약에만 남긴다. 대표 판정이 갈려도 이번 스펙은 다음 5건을 뽑지 않는다.
- 같은 층의 IQR 행에 `source`와 `logic`이 둘 다 있으면 `export-tsv --next`가 그 층만 잇는다. 꼬리별로, `hold`가 아닌 행의 최대 `queue_order`를 m이라 하고, `queue_order`가 m+1부터 m+5까지인 `hold` 행을 뽑는다. 이미 판정된 구멍은 건너뛴다.

## 5. 검토 테이블

`app/models/extraction_review.py`의 `extraction_reviews`. `ensure_schema`의 `create_all`로 만든다. facts에는 열을 추가하지 않는다.

자연키는 `rcept_no`, `dcm_no`, `bundle`, `signal`, `subject`다.

| 열 | 내용 |
|----|------|
| 자연키 5개 | 위와 같음. 문자열. `subject`는 빈 문자열 허용 |
| `extractor_version` | 진단 당시 추출기. active 행은 매 진단마다 현재 버전으로 갱신 |
| `in_research_panel` | §3의 한 행이면 참. 매 진단마다 다시 계산하고 판정은 유지 |
| `stratum` | §4의 층 키 |
| `tail` | `low` / `high` / 빈 문자열 |
| `queue_order` | 정수 또는 null. §4.4 |
| `raw_value` | 비교에 쓴 값의 문자열 |
| `active` | 이번 진단 후보면 참 |
| `verdict` | `hold` / `source` / `logic`. 신규는 `hold` |
| `tag` | 소스일 때만 `as_written`, `real_magnitude`, `rare_but_valid`, `other`. 아니면 빈 문자열 |
| `note` | 사람 메모. 기본 빈 문자열 |

upsert 규칙:

- 자연키가 있고 `raw_value`가 같으면 `verdict`·`tag`·`note`를 유지하고 `active=true`로 둔다. 패널 플래그·층·꼬리·순번은 다시 계산한다.
- `raw_value`가 달라지면 `verdict=hold`, `tag`는 빈 문자열로 두고, 기존 메모 앞에 `이전 판정={verdict}; 이전 태그={tag 또는 -}; 이전 값={old}`와 줄바꿈을 붙인다.
- 이번 후보에 없는 기존 행은 삭제하지 않고 `active=false`로 둔다.
- 모집단 ok 행이 0이면 diagnose는 실패하고, 기존 검토 행의 `active`를 끄지 않는다.

## 6. 스크립트

`packages/web-api/scripts/extraction_reviews.py`

계산은 `app/reviewing/candidates.py`(DB 없음), 입출력은 `app/services/extraction_review_service.py`다.

공통 옵션은 기존 facts export와 같이 `--database-url`(기본 앱 `DATABASE_URL`)이다.

### 6.1 diagnose

후보를 계산해 §5대로 upsert한다. 표준 출력에 층별 비교 개수·Q1·Q3·IQR·IQR 후보 수, IQR을 건너뛴 이유(`n<30`, `iqr_zero`), 실패 그룹별 전체 수·패널 수·대표 수, 범주 코드별 건수·비율을 한글로 찍는다. `--summary-out PATH`가 있으면 같은 내용을 TSV로도 쓴다.

`extraction_jobs.status`가 `pending` 또는 `running`인 행이 있으면 시작하지 않고 비제로로 끝난다.

### 6.2 export-tsv

`--out PATH`. 생략하면 표준 출력이다. UTF-8, 탭 구분, 헤더는 다음이다.

`rcept_no`, `dcm_no`, `bundle`, `signal`, `subject`, `extractor_version`, `in_research_panel`, `stratum`, `tail`, `queue_order`, `raw_value`, `verdict`, `tag`, `note`, `viewer_url`

`viewer_url`은 저장하지 않고 `field_bundles.DART_DOCUMENT_VIEW`로 만든다. `active=true`만 내보낸다. 기본 집합은 §4.4다. 후보가 없어도 헤더만 쓰고 종료 코드 0이다.

`--next`는 §4.4의 IQR 연장만 내보낸다. 소스와 로직이 같이 있는 층이 없으면 헤더만 쓰고, 그런 층이 없다고 표준 오류에 알린 뒤 종료 코드 0이다.

### 6.3 import-tsv

`--in PATH`. UTF-8 TSV다. 자연키로 행을 찾고 `verdict`·`tag`·`note`만 고친다. 그 세 칸이 비어 있으면 기존 값을 유지한다. 다른 열은 무시한다. 한 트랜잭션이다. 다음이면 파일을 거부하고 DB를 바꾸지 않는다.

- 헤더에 자연키와 `verdict`, `tag`, `note`가 없다.
- 자연키가 DB에 없다.
- 같은 자연키가 파일에 두 번 있다.
- `verdict`가 비어 있지 않은데 `hold` / `source` / `logic`이 아니다.
- `verdict`가 `logic` 또는 `hold`인데 `tag`가 비어 있지 않다.
- `tag`가 비어 있지 않은데 허용 네 값 밖이다.

`source`이면서 `tag`가 빈 것은 허용한다. 태그를 지울 때는 칸에 `-`를 적는다. `-`는 빈 태그로 저장하며, `logic`·`hold`의 `-`도 빈 태그로 본 뒤 통과시킨다.

### 6.4 facts export

`scripts/export_audit_report_facts.py`의 기본 열은 유지한다. `--with-reviews`일 때만 `source_tags` 열을 붙인다. 값은 그 문서의 `active=true`이고 `verdict=source`이며 `tag`가 비어 있지 않은 행을 `bundle:subject:tag`로, `bundle`·`subject`·`tag` 순으로 정렬해 `;`로 잇는다. 없으면 빈 칸이다. 로직 판정은 넣지 않는다.

## 7. 실패 처리

- `hours` 또는 `accounts`가 리스트가 아니면 그 신호만 건너뛰고 요약에 건수를 남긴다.
- 결산일 파싱 실패는 §3·§4.1과 같이 패널과 간격만 빠진다.
- IQR 0과 층 크기 30 미만은 IQR 후보만 생략한다.
- import 실패는 부분 반영하지 않는다.
- diagnose와 export, import는 한 프로세스다. facts·`disclosures`·`entries`·`corps`를 수정하지 않는다.

## 8. 테스트

DART를 호출하지 않는다. SQLite 메모리 DB와 픽스처만 쓴다. 파서 테스트는 넣지 않는다.

`candidates.py`:

- log1p 1.5 IQR은 0 초과만으로 울타리를 만들고, 음수는 사분위에 넣지 않는다.
- 층 30 미만과 IQR 0은 IQR 후보가 없고 금지 값은 남는다.
- 시간 합계 없음, 합계 0 이하, `value_won` 없음, 자산·부채 음수, 종속기업 수 음수, 간격 0 이하는 후보가 된다. 합계 칸이 둘 이상이면 후보는 아니고 요약 건수만 는다. 자본·당기순손익 음수, 계정·종속기업 수의 0은 금지 후보가 아니다.
- 닫힌 코드는 비율 1% 미만만 `rare_code`다. 감사인 1건은 후보가 아니고, 빈 값·한글 없음·2자 미만만 `auditor_invalid`다.
- 실패는 `fail`만 묶고, 대표는 패널 5건, 패널이 없으면 비패널 5건이다.
- IQR `queue_order`는 패널의 작은 쪽 5와 큰 쪽 5가 1–5다.
- 패널은 기간·`corp_code`·연결 우선·F001/F002 우선·가장 늦은 접수 한 문서다.

서비스:

- diagnose는 facts와 카탈로그를 고치지 않는다. 같은 값이면 판정을 유지하고, 값이 바뀌면 `hold`와 이전 판정 메모로 되돌린다. 빠진 후보는 `active=false`다. ok 행이 0이면 `active`를 끄지 않고 실패한다.
- 추출 잡이 `pending` 또는 `running`이면 diagnose는 시작하지 않는다.
- import는 잘못된 파일이면 한 행도 반영하지 않는다. 빈 칸은 유지하고, 소스이면서 태그가 빈 것은 허용한다. `-`는 태그를 빈 문자열로 지운다.
- 기본 export 집합과 `--next`는 §4.4와 같다.
- `--with-reviews`는 소스 태그만 `source_tags`에 붙인다.

## 9. 범위 밖

- 파서·추출기 버전 변경, `patch` 재추출
- Admin 검토 화면
- 실패·희귀 코드 대표를 넘는 다음 슬라이스
- 비패널 IQR 행의 기본 TSV 포함
- 원문 HTML 저장
