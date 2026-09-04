# 외부감사 실시내용 추출 (D-4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실시내용 leaf HTML에서 별지 제4호 1~4절을 읽어 `audit_report_facts`의 JSON·상태 컬럼에 저장하고, 기존 추출 잡·Public API·완전성에 붙인다.

**Architecture:** Viewer `_parse_table`은 그대로 둔다. D-4 전용 `expand_table_matrix`로 rowspan/colspan을 펼친 뒤, 라벨로 2·3·4절을 순수 함수 파싱한다. 기존 `POST /admin/extract/audit-opinion`이 이미 fetch하는 실시내용 HTML에 연결한다. 5절은 읽지 않는다.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2 async, BeautifulSoup/lxml, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-08-31-audit-activity-extraction-design.md`

## Global Constraints

- Python 3.11+, 모든 함수 타입 힌트
- 주석·Docstring·로그·예외·테스트 설명은 한국어
- extracting 순수 함수는 sync. I/O는 async
- Black/Flake8, line length 100
- 테스트는 실제 DART를 호출하지 않음
- 작업 디렉터리 기본: `packages/web-api`
- 실행 시 git 커밋은 **사용자가 요청한 경우에만**. 아래 Commit 스텝은 메시지 초안이다
- OpenDART 사용 금지. HTML 원문 DB 저장 금지
- Viewer `_parse_table` 전역 격자화 금지. `FindTargetTable`(td>20) 금지
- 5절 중요성 금액 파싱 금지

---

## File map

| 파일 | 역할 |
|------|------|
| `app/extracting/table_matrix.py` | `expand_table_matrix` |
| `app/extracting/activity_schedule.py` | `parse_schedule`, `parse_headcount` |
| `app/extracting/activity_hours.py` | 2절 시간 |
| `app/extracting/activity_items.py` | 3절 실시내용 |
| `app/extracting/activity_communication.py` | 4절 |
| `app/extracting/activity_header.py` | 1절 헤더 (유지) |
| `app/extracting/constants.py` | `EXTRACTOR_VERSION = "audit_opinion.v4"` |
| `app/models/audit_report_fact.py` | 6컬럼 |
| `app/db/session.py` | 기존 DB ALTER 패치 |
| `app/services/extraction_service.py` | 파서 연결, reparse 대상 |
| `app/services/completeness_service.py` | `field_partial` |
| `app/schemas/facts.py` | Public 응답 |
| `packages/web-api/README.md` | 추출 필드 설명 |

---

### Task 1: 격자 펼침

**Files:**
- Create: `app/extracting/table_matrix.py`
- Test: `tests/test_extracting_table_matrix.py`
- Modify: 없음 (Viewer `app/parsing/blocks.py` 금지)

**Interfaces:**
- Consumes: `bs4.Tag`
- Produces: `expand_table_matrix(table: Tag) -> list[list[str]]`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from bs4 import BeautifulSoup

from app.extracting.table_matrix import expand_table_matrix
from app.parsing.blocks import extract_blocks


def _table(html: str):
    soup = BeautifulSoup(f"<html><body>{html}</body></html>", "lxml")
    return soup.find("table")


def test_expand_repeats_rowspan_and_colspan() -> None:
    """병합 칸이 격자의 각 칸에 복제된다."""
    table = _table(
        """
        <table>
          <tr><td rowspan="2">투입 인원수</td><td>당기</td><td>10</td></tr>
          <tr><td>전기</td><td>8</td></tr>
          <tr><td colspan="2">합계</td><td>18</td></tr>
        </table>
        """
    )
    matrix = expand_table_matrix(table)
    assert matrix[0][0] == "투입 인원수"
    assert matrix[1][0] == "투입 인원수"
    assert matrix[2][0] == "합계"
    assert matrix[2][1] == "합계"
    assert matrix[0][2] == "10"


def test_viewer_parse_table_does_not_expand_span() -> None:
    """D-4 격자와 달리 Viewer는 행 길이가 제각각이다."""
    html = """
    <html><body>
    <table>
      <tr><td rowspan="2">A</td><td>1</td></tr>
      <tr><td>2</td></tr>
    </table>
    </body></html>
    """
    blocks = extract_blocks(html)
    table = next(b for b in blocks if b.type == "table")
    assert len(table.rows[0]) != len(table.rows[1]) or table.rows[0][0] != "A" or (
        len(table.rows[1]) < 2
    )
```

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `pytest tests/test_extracting_table_matrix.py -v`  
Expected: FAIL (`expand_table_matrix` 없음)

