# Admin Ops Console (좌우 분할 · 30년 완전성) 설계

- 날짜: 2026-07-26
- 상태: 승인됨(설계) / 스펙 리뷰 대기
- 선행:
  - `2026-07-25-admin-ops-resume-design.md` (재개·슬라이스 완전성 모델·Admin UI)
  - `2026-07-25-completeness-heatmap-design.md` (53주 히트맵·색 규칙)

## 1. 배경 · 목표

파싱 대상은 1998년 말부터 약 30년 치다. 현재 `/admin`은 폼 → 53주 히트맵 →
슬라이스 표를 세로로 쌓아, 완전성 탐색과 진행 모니터링이 한 화면에서
불편하게 섞여 있다.

목표는 **정보 배치와 상호작용만** 바꿔, 화면을 두 가지 주 업무에 맞춰
좌우로 분할하는 것이다.

- **완전성 탐색(gap-finding)**: 어느 연도·어느 날짜가 비었는지 빠르게 찾기
- **실행/모니터링(live job)**: 지금 도는 작업 상태와 로그를 항상 보기

수집 파이프라인·재개 로직·완전성 판정·히트맵 색 의미는 **바꾸지 않는다.**

## 2. 화면 구조 (좌우 master–detail)

`/admin` 대시보드를 상단 바 + 2열 그리드로 재구성한다.

```
┌───────────────────────────────────────────────────────────┐
│ 상단 바: 제목 · 현재 job 상태 칩(running/idle …)             │
├───────────────────────────────┬───────────────────────────┤
│ 좌: 완전성 탐색 (넓게)         │ 우: 실행 컨트롤             │
│  ① 연도 요약 바 (~30년)       │  ① Job 상태 카드(항상)     │
│  ② 선택 연도 일별 히트맵      │  ② 수집 폼(기본 접힘)      │
│  ③ 선택 연도 슬라이스 요약    │  ③ 로그(warn/error 기본)   │
└───────────────────────────────┴───────────────────────────┘
```

- 그리드 비율은 좌:우 ≈ 1.4:1. 좁은 화면(예: `max-width: 900px`)에서는
  세로 스택으로 자연스럽게 떨어지는 fallback만 둔다(모바일 전용 최적화는 안 함).
- 기존 세로 스택(폼 → 히트맵 → 표)은 제거한다.

## 3. 좌측: 완전성 탐색

### 3.1 연도 요약 바

- ~1999년부터 현재까지 연도당 막대 1개(가장 오래된 슬라이스 연도 ~ 올해).
- 색은 기존 규칙과 동일:
  - 초록 `#2ea043`: 그 해가 `complete`(아래 판정 참고)
  - 빨강 `#d1242f`: 슬라이스는 있으나 미완성 존재
  - 회색 `#ebedf0`(다크 `#30363d`): 그 해 슬라이스 없음(미입수)
- **연 단위 판정**: 해당 연도·(선택된 타입 필터 범위) 안에서
  - 슬라이스가 하나도 없으면 `missing`
  - 미완성 슬라이스(status ≠ complete)가 하나라도 있으면 `incomplete`
  - 전부 complete면 `complete`
  - 판정은 기존 `SliceProgress.status`만 사용하고 새 상태를 만들지 않는다.
- 막대 클릭 → 그 연도를 선택하고 아래 일별 히트맵을 그 해로 교체한다.
- 기본 선택 연도: **가장 최근 `incomplete` 연도**, 없으면 최신 연도.

### 3.2 선택 연도 일별 히트맵

- 기존 53주 GitHub형 그리드·색·툴팁·월 라벨 규칙을 재사용한다.
- 창이 “오늘 기준 최근 53주”에서 **“선택 연도 1년”**으로 바뀐다:
  - 시작 = 그 해 1월 1일이 속한 주의 일요일
  - 끝 = 그 해 12월 31일(단, 올해는 오늘까지만; 이후 셀은 `future`로 비움)
- 셀 클릭 동작:
  - 슬라이스 있음 → 기존 슬라이스 상세(`/admin/slices/{id}`)
  - 슬라이스 없음/미완성 → 우측 **수집 폼을 펼치고** 해당 타입·날짜를 채운다.
- 셀 아래 **선택 요약**: `YYYY-MM-DD · 상태 · slice_id`와
  “이 날부터 수집 →”(폼 펼치기+프리필) 링크.

### 3.3 선택 연도 슬라이스 요약

- 전체 긴 테이블 대신 선택 연도의 문제 슬라이스(blocked/incomplete)를
  짧은 칩/리스트로 보여준다.
- “전체 보기”로 기존 슬라이스 테이블(확장 패널 또는 별도 영역) 접근.

## 4. 우측: 실행 컨트롤

### 4.1 Job 상태 카드 (항상 표시)

- 최근/활성 job 하나를 항상 보여준다:
  상태 칩·진행률 바·범위·체크포인트(rcp_no)·성공/실패/blocked 수·
  일시정지/소프트스톱 버튼(기존 `/admin/catalog/jobs/{id}/soft-stop` 재사용).
- 데이터 출처: 기존 `CatalogService.get_status(job_id)`(`JobStatusResponse`).
- job_id 없이 최신 job을 얻기 위해 `JobRepository`에 **최신 job 조회 메서드**를
  추가한다(예: `latest() -> CatalogJob | None`, `started_at` 내림차순 1건).
  활성 job이 없으면 카드는 “대기(idle)”와 마지막 완료 job 요약을 보인다.
- HTMX 폴링으로 주기 갱신(진행 중 5s, idle 30s 정도).

