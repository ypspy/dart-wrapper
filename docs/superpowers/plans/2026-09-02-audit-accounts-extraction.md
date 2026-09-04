# 첨부 재무제표 계정 추출 (D-5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 감사보고서 첨부 제표 HTML에서 E-4 여덟 계정의 당기·전기 금액을 읽어 `audit_report_facts.accounts`에 저장하고, 기존 추출 잡·Public API·완전성에 붙인다.

**Architecture:** Viewer `_parse_table`은 그대로 둔다. D-4 `expand_table_matrix`로 본표를 펼친 뒤, 헤더로 열 역할(과목·주석·당기/전기 내역·합계)을 정하고 라벨로 계정만 집는다. 기존 `POST /admin/extract/audit-opinion`이 BS/IS leaf(없으면 제표 부모)를 추가로 fetch한다.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2 async, BeautifulSoup/lxml, pytest

**Spec:** `docs/superpowers/specs/2026-09-02-audit-accounts-extraction-design.md`

## Global Constraints

- Python 3.11+, 모든 함수 타입 힌트
- 주석·Docstring·로그·예외·테스트 설명은 한국어
- extracting 순수 함수는 sync. I/O는 async
- Black/Flake8, line length 100
- 테스트는 실제 DART를 호출하지 않음
- 작업 디렉터리 기본: `packages/web-api`
- 실행: `.\.venv\Scripts\python.exe -m pytest <path> -q`
- git 커밋은 **사용자가 요청한 경우에만**. 아래 Commit 스텝은 메시지 초안이다
- OpenDART 사용 금지. HTML 원문 DB 저장 금지
- Viewer `_parse_table` 전역 격자화 금지. `FindTargetTable`(td>20)·`len % 2` 칸 인덱스 금지
- D-6·D-7, 본표 전 행 덤프, 별도/연결 금액 conflict 금지

---

## File map

| 파일 | 역할 |
|------|------|
| `app/extracting/selector.py` | `LeafIds`에 BS/IS/부모 id |
| `app/extracting/accounts.py` | `cut_notes`, `extract_accounts` |
| `app/extracting/constants.py` | `EXTRACTOR_VERSION = "audit_opinion.v11"` |
| `app/models/audit_report_fact.py` | `accounts` 컬럼 |
| `app/db/session.py` | `ensure_schema` 패치 |
| `app/services/extraction_service.py` | 제표 fetch + 파서, reparse |
| `app/services/completeness_service.py` | `field_partial` |
| `app/schemas/facts.py` | Public 응답 |
| `packages/web-api/README.md` | v11·계정 필드 |

---

### Task 1: Selector — 제표 leaf·부모

**Files:**
- Modify: `app/extracting/selector.py`
- Test: `tests/test_extracting_selector.py`

