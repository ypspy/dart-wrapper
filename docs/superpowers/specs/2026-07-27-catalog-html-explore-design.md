# Catalog HTML 탐색 (공시 단위 leaf 표) 설계

날짜: 2026-07-27  
상태: 승인 (구현)  
범위: `packages/web-api` — Public HTML `/catalog` (본문 Viewer·열람 없음)

## 1. 목표

변경된 Catalog JSON 스키마의 **모든 필드**를 브라우저에서 표로 확인한다.

- 공시 목록 → 공시 1건의 leaf 전량
- 서버 렌더(Jinja). `CatalogQueryService` 재사용
- 인증 없음. Admin·Viewer 본문과 분리

## 2. 라우트

| 경로 | 역할 |
|------|------|
| `GET /catalog` | 공시 목록 표 (`DisclosureSummary` 전 컬럼) |
| `GET /catalog/{rcp_no}` | 공시 헤더 + leaf 표 (`EntrySummary` 전 컬럼) |

쿼리(목록): Catalog API와 동일하게 `limit`(기본 20, 최대 100), `cursor`, 선택 필터  
`corp_code`, `corp_name`, `report_nm`, `report_type`, `start_date`, `end_date`  
(1차에서는 **cursor + limit만** 노출해도 됨. 필터 폼은 선택.)

**1차 범위 (권장):** cursor 페이징만. 필터 폼은 후속.

## 3. 화면

### 3.1 `/catalog` — 공시 목록

가로 스크롤 가능한 `<table>`. 컬럼 순서(스키마 순):

1. `rcp_no` (링크 → `/catalog/{rcp_no}`)
2. `corp_code`
3. `corp_name`
4. `report_nm`
5. `report_type`
6. `correction_type`
7. `submitter`
8. `rcept_dt`
9. `year_end`
10. `bsns_year`
11. `entry_count`
12. `disclosure_url` (외부 링크)

하단: `next_cursor`가 있으면 «다음» → `?cursor=…&limit=…`

### 3.2 `/catalog/{rcp_no}` — leaf 목록

**상단:** 공시 메타 — `disclosure`(`DisclosureSummary`) 전 필드를  
정의 목록(`<dl>`) 또는 1행 표로 표시. `disclosure_url`은 외부 링크.

**본문:** `all_entries` 가로 스크롤 표. 컬럼 순서:

1. `ordinal`
2. `entry_id`
3. `rcept_no`
4. `report_type`
5. `correction_type`
6. `report_nm`
7. `year_end`
8. `corp_code`
9. `corp_name`
10. `submitter`
11. `rcept_dt`
12. `bsns_year`
13. `disclosure_url`
14. `source`
15. `dcm_no`
16. `document_name`
17. `section_name`
18. `section_original_name`
19. `depth`
20. `is_leaf`
21. `parent_ele_id`
22. `ele_id`
23. `offset`
24. `length`
25. `dtd`
26. `path` — ` › ` 로 join한 문자열
27. `viewer_url` — 외부 링크

상단 «목록으로» → `/catalog`.  
없는 `rcp_no` → 404 문구.

## 4. 구현 구조

| 경로 | 역할 |
|------|------|
| `app/api/catalog/ui.py` | `/catalog` 라우터, `include_in_schema=False` |
| `app/templates/catalog/base.html` | 최소 레이아웃 + 인라인 또는 `static/catalog.css` |
| `app/templates/catalog/list.html` | 공시 목록 표 |
| `app/templates/catalog/entries.html` | 공시 헤더 + leaf 표 |
| `tests/test_catalog_ui.py` | 목록·상세·404·컬럼명 존재 assert |

`main.py`에 라우터 등록. JSON `/api/v1/catalog/*` 변경 없음.

본문 Viewer / HTMX 섹션 로드 **없음**.

## 4.1 CSS · 레이아웃 (단순 / Skeleton)

- Admin·구 Browse CSS와 **완전 분리**. 인라인 `<style>` 또는 짧은 `static/catalog.css` 한 파일.
- **Skeleton 위주**: 여백·테두리·표만. 카드/그림자/그라데이션/장식 색 없음.
- 폰트: 시스템 스택 (`sans-serif` / 표 셀은 `monospace` 가능).
- 페이지 상단 바(제목·«목록으로»)는 `position: sticky; top: 0`으로 고정.
- 표는 `.table-scroll { overflow: auto; max-height: … }` 래퍼 안에 두고,
  **`thead th`는 `position: sticky; top: 0`(또는 상단 바 높이를 뺀 top)** 로 세로 스크롤 시 열 헤더 고정.
- 가로 스크롤은 래퍼에서 처리. sticky는 세로 헤더 고정이 1차 목표(열 고정 freeze는 범위 밖).

## 5. null·표시

- `null` / 빈 값 → 셀에 `—`
- `path` → `A › B › C`
- boolean → `true` / `false`

## 6. 테스트

1. `/catalog` 200, `DisclosureSummary` 컬럼 헤더 전부 존재
2. fixture 공시 링크 → `/catalog/{rcp}` 200, leaf 컬럼 헤더 전부 + `ordinal` 순 데이터
3. 없는 rcp → 404
4. cursor 다음 링크 존재(있을 때)

## 7. 범위 밖

- 본문 열람 / Viewer 연동
- 필터 폼(1차)
- Admin 통합
- Catalog JSON 추가 변경
- 첫 열(rcp_no/ordinal) 가로 freeze
- 다크 테마·디자인 시스템 확장

## 8. README

루트·web-api README에 `http://127.0.0.1:8000/catalog` 한 줄 추가.