- [ ] **Step 3: 최소 구현**

`app/extracting/table_matrix.py`:

```python
"""실시내용 표의 rowspan/colspan을 격자로 펼친다."""

from __future__ import annotations

from bs4 import Tag


def _span(cell: Tag, name: str) -> int:
    try:
        return max(int(cell.get(name, 1)), 1)
    except (TypeError, ValueError):
        return 1


def expand_table_matrix(table: Tag) -> list[list[str]]:
    """colspan/rowspan을 칸에 복제한 2차원 리스트를 반환한다.

    셀은 strip만 한다. 매칭용 compact는 호출측에서 한다.
    """
    rows = table.find_all("tr")
    column_count = 0
    for row in rows:
        width = 0
        for cell in row.find_all(["th", "td"]):
            width += _span(cell, "colspan")
        column_count = max(column_count, width)

    matrix = [["#" for _ in range(column_count)] for _ in rows]
    for row_index, row in enumerate(rows):
        locator = [i for i, value in enumerate(matrix[row_index]) if value == "#"]
        offset = 0
        for cell in row.find_all(["th", "td"]):
            text = cell.get_text(" ", strip=True)
            row_span = _span(cell, "rowspan")
            col_span = _span(cell, "colspan")
            for down in range(row_span):
                for right in range(col_span):
                    matrix[row_index + down][locator[offset + right]] = text
            offset += col_span
    return matrix
```

`test_viewer_parse_table_does_not_expand_span`의 단언이 환경에 따라 약하면, Viewer 첫 데이터 행 길이가 1이고 둘째가 1인지만 봐도 된다. 요지는 **blocks 행에 rowspan 복제가 없다**.

- [ ] **Step 4: 테스트 실행 (통과 확인)**

Run: `pytest tests/test_extracting_table_matrix.py -v`  
Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/table_matrix.py packages/web-api/tests/test_extracting_table_matrix.py
git commit -m "feat: 실시내용 표 rowspan/colspan 격자를 펼친다"
```

---

### Task 2: 수행시기·투입인원 파서

**Files:**
- Create: `app/extracting/activity_schedule.py`
- Test: `tests/test_extracting_activity_schedule.py`

**Interfaces:**
- Consumes: `compact` (`app.extracting.text`)
- Produces:
  - `parse_schedule(raw: str) -> dict[str, object]`  
    키: `raw`(str), `start_date`(str|None), `end_date`(str|None), `days`(int|None)
  - `parse_headcount(raw: str) -> dict[str, object]`  
    키: `raw`(str), `count`(int|None)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from app.extracting.activity_schedule import parse_headcount, parse_schedule


def test_parse_schedule_splits_range_and_days() -> None:
    result = parse_schedule("24.06.17~24.07.14 (27일)")
    assert result["raw"] == "24.06.17~24.07.14 (27일)"
    assert result["start_date"] == "24.06.17"
    assert result["end_date"] == "24.07.14"
    assert result["days"] == 27


def test_parse_schedule_single_day_sets_start_equal_end() -> None:
    result = parse_schedule("2025.01.02 (1일)")
    assert result["start_date"] == "2025.01.02"
    assert result["end_date"] == "2025.01.02"
    assert result["days"] == 1


def test_parse_schedule_dash_is_null() -> None:
    result = parse_schedule("-")
    assert result["start_date"] is None
    assert result["end_date"] is None
    assert result["days"] is None


def test_parse_headcount_reads_number_keeps_raw() -> None:
    result = parse_headcount("20명")
    assert result["raw"] == "20명"
    assert result["count"] == 20


def test_parse_headcount_dash_is_null_not_zero() -> None:
    result = parse_headcount("-")
    assert result["count"] is None
```

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `pytest tests/test_extracting_activity_schedule.py -v`  
Expected: FAIL