**Interfaces:**
- Consumes: 기존 `SelectorEntry`, `select_leaves`, `is_audit_document`(변경 없음)
- Produces: `LeafIds`에 `bs_entry_id: str | None`, `is_entry_id: str | None`, `fs_parent_entry_id: str | None`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_extracting_selector.py`에 추가한다. `SelectorEntry` 생성자 순서는 기존과 같다 (`entry_id, rcept_no, dcm_no, report_type, source, document_name, section_name`).

```python
def test_select_leaves_prefers_bs_is_leaves() -> None:
    """재무상태표·손익계산서 leaf가 있으면 부모를 쓰지 않는다."""
    rows = [
        SelectorEntry("c", "r", "d", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry("p", "r", "d", "F001", "body", "감사보고서", "(첨부)재무제표"),
        SelectorEntry("bs", "r", "d", "F001", "body", "감사보고서", "재무상태표"),
        SelectorEntry("is_", "r", "d", "F001", "body", "감사보고서", "손익계산서"),
        SelectorEntry("n", "r", "d", "F001", "body", "감사보고서", "주석"),
    ]
    leaves = select_leaves(rows)
    assert leaves.bs_entry_id == "bs"
    assert leaves.is_entry_id == "is_"
    assert leaves.fs_parent_entry_id is None


def test_select_leaves_consolidated_statement_names() -> None:
    """연결 제표 섹션명을 BS/IS로 고른다."""
    rows = [
        SelectorEntry("c", "r", "d", "F002", "body", "연결감사보고서", "감사보고서"),
        SelectorEntry("bs", "r", "d", "F002", "body", "연결감사보고서", "연결재무상태표"),
        SelectorEntry("is_", "r", "d", "F002", "body", "연결감사보고서", "연결손익계산서"),
    ]
    leaves = select_leaves(rows)
    assert leaves.bs_entry_id == "bs"
    assert leaves.is_entry_id == "is_"


def test_select_leaves_falls_back_to_fs_parent_when_only_notes() -> None:
    """본표 leaf가 없고 주석만 있으면 부모 (첨부)연결재무제표를 쓴다."""
    rows = [
        SelectorEntry("c", "r", "d", "F002", "body", "연결감사보고서", "감사보고서"),
        SelectorEntry("p", "r", "d", "F002", "body", "연결감사보고서", "(첨부)연결재무제표"),
        SelectorEntry("n", "r", "d", "F002", "body", "연결감사보고서", "주석"),
    ]
    leaves = select_leaves(rows)
    assert leaves.bs_entry_id is None
    assert leaves.is_entry_id is None
    assert leaves.fs_parent_entry_id == "p"


def test_select_leaves_prefers_income_over_comprehensive() -> None:
    """손익계산서가 있으면 포괄손익계산서를 IS로 쓰지 않는다."""
    rows = [
        SelectorEntry("c", "r", "d", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry("is_", "r", "d", "F001", "body", "감사보고서", "손익계산서"),
        SelectorEntry("ci", "r", "d", "F001", "body", "감사보고서", "포괄손익계산서"),
    ]
    leaves = select_leaves(rows)
    assert leaves.is_entry_id == "is_"


def test_select_leaves_ignores_other_dcm_statements() -> None:
    """다른 dcm의 제표는 고르지 않는다."""
    rows = [
        SelectorEntry("c", "r", "d1", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry("bs", "r", "d2", "F001", "body", "감사보고서", "재무상태표"),
    ]
    leaves = select_leaves(rows)
    assert leaves.bs_entry_id is None
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_selector.py::test_select_leaves_prefers_bs_is_leaves -q`

Expected: FAIL (`LeafIds`에 `bs_entry_id` 없음 또는 값이 None)

- [ ] **Step 3: 최소 구현**

`LeafIds`에 세 필드를 추가한다. `select_leaves`는 기존처럼 `_first_audit_dcm_no`로 감사 dcm을 고른 뒤, 그 dcm entry만 본다.

```python
# selector.py 요지 (전체 파일을 이 조각으로 바꾸지 말고 필드·헬퍼만 추가)

@dataclass(frozen=True)
class LeafIds:
    cover_entry_id: str | None
    opinion_entry_id: str | None
    activity_entry_id: str | None
    a001_opinion_entry_id: str | None
    a001_cover_entry_id: str | None
    bs_entry_id: str | None
    is_entry_id: str | None
    fs_parent_entry_id: str | None


def _is_notes_section(entry: SelectorEntry) -> bool:
    return compact(entry.section_name) == "주석"


def _is_bs_section(entry: SelectorEntry) -> bool:
    token = compact(entry.section_name)
    if _is_notes_section(entry):
        return False
    return "연결재무상태표" in token or "재무상태표" in token


def _is_is_section(entry: SelectorEntry) -> bool:
    token = compact(entry.section_name)
    if _is_notes_section(entry) or "자본변동" in token or "현금흐름" in token:
        return False
    if "연결손익계산서" in token or (
        "손익계산서" in token and "포괄" not in token
    ):
        return True
    return False


def _is_ci_section(entry: SelectorEntry) -> bool:
    token = compact(entry.section_name)
    return "포괄손익계산서" in token


def _is_fs_parent(entry: SelectorEntry) -> bool:
    token = compact(entry.section_name)
    return "첨부재무제표" in token and "주석" not in token
```

`select_leaves` 끝에서 `audit_entries` 기준으로:

```python
bs_entry_id = next((e.entry_id for e in audit_entries if _is_bs_section(e)), None)
is_entry_id = next((e.entry_id for e in audit_entries if _is_is_section(e)), None)
if is_entry_id is None:
    is_entry_id = next((e.entry_id for e in audit_entries if _is_ci_section(e)), None)
fs_parent_entry_id = None
if bs_entry_id is None and is_entry_id is None:
    fs_parent_entry_id = next(
        (e.entry_id for e in audit_entries if _is_fs_parent(e)),
        None,
    )
```

`LeafIds(...)` 호출에 세 인자를 넣는다. 기존 테스트가 깨지면 새 필드만 채운다.

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_selector.py -q`

Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/selector.py packages/web-api/tests/test_extracting_selector.py
git commit -m "feat: 제표 BS/IS/부모 leaf를 selector에 넣는다"
```

---

### Task 2: 5칸 본표 — 내역/합계 금액

**Files:**
- Create: `app/extracting/accounts.py`
- Test: `tests/test_extracting_accounts.py`

**Interfaces:**
- Consumes: `expand_table_matrix`, `compact`
- Produces: `extract_accounts(*, bs_html: str | None, is_html: str | None) -> tuple[list[dict[str, object]], str]`
  원소 키: `account`, `account_raw`, `period`, `period_raw`, `raw`, `value`, `unit_raw`, `unit_scale`, `value_won`, `status`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""첨부 제표 계정 추출 테스트."""

from app.extracting.accounts import extract_accounts


_FIVE_COL_BS = """
<html><body>
<p>재무상태표</p>
<p>회사명 : 예 (단위 : 원)</p>
<table>
<tr>
  <td>과 목</td><td>제 3(당) 기</td><td>제 3(당) 기</td>
  <td>제 2(전) 기</td><td>제 2(전) 기</td>
</tr>
<tr><td>Ⅰ. 유동자산</td><td></td><td>665,809,879</td><td></td><td>622,084,856</td></tr>
<tr><td>1. 현금및현금성자산(주석 3)</td><td>173,181,742</td><td></td><td>198,404,558</td><td></td></tr>
<tr><td>자 산 총 계</td><td></td><td>30,665,809,879</td><td></td><td>30,322,084,856</td></tr>
<tr><td>Ⅰ. 자본금</td><td></td><td>100</td><td></td><td>100</td></tr>
<tr><td>자 본 총 계</td><td></td><td>100</td><td></td><td>100</td></tr>
<tr><td>부채와자본총계</td><td></td><td>30,665,809,879</td><td></td><td>30,322,084,856</td></tr>
</table>
</body></html>
"""


def _by_account_period(rows: list[dict], account: str, period: str) -> dict:
    return next(r for r in rows if r["account"] == account and r["period"] == period)


def test_extract_accounts_five_col_uses_pair_not_blank() -> None:
    """5칸 표에서 총계는 합계 칸, 공란 내역은 0이 아니다."""
    accounts, status = extract_accounts(bs_html=_FIVE_COL_BS, is_html=None)
    assert status == "ok"
    total = _by_account_period(accounts, "total_asset", "current")
    assert total["value"] == 30665809879
    assert total["value_won"] == 30665809879
    assert total["unit_scale"] == 1
    assert total["period"] == "current"
    prior = _by_account_period(accounts, "total_asset", "prior")
    assert prior["value"] == 30322084856
    equity = _by_account_period(accounts, "total_equity", "current")
    assert equity["value"] == 100
    assert not any(r["account"] == "total_equity" and "부채" in (r["account_raw"] or "") for r in accounts)
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py::test_extract_accounts_five_col_uses_pair_not_blank -q`

Expected: FAIL (`extract_accounts` import 오류)

- [ ] **Step 3: 최소 구현**

`app/extracting/accounts.py`를 만든다. 동작 요지:

1. `bs_html`·`is_html`이 둘 다 없으면 `([], "skipped")`.
2. BeautifulSoup + 제목 `재무상태표` 다음 열≥3 표, 없으면 compact `부채` 또는 `자산총계` 표.
3. 표 앞 `p`/`td`에서 `단위` 줄 → `원` 1, `천원` 1000, `백만원` 1_000_000.
4. 헤더 행에서 `주석`/`주기`→note, `(당)기`/`당기`→current 그룹, `(전)기`/`전기`→prior 그룹. 그룹 칸 2개면 왼쪽 내역·오른쪽 합계.
5. 각 데이터 행: note가 아닌 빈 칸이 아닌 셀을 라벨로 compact. `_account_of(label)`로 키. 이미 본 계정은 건너뜀.
6. 기간별 금액 칸 중 비어 있지 않은 쪽. 둘 다 있으면 `total_asset`/`total_equity`/`net_income`은 합계, 나머지는 내역.
7. `-`/`－` → value 0. 쉼표 제거 정수. `value_won = value * unit_scale` (scale null이면 value_won null).
8. 표를 읽었으면 여덟 계정 × 헤더에 있는 기간을 채움. 못 찾은 계정은 `status=not_found`.
9. 표를 하나도 못 찾으면 `([], "not_found")`. 하나라도 읽으면 `ok`.

`_ACCOUNT_RULES` 순서는 스펙 표와 같게 (장기매출을 매출채보다 먼저). `net_income` 제외 키워드 스펙 그대로. `부채와자본총계`/`부채및자본총계`는 `total_equity`가 아니다 (`자본총계`만).

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py -q`

Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/accounts.py packages/web-api/tests/test_extracting_accounts.py
git commit -m "feat: 5칸 제표에서 자산·자본총계를 읽는다"
```

---

### Task 3: 6칸·4칸·단위·IS·예외 행

**Files:**
- Modify: `app/extracting/accounts.py`
- Test: `tests/test_extracting_accounts.py`

**Interfaces:**
- Consumes: Task 2 `extract_accounts`
- Produces: 동일 시그니처. `cut_notes(html: str) -> str` (부모 HTML용, `주석 ` 앞)

- [ ] **Step 1: 실패하는 테스트 작성**

같은 테스트 파일에 추가:

```python
_SIX_COL = """
<html><body>
<p>재무상태표</p>
<p>(단위: 천원)</p>
<table>
<tr>
  <td>과 목</td><td>주석</td>
  <td>제 9 (당)기</td><td>제 9 (당)기</td>
  <td>제 8 (전)기</td><td>제 8 (전)기</td>
</tr>
<tr><td>매출채권및기타채권</td><td>4,6</td><td>123,367</td><td></td><td>44,901</td><td></td></tr>
<tr><td>재고자산</td><td>7</td><td>27,435</td><td></td><td>46,508</td><td></td></tr>
<tr><td>자 산 총 계</td><td></td><td></td><td>825,062</td><td></td><td>685,537</td></tr>
<tr><td>자 본 총 계</td><td></td><td></td><td>316,553</td><td></td><td>265,039</td></tr>
</table>
<p>포괄손익계산서</p>
<table>
<tr>
  <td>과 목</td><td>주석</td>
  <td>제 9 (당)기</td><td>제 9 (당)기</td>
  <td>제 8 (전)기</td><td>제 8 (전)기</td>
</tr>
<tr><td>XI.당기순이익</td><td></td><td></td><td>22,755</td><td></td><td>12,095</td></tr>
<tr><td>XV. 당기총포괄이익</td><td></td><td></td><td>11,226</td><td></td><td>4,010</td></tr>
</table>
</body></html>
"""

_FOUR_COL = """
<html><body>
<p>재무상태표</p>
<p>(단위 : 원)</p>
<table>
<tr><td>과 목</td><td>주 석</td><td>제 8(당) 기말</td><td>제 7(전) 기말</td></tr>
<tr><td>매출채권</td><td>3,5</td><td>21,738,646,030</td><td>19,325,663,336</td></tr>
<tr><td>재고자산</td><td>8</td><td>13,054,289,195</td><td>12,002,449,673</td></tr>
<tr><td>자 산 총 계</td><td></td><td>93,277,152,562</td><td>91,337,960,197</td></tr>
<tr><td>자 본 총 계</td><td></td><td>67,463,232,976</td><td>63,561,665,542</td></tr>
<tr><td>계약자산</td><td>9</td><td>-</td><td>15,621,952</td></tr>
</table>
</body></html>
"""

_EQUITY_CHANGE = """
<html><body>
<table>
<tr><td>과 목</td><td>자본금</td><td>이익잉여금</td><td>총 계</td></tr>
<tr><td>당기순이익</td><td>-</td><td>12,095</td><td>12,095</td></tr>
</table>
</body></html>
"""


def test_extract_accounts_six_col_skips_note_column() -> None:
    """6칸 주석 열은 금액이 아니고, 재고는 내역·총계는 합계 칸이다."""
    accounts, status = extract_accounts(bs_html=_SIX_COL, is_html=_SIX_COL)
    assert status == "ok"
    inv = _by_account_period(accounts, "inventory", "current")
    assert inv["value"] == 27435
    assert inv["unit_scale"] == 1000
    assert inv["value_won"] == 27435000
    rec = _by_account_period(accounts, "receivable", "current")
    assert rec["value"] == 123367
    total = _by_account_period(accounts, "total_asset", "current")
    assert total["value"] == 825062
    ni = _by_account_period(accounts, "net_income", "current")
    assert ni["value"] == 22755
    assert not any(
        r["account"] == "net_income" and r["value"] == 11226 for r in accounts
    )


def test_extract_accounts_four_col_dash_is_zero() -> None:
    """4칸 표의 '-' 금액은 0이고 주석 공란은 무시한다."""
    accounts, status = extract_accounts(bs_html=_FOUR_COL, is_html=None)
    assert status == "ok"
    contract = _by_account_period(accounts, "contract_asset", "current")
    assert contract["value"] == 0
    assert contract["value_won"] == 0
    assert contract["raw"] in {"-", "－"}
    missing = _by_account_period(accounts, "unbilled", "current")
    assert missing["status"] == "not_found"
    assert missing["value"] is None


def test_extract_accounts_ignores_equity_change_net_income() -> None:
    """자본변동표만 있으면 당기순을 읽지 않는다."""
    accounts, status = extract_accounts(bs_html=None, is_html=_EQUITY_CHANGE)
    assert status == "not_found"
    assert accounts == []


def test_extract_accounts_no_html_is_skipped() -> None:
    """제표 HTML이 없으면 skipped다."""
    accounts, status = extract_accounts(bs_html=None, is_html=None)
    assert status == "skipped"
    assert accounts == []
```

`cut_notes` 테스트:

```python
from app.extracting.accounts import cut_notes


def test_cut_notes_drops_after_notes_heading() -> None:
    """부모 HTML은 '주석 ' 앞만 남긴다."""
    html = "<p>재무상태표</p><table><tr><td>자산총계</td></tr></table>주석 1. 중요한"
    assert "자산총계" in cut_notes(html)
    assert "중요한" not in cut_notes(html)
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py -q`

Expected: FAIL (6칸 주석을 금액으로 읽거나 IS 표를 자본변동과 구분 못 함)

- [ ] **Step 3: 구현을 테스트에 맞춤**

- IS 표: 제목 `손익계산서`/`포괄손익계산서` 다음 표, 없으면 `당기순`이 있고 `미처분`·`미처리`·`이익잉여금`이 **없는** 표.
- 헤더 `주석`/`주기` 열은 금액 그룹에 넣지 않음.
- `cut_notes`: `html.split("주석 ", 1)[0]` (원전과 같이 공백 있는 `주석 `).
- 단위는 각 HTML에서 독립적으로 읽는다. 같은 HTML을 bs·is에 넣으면 같은 scale.

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py tests/test_extracting_selector.py -q`

Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/accounts.py packages/web-api/tests/test_extracting_accounts.py
git commit -m "feat: 4·6칸 제표와 당기순·단위를 읽는다"
```

---

### Task 4: 모델·스키마·v11

**Files:**
- Modify: `app/models/audit_report_fact.py`
- Modify: `app/db/session.py` (`_COLUMN_PATCHES`)
- Modify: `app/extracting/constants.py`
- Modify: `app/schemas/facts.py`
- Modify: `tests/test_audit_report_fact_repository.py`
- Modify: `tests/test_ensure_schema.py`
- Modify: `tests/test_extraction_service.py` (버전 문자열 `v10` → `v11`)
- Modify: `packages/web-api/README.md`

**Interfaces:**
- Consumes: 기존 `AuditReportFact`, `ensure_schema`
- Produces: 컬럼 `accounts`(JSON list, default `[]`), `accounts_status`, `bs_entry_id`, `is_entry_id`, `fs_parent_entry_id`. `EXTRACTOR_VERSION == "audit_opinion.v11"`

- [ ] **Step 1: 실패하는 테스트 수정/추가**

`SPEC_FACT_COLUMNS`에 `bs_entry_id`, `is_entry_id`, `fs_parent_entry_id`, `accounts`, `accounts_status`를 넣고 `_make_fact` 기본값:

```python
"bs_entry_id": None,
"is_entry_id": None,
"fs_parent_entry_id": None,
"accounts": [],
"accounts_status": "skipped",
```

`test_audit_report_fact_repository.py`의 `assert EXTRACTOR_VERSION == "audit_opinion.v10"` → `v11`.

`test_ensure_schema.py`에 hours 테스트와 같이 `accounts` 컬럼이 레거시 테이블에 생기는지 단언을 추가하거나, 기존 hours 테스트의 CREATE TABLE 이후 `PRAGMA`에 `accounts`가 있는지를 추가로 assert한다.

`test_extraction_service.py`의 `audit_opinion.v10` 두 곳을 `v11`로 바꾸고, 기존 skipped 단언에 `assert fact.accounts_status == "skipped"`와 `assert fact.accounts == []`를 넣는다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_audit_report_fact_repository.py tests/test_ensure_schema.py -q`

Expected: FAIL (컬럼 없음 또는 버전 불일치)

- [ ] **Step 3: 모델·패치·상수**

`AuditReportFact`:

```python
bs_entry_id: Mapped[str | None] = mapped_column(String(128))
is_entry_id: Mapped[str | None] = mapped_column(String(128))
fs_parent_entry_id: Mapped[str | None] = mapped_column(String(128))
accounts: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
accounts_status: Mapped[str | None] = mapped_column(String(32))
```

`session.py` `_COLUMN_PATCHES`에 D-4 hours와 같은 패턴으로 `accounts`(TEXT `'[]'` / JSONB), `accounts_status`, `bs_entry_id`, `is_entry_id`, `fs_parent_entry_id`를 추가.

`AuditReportFactItem`에 동일 필드.

README 추출기 버전 `v10` → `v11`, 계정 JSON 한 줄 설명.

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_audit_report_fact_repository.py tests/test_ensure_schema.py tests/test_facts_api.py tests/test_extraction_service.py -q`

Expected: `test_extraction_service`는 아직 `accounts_status`를 안 넣으면 skipped 단언이 FAIL할 수 있다. 그 경우 Task 5에서 채운다. **이 스텝에서는 `_build_fact`에 `accounts=[]`, `accounts_status="skipped"` 기본만 넣어 기존 잡 테스트가 통과하게 한다.** 제표 fetch는 Task 5.

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/models/audit_report_fact.py packages/web-api/app/db/session.py packages/web-api/app/extracting/constants.py packages/web-api/app/schemas/facts.py packages/web-api/tests packages/web-api/README.md
git commit -m "feat: 계정 JSON 컬럼과 extractor v11을 둔다"
```

---

### Task 5: 추출 잡에 제표 fetch·파서 연결

**Files:**
- Modify: `app/services/extraction_service.py`
- Test: `tests/test_extraction_service.py`

**Interfaces:**
- Consumes: `select_leaves`의 `bs_entry_id`/`is_entry_id`/`fs_parent_entry_id`, `extract_accounts`, `cut_notes`
- Produces: `_build_fact`가 `accounts`, `accounts_status`, 세 entry id를 채움. `_NOT_FOUND_STATUSES`에 `accounts_status`. `_LEAF_ROLES`에 `bs_entry_id`, `is_entry_id`만 추가 (부모는 별도). 부모는 BS·IS가 **둘 다 없을 때만** fetch하고 `cut_notes` 후 `extract_accounts(bs_html=cut, is_html=cut)`

- [ ] **Step 1: 실패하는 테스트 작성**

`test_extraction_service.py`에 제표 HTML을 응답하는 케이스를 추가한다. 기존 `_service` MockTransport에 `재무상태표` viewer_url을 매핑.

기존 fixture entry에 더해:

```python
_FS_HTML = """
<html><body>
<p>재무상태표</p>
<p>(단위 : 원)</p>
<table>
<tr><td>과 목</td><td>주석</td><td>당기</td><td>전기</td></tr>
<tr><td>자 산 총 계</td><td></td><td>1000</td><td>900</td></tr>
<tr><td>자 본 총 계</td><td></td><td>400</td><td>350</td></tr>
</table>
</body></html>
"""
```

`test_extract_job_parses_statement_accounts` (이름은 기존 스타일에 맞춤):

- catalog에 `section_name="재무상태표"`, `viewer_url`이 mock에 걸리게
- `run_job` 후 `fact.accounts_status == "ok"`
- `total_asset` current `value == 1000`
- `fact.bs_entry_id`가 그 entry
- `fact.fs_parent_entry_id is None`

`test_extract_job_uses_parent_when_no_statement_leaves`:

- `(첨부)재무제표` 부모만, `주석` leaf만
- mock이 부모 URL에 `_FS_HTML + "주석 1. 자세한"` 반환
- `accounts_status == "ok"`, `fs_parent_entry_id` 설정, `total_asset` 존재

`test_reparse_refetches_when_accounts_status_is_not_found`:

- 기존 hours reparse 테스트와 같이 `accounts_status="not_found"`이면 다시 fetch

기존 커버만 있는 테스트: `accounts_status == "skipped"`.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py -q -k accounts`

Expected: FAIL (제표를 fetch하지 않음)

- [ ] **Step 3: 최소 연결**

1. `_LEAF_ROLES`에 `"bs_entry_id"`, `"is_entry_id"` 추가. `fs_parent_entry_id`는 넣지 않는다.
2. `_extract_document` 루프 뒤:

```python
if not leaves.bs_entry_id and not leaves.is_entry_id and leaves.fs_parent_entry_id:
    parent = by_id.get(leaves.fs_parent_entry_id)
    if parent and parent.viewer_url:
        # 기존과 같은 try/except SourceFetchError, blocked 처리
        html_by_role["fs_parent_entry_id"] = html
```

3. `_build_fact`:

```python
from app.extracting.accounts import cut_notes, extract_accounts

bs_html = html_by_role.get("bs_entry_id")
is_html = html_by_role.get("is_entry_id")
parent_html = html_by_role.get("fs_parent_entry_id")
if bs_html is None and is_html is None and parent_html:
    cut = cut_notes(parent_html)
    bs_html = is_html = cut
if bs_html is None and is_html is None:
    accounts, accounts_status = [], "skipped"
else:
    accounts, accounts_status = _safe_activity_parse(
        lambda html: extract_accounts(bs_html=bs_html, is_html=is_html),
        "",  # html 인자는 쓰지 않음 — _safe_activity_parse 시그니처가 html을 넘기면
        [],
        "제표계정",
    )
```

`_safe_activity_parse`가 `parser(html)`만 받으면 래퍼를 둔다:

```python
def _parse_accounts(_html: str) -> tuple[list[dict[str, object]], str]:
    return extract_accounts(bs_html=bs_html, is_html=is_html)

accounts, accounts_status = _safe_activity_parse(_parse_accounts, "unused", [], "제표계정")
```

또는 `_safe_activity_parse`를 건드리지 않고 try/except를 `_build_fact`에 직접 쓴다. **기존 `_safe_activity_parse`를 제표에도 재사용하는 쪽을 우선**하고, html 인자가 거슬리면 로컬 람다로 `extract_accounts`를 감싼다.

4. `AuditReportFact(...)`에 `bs_entry_id=leaves.bs_entry_id` 등, `accounts`, `accounts_status`.
5. `_NOT_FOUND_STATUSES`에 `"accounts_status"`.
6. `_failed_fact`는 새 컬럼 기본값(빈 리스트·None)이면 ORM default로 충분.

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py tests/test_extracting_accounts.py tests/test_extracting_selector.py -q`

Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/services/extraction_service.py packages/web-api/tests/test_extraction_service.py
git commit -m "feat: 추출 잡이 첨부 제표 계정을 저장한다"
```

---

### Task 6: 완전성·Public API·README

**Files:**
- Modify: `app/services/completeness_service.py` (`_FIELD_STATUS_ATTRS`)
- Modify: `tests/test_extract_admin_api.py` (fact fixture에 `accounts`/`accounts_status` 필요하면)
- Modify: `tests/test_facts_api.py`
- Modify: `packages/web-api/README.md` (Task 4에서 안 했으면 여기서)

**Interfaces:**
- Consumes: `accounts_status`
- Produces: `field_partial`이 `accounts_status != ok`를 포함. GET audit-facts JSON에 `accounts` 배열

- [ ] **Step 1: 실패하는 테스트**

`test_facts_api.py` `_fact`에 `accounts=[{"account": "total_asset", "period": "current", "value": 1, "status": "ok"}]`, `accounts_status="ok"`를 넣고 응답 `row["accounts_status"] == "ok"`를 단언.

완전성: 기존 field_partial 테스트가 hours만 보면, accounts_status가 None/skipped인 fixture는 이미 partial일 수 있다. **ok 행 fixture에 `accounts_status="ok"`를 넣어 회귀를 막는다.** `test_extract_admin_api.py`의 `_fact` 헬퍼를 같은 방식으로 보강한다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_facts_api.py tests/test_extract_admin_api.py -q`

Expected: FAIL 또는 fixture ValidationError

- [ ] **Step 3: `_FIELD_STATUS_ATTRS`에 `accounts_status` 추가.** README에 계정 8개·당기/전기·4/5/6칸 한 문단.

- [ ] **Step 4: 전체 테스트**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: 전부 PASS (기존 381+α)

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/services/completeness_service.py packages/web-api/tests packages/web-api/README.md
git commit -m "feat: 계정 상태를 완전성과 Public API에 넣는다"
```

---

## Self-review (스펙 대응)

| 스펙 | 태스크 |
|------|--------|
| E-4 8계정 × 당기/전기, value_won | 2–3 |
| 4·5·6칸, 공란≠0, `-`→0 | 2–3 |
| leaf 우선, 연결 섹션명, 부모+`주석 ` | 1, 5 |
| 자본변동표 제외, 부채및자본총계 ≠ equity | 2–3 |
| 같은 잡, v11, reparse, field_partial, Public | 4–6 |
| D-6/D-7·전 행 덤프 안 함 | 전역 제약 |

`extract_accounts` 시그니처는 Task 2에서 고정하고 5–6이 그대로 쓴다. 부모 fetch는 `_LEAF_ROLES`에 넣지 않아 BS/IS가 있을 때 부모를 치지 않는다.
