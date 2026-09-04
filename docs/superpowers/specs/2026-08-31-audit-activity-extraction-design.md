# 외부감사 실시내용 추출 설계 (D-4)

날짜: 2026-08-31  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` — 이미 고르는 `외부감사 실시내용` leaf의 `viewer_url`에서
별지 제4호 1~4절을 구조화해 `audit_report_facts`에 붙이고, API·연구 CSV로 제공한다.  
구현 계획이 아니라 **아키텍처·스키마·파서 규칙·잡/API 계약·테스트 경계**다.

선행: [2026-08-28 감사보고서 표지·의견 추출](2026-08-28-audit-opinion-extraction-design.md).  
서식 원전: 외부감사 및 회계 등에 관한 규정 시행세칙 **별지 제4호 서식** 「외부감사 실시내용」
(사용자 첨부 PDF: `[별지 4] 외부감사 실시내용(외부감사 및 회계 등에 관한 규정 시행세칙).pdf`).  
스크래핑 원전: [ypspy/dart-scraping](https://github.com/ypspy/dart-scraping) D-4-1·D-4-2·D-4-3.  
규칙: 추출기 라벨·키워드를 바꿀 때는 **별지 제4호 또는 해당 옛 파일을 연 뒤에만** 적는다.

이번 라운드는 D-4만. D-5(계정)·D-6(내부통제)·D-7(정관)은 다음 스펙.

## 1. 목표

의견 추출 잡이 이미 실시내용 HTML을 헤더(회사명·결산월) 검증용으로 가져온다.
같은 fetch에서 별지 제4호 1~4절 표를 읽어 JSON으로 저장한다. 새 잡·새 패키지는 없다.

서식은 과거부터 **절이 추가되기만 했고 줄어들지 않았다.** 1·2·3절이 먼저 있고,
4절(감사·감사위원회 커뮤니케이션)이 붙었으며, 5절(중요성 금액)은 선택 기재다.
옛 공시는 있는 절만 파싱하고, 없는 4절은 `not_found`다. 5절은 범위 밖이다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 산출 | 연구 CSV + Public API. 의견 facts와 **같은 행** |
| 실행 | 기존 `POST /admin/extract/audit-opinion`. 새 `extractor_id` 없음 |
| 저장 단위 | 감사보고서 문서 (`rcept_no` + `dcm_no`). 기업·연도당 접지 않음 |
| 공시 유형 | F001, F002, A001 첨부 감사·연결감사. selector 변경 없음 |
| 필드 | 2절 시간 피벗, 3절 실시내용 전 항목, 4절 회차 + `has_audit_committee` |
| 5절 | **파싱하지 않음.** 있어도 무시, 없어도 상태·완전성에 넣지 않음 |
| JSON 해석 | 격자 덤프가 아니라 **의미 단위 레코드**. 라벨이 안 맞는 칸은 `unmapped`로 남김 |
| HTML | 저장하지 않음. 재추출은 URL을 다시 fetch |
| 패키지 | `packages/web-api` `app/extracting/` |
| 파싱 | 실시내용 soup의 `table` + D-4 전용 격자 펼침. Viewer `_parse_table`은 그대로. `FindTargetTable`(td>20)·칸 인덱스 하드코딩은 쓰지 않음 |
| 해소 | 시간·실시내용을 F001/A001 형제 행과 맞추거나 `conflicts`에 넣지 않음. 별지 주 1②대로 별도·연결은 **합산 공시** |
| 버전 | `extractor_version` = `audit_opinion.v4` |

## 3. 구조

```text
기존 Admin 추출 잡 (기간 + report_types)
  → Selector가 activity_entry_id 선정 (변경 없음)
  → DartHttp로 viewer_url fetch
  → extract_activity_header (회사명·결산월, 그대로)
  → expand_table_matrix → hours / activities / communications
  → 같은 audit_report_facts 행 upsert