- [ ] **Step 3: 최소 구현**

```python
"""현장감사·실사 시기와 상주 인원 숫자 파싱."""

from __future__ import annotations

import re

from app.extracting.text import compact

_DAYS = re.compile(r"\(?\s*(\d+)\s*일\s*\)?")
_RANGE = re.compile(
    r"(\d{2,4}\.\d{1,2}\.\d{1,2})\s*[~～]\s*(\d{2,4}\.\d{1,2}\.\d{1,2})"
)
_ONE = re.compile(r"(\d{2,4}\.\d{1,2}\.\d{1,2})")
_COUNT = re.compile(r"(\d+)")


def parse_schedule(raw: str) -> dict[str, object]:
    """원문에서 start_date·end_date·days를 읽는다. ISO로 바꾸지 않는다."""
    text = raw.strip()
    if compact(text) in {"", "-"}:
        return {"raw": raw, "start_date": None, "end_date": None, "days": None}
    days: int | None = None
    days_match = _DAYS.search(text)
    if days_match:
        days = int(days_match.group(1))
    date_part = _DAYS.sub("", text).strip(" ,/")
    start: str | None = None
    end: str | None = None
    ranged = _RANGE.search(date_part)
    if ranged:
        start, end = ranged.group(1), ranged.group(2)
    else:
        one = _ONE.search(date_part)
        if one:
            start = end = one.group(1)
    return {"raw": raw, "start_date": start, "end_date": end, "days": days}


def parse_headcount(raw: str) -> dict[str, object]:
    """상주·비상주 원문과 선택적 정수를 반환한다. '-'는 0이 아니다."""
    text = raw.strip()
    if compact(text) in {"", "-"}:
        return {"raw": raw, "count": None}
    match = _COUNT.search(text)
    return {"raw": raw, "count": int(match.group(1)) if match else None}
```

- [ ] **Step 4: 테스트 실행 (통과 확인)**

Run: `pytest tests/test_extracting_activity_schedule.py -v`  
Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/activity_schedule.py packages/web-api/tests/test_extracting_activity_schedule.py
git commit -m "feat: 실시내용 수행시기·투입인원 숫자 파서"
```

---

### Task 3: 2절 시간 피벗

**Files:**
- Create: `app/extracting/activity_hours.py`
- Test: `tests/test_extracting_activity_hours.py`

**Interfaces:**
- Consumes: `expand_table_matrix`, `compact`
- Produces: `extract_hours(html: str) -> tuple[list[dict[str, object]], str]`  
  원소 키: `role`, `role_raw`, `metric`, `metric_raw`, `period`, `period_raw`, `raw`, `value`, `unmapped`  
  상태: `ok` / `not_found`

- [ ] **Step 1: 실패하는 테스트 작성**

비교표시 7열 중 일부만 있어도 된다. 최소 fixture:

```python
from app.extracting.activity_hours import extract_hours

_COMPARATIVE = """
<html><body>
<table>
<tr>
  <td rowspan="2">구분</td>
  <td colspan="2">담당이사<br/>(업무수행이사)</td>
  <td colspan="2">합계</td>
</tr>
<tr><td>당기</td><td>전기</td><td>당기</td><td>전기</td></tr>
<tr><td>투입 인원수</td><td></td><td>1</td><td>1</td><td>2</td><td>2</td></tr>
<tr><td rowspan="3">투입시간</td><td>분·반기검토</td><td>10</td><td>-</td><td>10</td><td>-</td></tr>
<tr><td>감사</td><td>100</td><td>80</td><td>100</td><td>80</td></tr>
<tr><td>합계</td><td>110</td><td>80</td><td>110</td><td>80</td></tr>
</table>
</body></html>
"""


