# Admin 완전성 히트맵 (GitHub Contribution 스타일) 설계

- 날짜: 2026-07-25
- 상태: 승인됨
- 선행: `2026-07-25-admin-ops-resume-design.md` (슬라이스 완전성 모델·Admin UI)

## 1. 목표

Admin 대시보드(`/admin`)에 GitHub Overview의 contribution 그래프와 같은
**날짜×요일 히트맵**을 추가해, 보고서 타입별 수집 완전성을 1년 치 한눈에 보이게 한다.

- 초록: 그 날짜 슬라이스가 `complete`
- 빨강: 슬라이스는 있으나 미완성 (`pending` / `running` / `failed` / `blocked`)
- 옅은 회색: 슬라이스 없음(미입수)
- 미래 날짜: 칸을 그리지 않음(투명)

## 2. 범위

### 포함

- 대시보드 상단(수집 폼 아래, 슬라이스 표 위)에 히트맵 섹션
- 보고서 타입마다 히트맵 한 줄씩 세로로 쌓기
- 표시 타입 = **고정 목록(설정) + DB에만 있는 타입을 뒤에 추가**
- 칸 클릭: 슬라이스 있으면 상세(`/admin/slices/{id}`),
  없으면 수집 폼에 해당 타입·날짜가 채워진 대시보드(`/admin?...`)로 이동
- 칸 hover: 툴팁 — `YYYY-MM-DD · 상태 · 성공/목록 건수`
- HTMX 주기 갱신(슬라이스 표와 동일한 패턴, 단 30초 간격)

### 제외

- Public 화면 노출, 월/연 단위 집계 화면
- 완전성 판정 로직 변경(기존 `SliceProgress.status` 그대로 사용)
- JS 차트 라이브러리 도입

## 3. 표시 규칙 (GitHub 규칙 준수)

- 기간: **오늘을 포함한 최근 53주**. 시작일은 `오늘 - 52주`가 속한 주의 **일요일**.
- 격자: 열 = 주(왼쪽이 과거), 행 = 요일(일요일 위, 토요일 아래).
- 상단에 월 라벨(해당 월의 첫 주 열 위에 표시), 왼쪽에 요일 라벨(월·수·금만).
- 오늘 이후 날짜는 렌더링하지 않는다.
- 범례: 미입수(회색) → 미완성(빨강) → 완료(초록).

색상 값(라이트/다크 공통으로 무난한 톤):

| 상태 | 색 |
|------|-----|
| 완료(complete) | `#2ea043` |
| 미완성(그 외 상태) | `#d1242f` |
| 미입수(슬라이스 없음) | `#ebedf0` (다크: `#30363d`) |

## 4. 데이터 흐름

### 설정 (`app/config.py`)

```python
# 히트맵에 항상 표시할 보고서 타입(쉼표 구분 env: HEATMAP_REPORT_TYPES)
heatmap_report_types: list[str] = ["A001", "F001"]
```

- pydantic-settings의 JSON/쉼표 파싱을 사용. `.env.example`에 예시 추가.

### 저장소 (`SliceRepository`)

- `list_slices`는 `limit` 기본 100이라 1년치×타입에 부족.
- 새 메서드 `list_slices_between(start_date, end_date)` 추가:
  기간 내 **모든 타입**의 슬라이스를 limit 없이 반환.

### 서비스 (`SliceQueryService`)

새 메서드 `heatmap(today: date | None = None) -> HeatmapResponse`:

1. 기간 계산(최근 53주, 일요일 시작)
2. `list_slices_between`으로 기간 내 슬라이스 조회
3. `(report_type, slice_date) → SliceSummary` 매핑
4. 타입 순서 = 설정 고정 목록 + (DB에서 발견됐지만 목록에 없는 타입, 코드 오름차순)
5. 주×요일 격자로 펼친 `HeatmapResponse` 반환

### 스키마 (`app/schemas/catalog.py`)

```python
class HeatmapCell(BaseModel):
    slice_date: str            # YYYYMMDD
    level: str                 # "complete" | "incomplete" | "missing" | "future"
    slice_id: str | None
    status: str | None         # 원본 슬라이스 상태
    succeeded: int = 0
    listed_count: int | None = None

class HeatmapRow(BaseModel):
    report_type: str
    weeks: list[list[HeatmapCell]]   # 53주 × 7일 (열 우선)

class HeatmapResponse(BaseModel):
    month_labels: list[tuple[int, str]]  # (주 인덱스, "Jan" 등)
    rows: list[HeatmapRow]
```

## 5. UI

### 라우트 (`app/api/admin/ui.py`)

- `GET /admin` — 컨텍스트에 `heatmap` 추가
- `GET /admin/heatmap` — HTMX 부분 갱신용 partial (쿠키 토큰 검사 동일)
- `GET /admin`은 `report_type` / `start_date` / `end_date` 쿼리를 받으면
  수집 폼 기본값으로 사용(미입수 칸 클릭 → 폼 프리필)

### 템플릿

- `templates/admin/partials/heatmap.html`
  - 타입별로: 왼쪽 라벨 + CSS Grid(`grid-auto-flow: column`, 7행) 격자
  - 셀 = `<a>` (링크 + `title` 툴팁), 크기 11px, 간격 2px
  - 미래 셀은 링크 없는 투명 `<span>`
- `templates/admin/index.html`
  - "연간 수집 완전성" 섹션 + `hx-get="/admin/heatmap" hx-trigger="every 30s"`
- `templates/admin/base.html`
  - 히트맵 색상·격자 CSS 추가 (다크 모드는 `prefers-color-scheme`로 회색만 교체)

## 6. 테스트

1. **서비스**: 고정 타입 2개 + DB 슬라이스(다른 타입 1개) →
   행 순서·주 수(53)·상태 매핑(`complete`/`incomplete`/`missing`/`future`) 검증
2. **서비스**: 기간 밖 슬라이스는 무시되는지
3. **UI 스모크**: `/admin`에 히트맵 렌더(타입 라벨·범례 노출),
   미입수 칸의 href가 폼 프리필 링크인지, complete 칸의 href가 슬라이스 상세인지
4. **UI**: `/admin/heatmap` partial이 토큰 없이 접근 시 토큰 페이지로 리다이렉트

## 7. 결정 기록

- 타입별 세로 스택(1안) — 한눈 비교 우선
- 고정 목록 + DB 발견 타입 추가(3안) — 아직 안 돌린 타입의 빈칸을 놓치지 않기 위함
- 클릭 + 툴팁(3안)
- 서버 렌더 Jinja + HTMX(A안) — 기존 스택 유지, 의존성 없음