### 4.2 수집 폼 (기본 접힘)

- 기본 접힘. 아래 트리거로만 펼친다:
  - 좌측 히트맵의 미완성/미입수 셀 클릭(타입·날짜 프리필)
  - “수집 시작 / 펼치기” 버튼
- 필드·동작은 기존 `/admin/collect` POST 그대로.

### 4.3 로그 (접을 수 있음)

- 기본은 **warn/error만** 표시, 접기 가능. info는 필터 토글로 표시.
- 데이터 출처: `JobStatusResponse`의 최근 로그(`recent_logs`).
- 상태 카드와 같은 job_id·폴링을 공유한다.

## 5. 데이터 · API 변경

UI 재배치에 필요한 최소 추가만 한다. 기존 엔드포인트는 유지한다.

### 5.1 연도 요약

- `SliceRepository`: 연도별 상태 집계에 쓸 조회.
  - 옵션 A(권장): 기존 `list_slices_between`로 `[최소연도-01-01, 올해-12-31]`
    범위를 한 번 읽어 서비스에서 연 단위로 접는다.
  - 대량이면 옵션 B: SQL `GROUP BY year, (status=complete)` 집계 메서드 추가.
    1인 운영·연 30개 버킷이므로 **A로 시작**하고 느리면 B로 승격.
- `SliceQueryService.year_summary(report_type=None) -> YearSummaryResponse`:
  - 연도 리스트(오래된 슬라이스 연도 ~ 올해)와 각 연도 level(complete/incomplete/missing).
  - 기본 선택 연도(가장 최근 incomplete, 없으면 최신)도 함께 반환.

### 5.2 선택 연도 일별 히트맵

- `SliceQueryService.heatmap(...)`을 **연도 파라미터**를 받도록 확장한다:
  - `heatmap(year: int | None = None, report_type: str | None = None)`.
  - `year=None`이면 현행(최근 53주) 동작을 유지해 회귀를 막는다.
  - `year`가 오면 그 해 1/1 주의 일요일 ~ 12/31(또는 오늘) 창으로 격자 생성.
  - 주 수는 연초 요일에 따라 가변(보통 53, 경우에 따라 최대 54열)이므로
    `WEEK_COUNT` 상수 대신 시작~끝에서 계산한다. 월 라벨도 이 창 기준.
- 라우트: `GET /admin/heatmap`에 `?year=&report_type=` 쿼리 추가.

### 5.3 Job 상태·로그 partial

- `JobRepository.latest()` 추가.
- Admin UI 라우트 추가:
  - `GET /admin/job-status` → 최신/지정 job의 상태 카드 partial(HTML).
  - `GET /admin/job-logs` → 로그 partial(HTML, level 필터 쿼리).
  - 두 partial 모두 기존 `get_status`/`recent_logs` 데이터를 렌더만 한다.

### 5.4 스키마 (`app/schemas/catalog.py`)

- `YearSummaryItem { year: int, level: Literal["complete","incomplete","missing"] }`
- `YearSummaryResponse { items: list[YearSummaryItem], selected_year: int }`
- 히트맵 응답은 기존 `HeatmapResponse` 재사용(연도 창만 바뀜).

## 6. 템플릿 구조

- `admin/index.html`: 2열 그리드 + 상단 바로 재작성.
- partial 분리:
  - `partials/year_bar.html`(연도 요약)
  - `partials/heatmap.html`(기존, 연도 창으로 재사용)
  - `partials/slices_summary.html`(선택 연도 요약 칩)
  - `partials/job_card.html`(상태 카드)
  - `partials/collect_form.html`(접힘 폼)
  - `partials/job_logs.html`(로그)
- CSS는 `base.html`에 그리드·카드·연도 바 스타일 추가(기존 히트맵 CSS 유지).
- 상호작용은 HTMX 중심. 셀→폼 프리필은 `hx-get`으로 폼 partial을 열고
  값을 채우는 방식(경량 JS 최소화).

## 7. 에러 처리

- 슬라이스/연도 데이터 없음: 연도 바·히트맵은 전부 `missing`(회색)로 표시,
  빈 화면 대신 “아직 수집 이력이 없습니다” 안내.
- 활성 job 없음: 상태 카드는 idle + 마지막 완료 job 요약(없으면 안내).
- 잘못된 `year`(범위 밖/비숫자): 최신 연도로 폴백.
- 인증 실패: 기존과 동일하게 `/admin/token`으로 리다이렉트.
- 모든 사용자 메시지·로그·예외는 한국어.

## 8. 테스트

- `SliceQueryService.year_summary`: 빈 데이터/전부 complete/일부 incomplete/
  기본 선택 연도 선정 로직.
- `heatmap(year=...)`: 연초 일요일 정렬, 올해의 future 컷오프,
  `year=None` 회귀(기존 53주와 동일).
- `JobRepository.latest`: 활성/완료/없음.
- 라우트 스모크: `/admin`(2열 렌더), `/admin/heatmap?year=`,
  `/admin/job-status`, `/admin/job-logs`(인증 유무 포함).
- 기존 Admin/히트맵 테스트가 계속 통과하는지 회귀 확인.

## 9. 비범위

- 수집 파이프라인·재개 알고리즘 변경
- 완전성 판정 규칙 변경(기존 `SliceProgress.status` 그대로)
- Public 뷰어, 새 JS 차트 라이브러리 도입
- 30년 전체를 일별 셀로 한 화면에 렌더
- 다국어, 모바일 전용 레이아웃 최적화(좁은 화면 세로 스택 fallback만)