def test_extract_hours_comparative_roles_and_metrics() -> None:
    cells, status = extract_hours(_COMPARATIVE)
    assert status == "ok"
    audit_partner = next(
        c
        for c in cells
        if c["role"] == "engagement_partner"
        and c["metric"] == "audit"
        and c["period"] == "current"
    )
    assert audit_partner["value"] == 100
    dash = next(
        c
        for c in cells
        if c["metric"] == "interim_review"
        and c["period"] == "prior"
        and c["role"] == "engagement_partner"
    )
    assert dash["raw"] == "-"
    assert dash["value"] == 0
    totals = [c for c in cells if c["role"] == "total" and c["metric"] == "total"]
    assert len(totals) == 2


def test_extract_hours_missing_table_is_not_found() -> None:
    cells, status = extract_hours("<html><body><p>없음</p></body></html>")
    assert status == "not_found"
    assert cells == []


def test_extract_hours_legacy_other_role() -> None:
    html = """
    <html><body>
    <table>
    <tr><td></td><td>기타</td></tr>
    <tr><td>투입 인원수</td><td>3</td></tr>
    </table>
    </body></html>
    """
    cells, status = extract_hours(html)
    assert status == "ok"
    assert any(c["role"] == "other" and c["value"] == 3 for c in cells)
```

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `pytest tests/test_extracting_activity_hours.py -v`  
Expected: FAIL

- [ ] **Step 3: 최소 구현**

요지:

1. soup의 각 `table`을 `expand_table_matrix`.
2. 앞 두 열 compact에 `투입인원수`가 있는 **첫 표**.
3. 그 행보다 위는 헤더. 각 열 `role`은 스펙 표 순서대로 compact 매칭 (`수주산업`을 `specialist`보다 먼저). 열 헤더 compact가 정확히 `합계`이면 `role=total`. `당기`/`전기`는 역할이 아니다.
4. 지표 행: 앞 두 열에 `투입인원수` → `headcount`, `분ㆍ반기검토`/`분·반기검토`/`분기검토`/`반기검토` → `interim_review`, 정확히 `합계` → `total`, 정확히 `감사`이면서 `감사참여자`·`감사업무`·`감사시간`이 없으면 `audit`.
5. 값 칸: 쉼표 제거 정수. `-`·공백 → `value=0`. 숫자 아님 → `null`.
6. `period`: 그 열 헤더 또는 행 칸에 `당기`/`전기`. 없으면 `unknown`.
7. 역할 헤더가 비면 `unmapped=True`, `role=other`.

`extract_hours` 시그니처는 위 Interfaces와 동일.

- [ ] **Step 4: 테스트 실행 (통과 확인)**

Run: `pytest tests/test_extracting_activity_hours.py -v`  
Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/activity_hours.py packages/web-api/tests/test_extracting_activity_hours.py
git commit -m "feat: 외부감사 실시내용 2절 투입시간과 인원을 피벗한다"
```

---

### Task 4: 4절 커뮤니케이션

**Files:**
- Create: `app/extracting/activity_communication.py`
- Test: `tests/test_extracting_activity_communication.py`

**Interfaces:**
- Consumes: `expand_table_matrix`, `compact`
- Produces: `extract_communications(html: str) -> tuple[dict[str, object], str]`  
  payload: `{"has_audit_committee": bool, "items": list[dict[str, str]]}`  
  상태: `ok` / `not_found`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from app.extracting.activity_communication import extract_communications

_HTML = """
<html><body>
<p>3. 주요 감사실시내용</p>
<table><tr><td>지배기구와의 커뮤니케이션</td><td>감사위원회</td></tr></table>
<p>4. 감사(감사위원회)와의 커뮤니케이션</p>
<table>
<tr><th>구분</th><th>일자</th><th>참석자</th><th>방식</th><th>주요 논의 내용</th></tr>
<tr><td>1</td><td>2024.05.14</td><td>회사측: 감사위원회 위원 3명</td><td>대면회의</td><td>1분기</td></tr>
</table>
<p>5. 감사인의 중요성 금액</p>
<table><tr><td>재무제표 전체 중요성</td><td>10억원</td></tr></table>
</body></html>
"""