```

카탈로그 수집과 추출 잡의 DART 상호 배타는 의견 추출과 같다.

식별자는 카탈로그만 쓴다. 1절 회사명·사업연도는 목록 `corp_name`·`year_end` **검증만** 하고 조인 키를 바꾸지 않는다.

## 4. 데이터 모델

`audit_report_facts`에 컬럼을 추가한다. 자식 테이블·`audit_activity_facts`는 두지 않는다.

| 컬럼 | 내용 |
|------|------|
| `hours` | JSON 배열. 기본 `[]` |
| `activities` | JSON 배열. 기본 `[]` |
| `communications` | JSON 객체 `{has_audit_committee, items}`. 기본 `{"has_audit_committee": false, "items": []}` |
| `hours_status` | `ok` / `not_found` / `skipped` |
| `activities_status` | 같음 |
| `communications_status` | 같음 |

필드 상태는 의견 추출과 같다. `normalize_failed`·`ambiguous`는 D-4에 쓰지 않는다.
칸 일부만 라벨이 안 맞아도 표를 읽었으면 `ok`이고 그 칸은 `unmapped: true`다.

### 4.1 `hours` 원소

```json
{
  "role": "engagement_partner",
  "role_raw": "담당이사 (업무수행이사)",
  "metric": "audit",
  "metric_raw": "감사",
  "period": "current",
  "period_raw": "당기",
  "raw": "1,200",
  "value": 1200,
  "unmapped": false
}
```

`role` (compact 헤더 매칭, 앞이 이김):

| compact 포함 | `role` |
|--------------|--------|
| `품질관리검토자` 또는 `심리실` | `qcr` |
| `담당이사` 또는 `업무수행이사` | `engagement_partner` |
| `등록공인회계사` | `cpa` |
| `수습공인회계사` | `junior_cpa` |
| `수주산업` 또는 `건설계약` | `construction_specialist` |
| `전산감사` 또는 `가치평가` 또는 `세무` (위 수주산업이 아닐 때) | `specialist` |
| 열 헤더가 정확히 `합계` | `total` |
| 그 밖 (옛 서식 `기타` 포함) | `other` |

`metric` (펼친 격자 **앞 두 열** compact):

| 라벨 | `metric` |
|------|----------|
| `투입인원수` | `headcount` |
| `분ㆍ반기검토` / `분·반기검토` / `분기검토` / `반기검토` | `interim_review` |
| 정확히 `합계` | `total` |
| 정확히 `감사` (`감사참여자`·`감사업무`·`감사시간` 등은 제외) | `audit` |
| 그 밖 지표 행 | `other` |

역할 열 `합계`와 지표 행 `합계`를 섞지 않는다.

`period`: 칸 또는 그 열 헤더에 `당기` → `current`, `전기` → `prior`, 없으면 `unknown`.
비교표시가 아닌 표는 역할당 값 하나, `period=unknown`.

`value`: 쉼표 제거 후 정수. `raw`가 `-`이거나 공백이면 `0` (별지 주 1①). 숫자가 아니면 `null`, `raw`는 유지.

### 4.2 `activities` 원소

모든 원소에 `row_type`을 둔다.

| `row_type` | 언제 |
|------------|------|
| `block` | 전반감사계획·외부조회·지배기구·전문가 등, 구분당 1개. 재고·금융 실사는 여기 넣지 않음 |
| `column_header` | 현장감사 안쪽 1행 헤더(수행시기 / 투입인원 / 주요 감사업무 수행내용) |
| `sub_header` | 투입인원 아래 2행 헤더(상주 / 비상주) |
| `visit` | 현장감사 회차, 또는 재고·금융 실사 회차(시기 하나가 새 회차) |
| `item` | 쓰지 않음. 실사 회차의 시기·장소·대상은 `visit.items` 안 |

현장감사 예(헤더 2개 + 회차). `투입인원`은 헤더 계층을 유지해 객체로 둔다.

```json
[
  {
    "section": "fieldwork",
    "section_raw": "현장감사",
    "row_type": "column_header",
    "labels": ["수행시기", "투입인원", "주요 감사업무 수행내용"]
  },
  {
    "section": "fieldwork",
    "section_raw": "현장감사",
    "row_type": "sub_header",
    "parent_label": "투입인원",
    "labels": ["상주", "비상주"]
  },
  {
    "section": "fieldwork",
    "section_raw": "현장감사",
    "row_type": "visit",
    "fields": {
      "수행시기": {
        "raw": "24.06.17~24.07.14 (27일)",
        "start_date": "24.06.17",
        "end_date": "24.07.14",
        "days": 27
      },
      "투입인원": {
        "상주": {"raw": "20명", "count": 20},
        "비상주": {"raw": "5명", "count": 5}
      },
      "주요 감사업무 수행내용": "내부회계관리제도감사 : 설계평가"
    }
  }
]
```

재고·금융 실사 예. **회차마다 `visit` 하나**, 그 안에 시기·장소·대상 `items`. 실사가 두 번이면 `visit`이 두 개다(item 6개가 평탄하게 나열되지 않음). 값이 `-`여도 그 회차 `items`에 남긴다.

```json
[
  {
    "section": "inventory_observation",
    "section_raw": "재고자산실사(입회)",
    "row_type": "visit",
    "items": [
      {
        "label": "실사(입회)시기",
        "raw": "2025.01.02 (1일)",
        "start_date": "2025.01.02",
        "end_date": "2025.01.02",
        "days": 1
      },
      {"label": "실사(입회)장소", "raw": "보은사업장, 부산사업장, 인천사업장 등"},
      {"label": "실사(입회)대상", "raw": "원재료, 재공품, 반제품, 제품, 상품, 저장품 등"}
    ]
  },
  {
    "section": "inventory_observation",
    "section_raw": "재고자산실사(입회)",
    "row_type": "visit",
    "items": [
      {
        "label": "실사(입회)시기",
        "raw": "2025.01.03 (1일)",
        "start_date": "2025.01.03",
        "end_date": "2025.01.03",
        "days": 1
      },
      {"label": "실사(입회)장소", "raw": "서울본사"},
      {"label": "실사(입회)대상", "raw": "-"}
    ]
  }
]
```

금융자산실사는 `section=financial_asset_observation`이고 같은 `visit`+`items` 구조다. 재고 1회·금융 1회면 `visit`이 섹션마다 하나다.

| compact 구분 | `section` |
|--------------|-----------|
| `전반감사계획` | `planning` |
| `현장감사` | `fieldwork` |
| `재고자산실사` | `inventory_observation` |
| `금융자산실사` | `financial_asset_observation` |
| `외부조회` | `external_confirmations` |
| `지배기구와의커뮤니케이션` | `tcwg_communication` |
| `외부전문가` | `expert` |
| 그 밖 | `other` |

같은 `section=fieldwork` 또는 실사 `visit`이 여러 개여도 된다.
외부조회 `fields`의 `금융거래조회`·`채권채무조회`·`변호사조회`는 원문 그대로 `O`/`X`/`-`(별지 주 6).
`block`에서 남는 칸은 `unmapped_1`, `unmapped_2`, … 키로 `fields`에 넣는다. 버리지 않는다.

전반감사계획(`planning`)의 `수행시기`만 현장감사 회차와 같이 `{raw, start_date, end_date, days}`다. `parse_schedule`을 쓴다. 지배기구 블록의 `수행시기`(「중간감사 및 기말감사」 등)는 문자열로 둔다.

```json
{
  "section": "planning",
  "section_raw": "전반감사계획 (감사착수단계)",
  "row_type": "block",
  "fields": {
    "수행시기": {
      "raw": "2024.06.29 1 일",
      "start_date": "2024.06.29",
      "end_date": "2024.06.29",
      "days": 1
    },
    "주요내용": "감사계획 수립"
  }
}
```

### 4.3 `communications`

```json
{
  "has_audit_committee": true,
  "items": [
    {
      "구분": "1",
      "일자": "2024.05.14",
      "참석자": "감사위원회 위원 3명, 담당이사",
      "방식": "대면회의",
      "주요 논의 내용": "핵심감사사항 선정"
    }
  ]
}
```

`items` 키는 4절 표 헤더 원문(strip). 헤더가 비면 `col_0` … 을 쓴다.
`has_audit_committee`: **4절 표 본문** compact에 `감사위원회`가 있으면 true. 제목 `4. 감사(감사위원회)와의 커뮤니케이션`과 3절 `지배기구와의 커뮤니케이션`은 보지 않는다.

## 5. Selector

변경 없음. `activity_entry_id`는 compact `외부감사실시내용`. 내부회계·내부감시장치·감사의감사보고서는 계속 제외.

## 6. 파서

Viewer `extract_blocks`가 아니라 실시내용 HTML의 `table` 태그에서 읽는다.
`_parse_table`은 rowspan/colspan을 펼치지 않아 2절 헤더를 못 읽는다.
`activity_header.py`와 같이 BeautifulSoup 순수 함수다.

### 6.1 격자

`expand_table_matrix(table: Tag) -> list[list[str]]`.
원전 D-4-1 `MatrixGenerator`와 같이 colspan/rowspan을 칸에 복제한다. 셀은 strip만.
매칭은 `compact`. Viewer는 바꾸지 않는다.
`FindTargetTable`(첫 td>20 표)과 `matrix[i][j]` 하드코딩은 쓰지 않는다.

### 6.2 1절 헤더

기존 `extract_activity_header` 유지. 회사명·결산/사업연도 라벨만. 조인 키 `year_end`는 바꾸지 않는다.

### 6.3 2절 시간

문서 앞쪽부터, 펼친 격자 **앞 두 열**에 compact `투입인원수`가 있는 **첫 표**.
그 위 헤더 행에서 역할명을 읽고, `당기`/`전기`는 역할이 아니다.
각 지표 행 × 각 역할 열마다 `hours` 원소 하나.
헤더에 안 붙는 값 칸은 `unmapped: true`, `role=other` 또는 `metric=other`.

별지 주석 중 파서가 **값을 바꾸지 않는** 것: 별도·연결 합산(주 1②), 내부회계·수임검토 포함(주 1③), 등록/수습 기준일(주 2), 전문가 열 정의(주 3·4), 수주산업 전기 공란·감사인 변경 시 전기 수치(주 5), 인원 전원 기록(주 6), 외국어 보고서 시간 제외(주 7). 공시된 숫자를 재계산하거나 각주 텍스트를 파싱하지 않는다.

### 6.4 3절 실시내용

compact에 `주요감사실시내용`이 있는 `p`/heading **다음** 첫 표.
없으면 첫 행에 `구분`과 `내역`이 있고 `투입인원수`가 없는 표.
1열(펼친 뒤)이 비지 않으면 새 섹션, 비면 직전 섹션 연속.

**현장감사·재고실사·금융실사가 아닌 구분.** 알려진 라벨
(`수행시기`, `주요내용`, `투입인원`, `주요투입업무`, `주요감사업무수행내용`,
`금융거래조회`, `채권채무조회`, `변호사조회`, `기타조회`,
`커뮤니케이션횟수`, `횟수`, `수행내용`, `감사활용내용`)은
다음 비어 있지 않은 칸을 값으로 쓰고, 구분당 `row_type=block` 하나다.
전반감사계획 `수행시기`는 `parse_schedule`로 `{raw, start_date, end_date, days}`가 된다. 다른 블록의 `수행시기`는 문자열이다.

**현장감사.** 1열이 `현장감사`이거나 직전 섹션이 현장감사인 연속 행을 아래 순서로 원소화한다. 1열이 `재고자산실사` 등 다른 구분으로 바뀌면 끝이다.

1. compact가 `수행시기`이고 같은 행에 `투입인원`·`주요감사업무수행내용`(또는 `주요내용`)이 있으면 `row_type=column_header`. `labels`는 그 행의 비어 있지 않은 칸(구분 열 `현장감사` 제외) 원문 순서.
2. compact가 `상주`이고 같은 행(또는 바로 다음 헤더 행)에 `비상주`가 있으면 `row_type=sub_header`, `parent_label=투입인원`. 상주·비상주가 1행 헤더에 colspan으로만 있고 2행이 없으면, 펼친 격자에서 투입인원 아래 칸이 `상주`/`비상주`인 행을 `sub_header`로 쓴다. 헤더 행을 건너뛰지 않는다.
3. 그 다음부터 날짜 구간(`YYYY.MM.DD`~ 또는 `YY.MM.DD`~)이 새로 보이면 `visit`을 연다. 같은 회차에 상주·비상주·수행내용만 있으면 방금 연 `fields`에 붙인다.
   - `수행시기`는 실사 시기와 같다. `raw` 원문. `~`(전각 포함)로 나누면 `start_date`·`end_date`. 날짜가 하나면 둘 다 그 날(당일 실사). `days`는 `(N일)` 또는 옆 칸 숫자. 칸이 `27 | 일`로 나뉘면 `days=27`. 실패·`-`이면 날짜와 `days`는 null. ISO로 바꾸지 않는다. 공시 표기(`24.06.17` vs `2024.06.17`)를 유지한다.
   - `투입인원`은 `{"상주": {"raw", "count"}, "비상주": {"raw", "count"}}`이다. 한쪽만 있으면 있는 키만 둔다. `count`는 `20명`·`20 명`에서 읽은 정수이고, `-`·빈칸·비숫자면 **null**이다. 시간 표의 `-`→0과 달리 상주 `-`를 0명으로 바꾸지 않는다. 정수만 저장하지 않는다(`명`·원문 손실).
4. 빈 서식 줄(날짜 없고 `-`만)은 `visit`을 만들지 않는다. `column_header`·`sub_header`는 칸이 라벨이면 만든다.
5. 회차가 1번이면 `visit`도 1개다. 날짜 구간이 4개면 `visit`도 4개다. 서식 빈 칸 3줄에 맞추지 않는다.

**재고자산실사·금융자산실사.** 1열이 `재고자산실사` 또는 `금융자산실사`이거나 그 연속 행이다. 다른 구분으로 바뀌면 끝이다. 평탄 `item` 나열이나 `fields` 한 덩어리로 합치지 않는다.

알려진 compact 라벨 세 개(앞이 이김): `실사(입회)시기` → `실사(입회)장소` → `실사(입회)대상`. 짧은 `시기`/`장소`/`대상`만으로는 매칭하지 않는다.

- `실사(입회)시기`가 나오면 **새 `visit`**을 연다. 같은 회차의 장소·대상은 그 `visit.items`에 붙인다.
- 시기 `item`은 날짜와 기간(일수)을 나눈다. `raw`는 칸을 이은 원문. `(N일)`·단독 `일` 칸을 뺀 뒤 `~`가 있으면 `start_date`/`end_date`로 가른다. 예: `2015.2.2~2015.2.10 (7일)` → `start_date="2015.2.2"`, `end_date="2015.2.10"`, `days=7`. 날짜가 하나면(한화형 `2025.01.02 | 1 | 일`) `start_date`와 `end_date`가 같다. 파싱 실패·`-`이면 날짜와 `days`는 null. ISO로 바꾸지 않는다.
- 장소·대상만 있고 시기 라벨이 아직 없으면, 그 섹션의 첫 `visit`을 연 뒤 붙인다.
- 이미 장소가 있는 `visit`에 장소가 다시 나오면 새 `visit`이다(시기 라벨이 생략된 두 번째 실사).
- 한 행에 장소와 대상이 같이 있으면 그 회차 `items`에 두 개를 넣는다.
- 값이 `-`이거나 비어도 그 회차 `items`에 남긴다(별지 주 1). 시기만 `-`이고 장소·대상이 없는 빈 서식 칸은 `visit`을 만들지 않는다.
- 실사 1회면 `visit` 1개(`items` 최대 3). 실사 2회면 `visit` 2개.
- 세 라벨이 하나도 없으면 그 구간은 `row_type=block` 하나로 접고 칸은 `unmapped_*`다.

원전 D-4-2처럼 `재고자산실사(입회)`에서 루프를 끊지 않는다.
3절의 `지배기구와의 커뮤니케이션`은 `activities`의 `tcwg_communication`이지 4절이 아니다.

### 6.5 4절 커뮤니케이션

compact가 `4.`로 시작하거나 `감사(감사위원회)`를 포함하고, `와의커뮤니케이션`이 있는 제목 **다음** 첫 표.
3절 `지배기구와의커뮤니케이션`과 구분한다.
헤더 행 → `items` 키, 이후 행 → 회차. 빈 행은 건너뛴다.

### 6.6 5절

제목 `5. 감사인의 중요성 금액` 또는 그 다음 표가 있어도 **읽지 않는다.**
컬럼·상태를 두지 않는다. 별지 주: 일반 열람 보고서에 첨부할 때만 선택 기재.

### 6.7 상태

각 파서는 `(payload, status)`를 반환한다.

| 조건 | 세 필드 |
|------|---------|
| `activity_entry_id` 없음 또는 실시내용 HTML 없음 | 모두 `skipped`, JSON 기본 공값 |
| 2절 표를 읽음 | `hours_status=ok` |
| 2절 제목/표/`투입인원수` 행 없음 | `hours_status=not_found`, `hours=[]` |
| 3절 제목/표 없음 | `activities_status=not_found` |
| 4절 제목/표 없음 (2018 등) | `communications_status=not_found`. **접수연도로 skipped 하지 않음** |
| 5절 유무 | 상태 없음 |

표를 찾았으면 칸이 `-`이거나 비어도 `ok`다.

## 7. 값 해소

D-4 필드는 문서 원문이다. 우선순위 병합을 하지 않는다.
같은 `corp_code`+`year_end`+`fs_scope`의 F001/F002/A001 첨부 행과 시간을 비교하지 않는다.
별지 주 1②: 별도·연결 투입은 구별하지 않고 합산하므로, 두 행의 숫자가 같아도 오류가 아니다.

회사명·결산월 헤더 검증(`conflicts`)은 의견 추출과 같다.

## 8. 잡 · API

### 8.1 추출

기존 `POST /admin/extract/audit-opinion`.
`extractor_version`을 `audit_opinion.v4`로 올린다. v3 `ok` 행은 다음 추출에서 실시내용 URL을 다시 가져온다.
`reparse`: 기존 not_found 필드에 `hours_status`·`activities_status`·`communications_status`를 포함한다.

### 8.2 조회

`GET /api/v1/disclosures/{rcp_no}/audit-facts`와 연구 CSV에 6컬럼을 그대로 노출한다.
날짜 LLM 해소·`audit_report_date_override`와 섞지 않는다.

### 8.3 완전성

`field_partial` 핵심 필드에 세 상태를 넣는다. 기존과 같이 `ok`가 아니면( `skipped`·`not_found` 포함) 부분실패다.
실시내용 leaf가 없는 문서·4절이 없는 옛 공시는 의견 필드가 `ok`여도 `field_partial`이 된다. 추출기가 연도로 숨기지 않는다.
5절은 집계에 넣지 않는다.

## 9. 에러 · 동시성

의견 추출과 같다. 표 파싱 실패는 행을 버리지 않고 해당 필드만 `not_found`.
DART 재시도·차단, 카탈로그 수집과의 상호 배타는 그대로다.

## 10. 테스트

실제 DART 호출 없음. HTML fixture.

- 격자: rowspan/colspan 복제. Viewer `_parse_table` 행 길이는 그대로인지(전역 변경 없음).
- 2절: 당기/전기 7열 피벗, 비교 없는 표(`period=unknown`), `"-"`→`value=0`, 역할 `합계` vs 지표 `합계`, 옛 `기타` → `role=other`.
- 3절: 현장감사 `column_header` + `sub_header` + `visit` 3개, 수행시기는 `start_date`/`end_date`/`days`(하루면 start=end), 상주·비상주는 `raw`+`count`(정수 전용 아님, `-`는 count null), 재고·금융 실사는 회차당 `visit` 1개(안쪽 `items`가 시기·장소·대상), 시기 `item`은 `start_date`/`end_date`/`days`로 분리(`(7일)` 및 칸이 나뉜 `1 | 일`), 실사 2회면 `visit` 2개, `-`도 `items`에 남김, 외부조회 `O`/`X`/`-`, 3절 지배기구를 4절로 오인하지 않음, 재고 이후 외부전문가까지.
- 4절: 회차 `items`, 표 본문 `감사위원회`만 `has_audit_committee=true`, 제목만 있으면 false.
- 5절 제목·표가 있는 fixture에서도 hours/activities/communications 페이로드·상태에 중요성 금액이 없음.
- leaf 없음 → 세 필드 `skipped`. 2절만 있고 4절 없음 → hours `ok`, communications `not_found`.
- 완전성: 세 상태 중 `ok` 아닌 것이 있으면 `field_partial`. 5절 HTML 유무는 건수에 무관.
- 기존 의견·날짜·감사인 테스트가 v4 upsert 후에도 깨지지 않음.

## 11. 범위 밖

- D-5 첨부 재무제표 계정, D-6 내부회계 의견, D-7 정관·OCR
- 5절 감사인의 중요성 금액 (별지 선택 기재. 공시되지 않는 것이 일반적)
- 원문 HTML 저장, Viewer `_parse_table` 전역 격자화, 추출 히트맵 UI
- 별도/연결 시간 분리, 표준감사시간·숙련도 재계산
- 각주(주 1~9, 4절 주 1~3) 텍스트 파싱
- 실시내용 전용 Admin 화면

## 12. 디렉터리 (web-api)

```text
app/extracting/table_matrix.py              # expand_table_matrix
app/extracting/activity_hours.py            # 2절
app/extracting/activity_items.py            # 3절
app/extracting/activity_communication.py    # 4절
app/extracting/activity_header.py           # 1절 헤더 (유지)
app/extracting/constants.py                 # EXTRACTOR_VERSION = audit_opinion.v4
app/models/audit_report_fact.py             # 6컬럼
app/services/extraction_service.py          # 실시내용 파서 연결
app/services/completeness_service.py        # field_partial
app/schemas/facts.py                        # Public 응답
scripts/export_audit_report_facts.py        # 컬럼 자동 포함(모델 기준이면 추가 작업 최소)
```