def test_communications_reads_section_four_not_three_or_five() -> None:
    payload, status = extract_communications(_HTML)
    assert status == "ok"
    assert payload["has_audit_committee"] is True
    assert payload["items"][0]["일자"] == "2024.05.14"
    assert "10억원" not in str(payload)


def test_title_alone_is_not_audit_committee() -> None:
    html = """
    <html><body>
    <p>4. 감사(감사위원회)와의 커뮤니케이션</p>
    <table>
    <tr><th>구분</th><th>일자</th><th>참석자</th></tr>
    <tr><td>1</td><td>2019.03.01</td><td>감사 1명</td></tr>
    </table>
    </body></html>
    """
    payload, status = extract_communications(html)
    assert status == "ok"
    assert payload["has_audit_committee"] is False


def test_missing_section_four_is_not_found() -> None:
    payload, status = extract_communications("<html><body><p>3. 주요</p></body></html>")
    assert status == "not_found"
    assert payload["items"] == []
    assert payload["has_audit_committee"] is False
```

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `pytest tests/test_extracting_activity_communication.py -v`  
Expected: FAIL

- [ ] **Step 3: 최소 구현**

1. `p`/heading compact가 `와의커뮤니케이션`을 포함하고 (`4.`로 시작하거나 `감사(감사위원회)` 포함). `지배기구와의커뮤니케이션`은 제외.
2. 그 노드 **다음 형제** 중 첫 `table`.
3. 첫 행 헤더 → 키(strip). 빈 헤더는 `col_{i}`.
4. 이후 비어 있지 않은 행 → `items` 원소.
5. `has_audit_committee`: **표 본문** `compact(table.get_text())`에 `감사위원회`. 제목 문자열은 보지 않음.
6. 5절 표는 제목 다음이므로 4절 다음 형제가 아니면 읽지 않음.

기본 공값: `{"has_audit_committee": False, "items": []}`.

- [ ] **Step 4: 테스트 실행 (통과 확인)**

Run: `pytest tests/test_extracting_activity_communication.py -v`  
Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/activity_communication.py packages/web-api/tests/test_extracting_activity_communication.py
git commit -m "feat: 외부감사 실시내용 4절 커뮤니케이션을 읽는다"
```

---

### Task 5: 3절 실시내용

**Files:**
- Create: `app/extracting/activity_items.py`
- Test: `tests/test_extracting_activity_items.py`

**Interfaces:**
- Consumes: `expand_table_matrix`, `compact`, `parse_schedule`, `parse_headcount`
- Produces: `extract_activities(html: str) -> tuple[list[dict[str, object]], str]`

- [ ] **Step 1: 실패하는 테스트 작성**

현장감사 헤더+회차 1, 재고 실사 1회(시기 분리), 금융 실사 `-`, 외부조회 O/X, 3절 지배기구, 외부전문가, 5절 무시. HTML은 별지 구조를 단순화한 fixture로 둔다.

필수 단언:

- `row_type=="column_header"` 이고 labels에 `수행시기`, `투입인원`
- `row_type=="sub_header"` 이고 `parent_label=="투입인원"`, labels에 `상주`
- fieldwork `visit`의 `수행시기["start_date"]`/`end_date`/`days`
- `투입인원["상주"]["count"]`는 int, `raw`에 `명`
- inventory `visit` 1개, `items`에 시기·장소·대상. 시기 `start_date==end_date`
- 실사 2회 fixture(시기 라벨 두 번) → inventory `visit` 2개
- 외부조회 `fields["금융거래조회"]=="O"`
- `section=="tcwg_communication"` 인 `block`이 있고, 4절이 아님
- 본문에 `중요성` 금액 표가 있어도 activities에 `10억원` 없음
- 3절 표 없으면 `not_found`, `[]`

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `pytest tests/test_extracting_activity_items.py -v`  
Expected: FAIL

- [ ] **Step 3: 최소 구현**

표 선정: compact `주요감사실시내용`인 `p`/heading 다음 첫 table. 없으면 첫 행에 `구분`과 `내역`이 있고 `투입인원수`가 없는 table.

행 순회(펼친 격자). 1열 compact로 섹션 전환.

**fieldwork:** 스펙 6.4 1~5. `parse_schedule` / `parse_headcount` 사용.

**inventory / financial:** `실사(입회)시기` → 새 visit. `parse_schedule`을 시기 item에 펼쳐 `label`과 함께 넣음. 장소·대상은 `{label, raw}`. 시기만 `-`이고 장소·대상 없으면 visit 생략.

**기타:** `planning`, `external_confirmations`, `tcwg_communication`, `expert`, `other` → `row_type=block`, 알려진 라벨 다음 칸을 `fields`. 외부조회 O/X/- 원문 유지. 잔여 칸 `unmapped_N`.

루프를 재고실사에서 끊지 않는다.

- [ ] **Step 4: 테스트 실행 (통과 확인)**

Run: `pytest tests/test_extracting_activity_items.py -v`  
Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/activity_items.py packages/web-api/tests/test_extracting_activity_items.py
git commit -m "feat: 외부감사 실시내용 3절을 회차·항목으로 읽는다"
```

---

### Task 6: 모델·스키마·버전

**Files:**
- Modify: `app/extracting/constants.py` (`audit_opinion.v4`)
- Modify: `app/models/audit_report_fact.py` (6컬럼)
- Modify: `app/schemas/facts.py`
- Modify: `app/db/session.py` `_COLUMN_PATCHES`
- Modify: `tests/test_audit_report_fact_repository.py` (v3 하드코딩 → v4)
- Test: `tests/test_ensure_schema.py`에 facts 컬럼 보강 케이스 추가

**Interfaces:**
- Consumes: 없음
- Produces: ORM/응답에 `hours`, `activities`, `communications`, `hours_status`, `activities_status`, `communications_status`

기본값: `hours=[]`, `activities=[]`, `communications={"has_audit_committee": False, "items": []}`. 상태는 nullable str.

기존 DB용 `_COLUMN_PATCHES` 예 (SQLite / PostgreSQL):

- `hours` / `activities`: `TEXT NOT NULL DEFAULT '[]'` / `JSONB NOT NULL DEFAULT '[]'::jsonb`
- `communications`: 기본 `'{"has_audit_committee":false,"items":[]}'`
- 세 `*_status`: `VARCHAR(32)`

- [ ] **Step 1: 테스트**  
`test_audit_report_fact_repository.py`의 `assert EXTRACTOR_VERSION == "audit_opinion.v3"`를 `v4`로 바꾸고, ensure_schema가 레거시 `audit_report_facts`(새 컬럼 없음)에 `hours`를 추가하는 테스트를 넣는다.

- [ ] **Step 2: 실패 확인**  
`pytest tests/test_audit_report_fact_repository.py tests/test_ensure_schema.py -v`  
Expected: FAIL (버전 또는 컬럼)

- [ ] **Step 3: 모델·패치·스키마 수정**

`AuditReportFact`에 JSON 컬럼 3 + status 3. `AuditReportFactItem`에 동일 필드(LLM 메타는 계속 비공개).

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_audit_report_fact_repository.py tests/test_ensure_schema.py tests/test_facts_api.py -v`  
Expected: PASS (`facts_api`는 새 필드 기본값으로 깨지지 않아야 함)

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/constants.py packages/web-api/app/models/audit_report_fact.py packages/web-api/app/schemas/facts.py packages/web-api/app/db/session.py packages/web-api/tests/test_audit_report_fact_repository.py packages/web-api/tests/test_ensure_schema.py
git commit -m "feat: 실시내용 JSON·상태 컬럼과 extractor v4"
```

---

### Task 7: 추출 잡 연결

**Files:**
- Modify: `app/services/extraction_service.py` (`_assemble`의 activity_html, `_NOT_FOUND_STATUSES`)
- Test: `tests/test_extraction_service.py`에 실시내용 fixture 행 단언 추가

**Interfaces:**
- Consumes: `extract_hours`, `extract_activities`, `extract_communications`
- Produces: 같은 `AuditReportFact` 행에 6필드. leaf 없으면 세 상태 `skipped`, JSON 기본 공값. HTML 있으면 각 파서 status 저장. 형제 행 시간 conflict 추가 없음.

- [ ] **Step 1: 실패하는 테스트**  
기존 extraction 테스트용 실시내용 HTML에 2절 `투입 인원수` 표를 넣고, 저장된 fact의 `hours_status=="ok"`, `hours` 비어 있지 않음. 4절 없는 HTML은 `communications_status=="not_found"`. activity leaf가 없는 문서는 세 상태 `skipped`.

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_extraction_service.py -v`  
Expected: FAIL (컬럼 비어 있음)

- [ ] **Step 3: `_assemble`에서 `activity_html`이 있으면 세 파서 호출, 없으면 skipped.**  
`_NOT_FOUND_STATUSES`에 `hours_status`, `activities_status`, `communications_status` 추가.

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_extraction_service.py -v`  
Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/services/extraction_service.py packages/web-api/tests/test_extraction_service.py
git commit -m "feat: 의견 추출 잡에 실시내용 1~4절을 붙인다"
```

---

### Task 8: 완전성·Public·문서

**Files:**
- Modify: `app/services/completeness_service.py` `_FIELD_STATUS_ATTRS`
- Modify: `tests/test_extract_admin_api.py` (`field_partial`이 새 skipped/not_found를 포함하는지)
- Modify: `tests/test_facts_api.py` (hours JSON이 응답에 있는지)
- Modify: `packages/web-api/README.md` (추출 필드·field_partial 설명)

**Interfaces:**
- Consumes: Task 6 컬럼
- Produces: `field_partial`에 세 상태 포함. 5절은 집계 키 없음.

- [ ] **Step 1: 테스트**  
fetch ok + 의견 필드 ok + `communications_status=not_found` → `field_partial==1`.  
Public GET 본문에 `hours` 키.

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_extract_admin_api.py tests/test_facts_api.py -v`  
Expected: 새 단언 FAIL

- [ ] **Step 3: completeness attrs에 세 status 추가. README에 실시내용 JSON·4절 없는 옛 공시가 field_partial이 됨·5절 미추출을 한 줄씩.**

- [ ] **Step 4: 관련 테스트 + 파서 테스트 일괄**

Run: `pytest tests/test_extracting_table_matrix.py tests/test_extracting_activity_schedule.py tests/test_extracting_activity_hours.py tests/test_extracting_activity_communication.py tests/test_extracting_activity_items.py tests/test_extraction_service.py tests/test_extract_admin_api.py tests/test_facts_api.py tests/test_blocks.py -v`  
Expected: PASS. `test_blocks`는 Viewer 표 파서가 안 바뀌었음을 확인.

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/services/completeness_service.py packages/web-api/tests/test_extract_admin_api.py packages/web-api/tests/test_facts_api.py packages/web-api/README.md
git commit -m "feat: 실시내용 상태를 완전성·Public 조회에 넣는다"
```

---

## Spec coverage

| 스펙 | 작업 |
|------|------|
| 6.1 격자, Viewer 불변 | Task 1 |
| 수행시기 start/end/days, 상주 raw+count | Task 2, 5 |
| 2절 피벗, `-`→0, 역할/지표 합계 | Task 3 |
| 3절 회차·실사 visit.items, 5절 무시 | Task 5, 4 |
| 4절, 제목 오탐 방지 | Task 4 |
| 컬럼·v4·기존 DB | Task 6 |
| 같은 잡, skipped/not_found, reparse | Task 7 |
| field_partial, API, README | Task 8 |
| D-5~7, 5절 파싱, 별도/연결 분리 | 작업 없음 |
