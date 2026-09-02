# 제표 비교열 `제N기` 기간 매핑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `당기`/`전기` 글자가 없는 제표 헤더(`제49기 기말` 등)에서 당기·전기 금액을 읽고, `당기순이익` 행을 헤더로 오인해 `ok`+빈 금액을 내지 않게 한다.

**Architecture:** `extract_accounts` 시그니처는 그대로다. `_period_groups`가 기존 `_col_role` 그룹이 비면 `제(\d+)기` 기수(큰 쪽 당기) → 실패 시 왼쪽 당기·오른쪽 전기로 채운다. 과목/`당기순` 칸은 기간 열이 아니다. 추출기 버전만 `audit_opinion.v12`로 올린다.

**Tech Stack:** Python 3.11+, BeautifulSoup/lxml, pytest

**Spec:** `docs/superpowers/specs/2026-09-03-fs-comparative-period-headers-design.md`

## Global Constraints

- Python 3.11+, 모든 함수 타입 힌트
- 주석·Docstring·로그·예외·테스트 설명은 한국어
- extracting 순수 함수는 sync
- Black/Flake8, line length 100
- 테스트는 실제 DART를 호출하지 않음
- 작업 디렉터리 기본: `packages/web-api`
- 실행: `.\.venv\Scripts\python.exe -m pytest <path> -q`
- git 커밋은 **사용자가 요청한 경우에만**. 아래 Commit 스텝은 메시지 초안이다
- `extract_accounts` 시그니처·여덟 계정·내역/합계·`cut_notes`·selector·fetch 변경 금지
- `period=unknown` 금지. Viewer `_parse_table`·`FindTargetTable`·`len % 2` 금지
- D-6·D-7, 본표 전 행 덤프, 달력 연도 해석, 3기를 각각 period로 저장 금지

---

## File map

| 파일 | 역할 |
|------|------|
| `app/extracting/accounts.py` | `_col_role` 제외 칸, `_period_groups` 2단계, `_is_header_row` |
| `app/extracting/constants.py` | `EXTRACTOR_VERSION = "audit_opinion.v12"` |
| `tests/test_extracting_accounts.py` | 제N기·가짜 헤더·왼쪽/오른쪽 fixture |
| `tests/test_audit_report_fact_repository.py` | 버전 단언 v12 |
| `tests/test_extraction_service.py` | 버전 단언 v12 |
| `packages/web-api/README.md` | v12 |

기존 `_UNREADABLE_BS`(과목\|비고A\|비고B)는 스펙 4번에 따라 **왼쪽=당기·오른쪽=전기로 읽힌다.**
`test_extract_accounts_unreadable_table_is_not_found`는 과목-only+`당기순이익` fixture로 바꾼다.

---

### Task 1: 제N기·가짜 헤더 기간 그룹

**Files:**
- Modify: `packages/web-api/app/extracting/accounts.py`
- Test: `packages/web-api/tests/test_extracting_accounts.py`

**Interfaces:**
- Consumes: 기존 `extract_accounts(*, bs_html: str | None, is_html: str | None) -> tuple[list[dict[str, object]], str]`, `_PeriodGroup`, `compact`, `expand_table_matrix`
- Produces: 동일 시그니처. `_period_groups(header: list[str]) -> tuple[list[_PeriodGroup], list[int]]`가 스펙 1~4 순서를 따른다. `_GI_RE = re.compile(r"제(\d+)기")` (compact 문자열에 적용)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_extracting_accounts.py`에 fixture와 테스트를 추가하고, 기존 unreadable 테스트를 교체한다.

```python
_JEN_GI_BS = """
<html><body>
<p>재무상태표</p>
<p>(단위: 원)</p>
<table>
<tr><td>과 목</td><td>주석</td><td>제49기 기말</td><td>제48기 기말</td></tr>
<tr><td>자 산 총 계</td><td></td><td>1,179,628,362,898</td><td>1,084,097,944,847</td></tr>
<tr><td>자 본 총 계</td><td></td><td>910,667,791,486</td><td>854,085,976,617</td></tr>
</table>
<p>연결포괄손익계산서</p>
<table>
<tr><td>과 목</td><td>주석</td><td>제49기</td><td>제48기</td></tr>
<tr><td>당기순이익</td><td></td><td>166,912,885,242</td><td>170,246,170,594</td></tr>
<tr><td>당기총포괄이익</td><td></td><td>1</td><td>2</td></tr>
</table>
</body></html>
"""

_SAME_GI = """
<html><body>
<p>재무상태표</p>
<table>
<tr><td>과 목</td><td>제49기</td><td>제49기</td></tr>
<tr><td>자 산 총 계</td><td>1000</td><td>900</td></tr>
</table>
</body></html>
"""

_NO_GI_TWO_AMOUNTS = """
<html><body>
<p>재무상태표</p>
<table>
<tr><td>과 목</td><td>비고A</td><td>비고B</td></tr>
<tr><td>자 산 총 계</td><td>100</td><td>200</td></tr>
</table>
</body></html>
"""

_FAKE_NI_HEADER = """
<html><body>
<p>재무상태표</p>
<table>
<tr><td>과 목</td></tr>
<tr><td>당기순이익</td></tr>
<tr><td>자 산 총 계</td></tr>
</table>
</body></html>
"""


def test_extract_accounts_jen_gi_larger_is_current() -> None:
    """제N기 기수가 있으면 큰 기가 당기이고 당기순 행은 헤더가 아니다."""
    accounts, status = extract_accounts(bs_html=_JEN_GI_BS, is_html=_JEN_GI_BS)
    assert status == "ok"
    total = _by_account_period(accounts, "total_asset", "current")
    assert total["value"] == 1179628362898
    assert "49" in compact(total["period_raw"])
    prior = _by_account_period(accounts, "total_asset", "prior")
    assert prior["value"] == 1084097944847
    ni = _by_account_period(accounts, "net_income", "current")
    assert ni["value"] == 166912885242
    assert not any(
        r["account"] == "net_income" and r["value"] == 1 for r in accounts
    )


def test_extract_accounts_same_gi_falls_back_left_right() -> None:
    """기수가 같으면 왼쪽이 당기다."""
    accounts, status = extract_accounts(bs_html=_SAME_GI, is_html=None)
    assert status == "ok"
    assert _by_account_period(accounts, "total_asset", "current")["value"] == 1000
    assert _by_account_period(accounts, "total_asset", "prior")["value"] == 900


def test_extract_accounts_no_gi_two_amount_cols_left_is_current() -> None:
    """제N기 없이 금액 열 두 개면 왼쪽이 당기다."""
    accounts, status = extract_accounts(bs_html=_NO_GI_TWO_AMOUNTS, is_html=None)
    assert status == "ok"
    assert _by_account_period(accounts, "total_asset", "current")["value"] == 100
    assert _by_account_period(accounts, "total_asset", "prior")["value"] == 200


def test_extract_accounts_danggisun_row_is_not_period_header() -> None:
    """과목만 있는 표의 당기순이익 행으로 ok를 내면 안 된다."""
    accounts, status = extract_accounts(bs_html=_FAKE_NI_HEADER, is_html=None)
    assert status == "not_found"
    assert accounts == []
```

`from app.extracting.text import compact`를 테스트 파일에 추가한다 (`period_raw` 단언용).

기존 `test_extract_accounts_unreadable_table_is_not_found`와 `_UNREADABLE_BS`는 **삭제**하고, 위 `test_extract_accounts_no_gi_two_amount_cols_left_is_current`가 그 표 모양을 대신한다.

기존 `test_extract_accounts_five_col_uses_pair_not_blank`는 그대로 둔다 (기수 분기 미사용).

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py::test_extract_accounts_jen_gi_larger_is_current tests/test_extracting_accounts.py::test_extract_accounts_danggisun_row_is_not_period_header -q`

Expected: FAIL (제49기 열을 기간으로 안 읽거나, 당기순 행 때문에 ok)

- [ ] **Step 3: 최소 구현**

`accounts.py`의 `_is_header_row`, `_col_role`, `_period_groups`를 스펙 순서에 맞게 바꾼다. 요지:

```python
_GI_RE = re.compile(r"제(\d+)기")


def _is_excluded_period_cell(token: str) -> bool:
    """과목·당기순 칸은 기간 열로 보지 않는다."""
    return "과목" in token or "당기순" in token


def _is_header_row(row: list[str]) -> bool:
    tokens = [compact(cell) for cell in row]
    if any("과목" in token for token in tokens):
        return True
    for token in tokens:
        if _is_excluded_period_cell(token):
            continue
        if "당기" in token or "(당)기" in token:
            return True
        if "전기" in token or "(전)기" in token:
            return True
        if "제" in token and "기" in token:
            return True
    return False


def _col_role(header_text: str) -> str | None:
    token = compact(header_text)
    if "주석" in token or "주기" in token:
        return "note"
    if _is_excluded_period_cell(token):
        return None
    if "당기" in token or "(당)기" in token:
        return "current"
    if "전기" in token or "(전)기" in token:
        return "prior"
    return None


def _groups_from_roles(
    header: list[str], roles: list[str | None]
) -> list[_PeriodGroup]:
    groups: list[_PeriodGroup] = []
    index = 0
    while index < len(roles):
        role = roles[index]
        if role not in ("current", "prior"):
            index += 1
            continue
        end = index
        while end < len(roles) and roles[end] == role:
            end += 1
        cols = list(range(index, end))
        period_raw = header[index]
        if len(cols) == 1:
            groups.append(_PeriodGroup(role, period_raw, cols[0], None))
        else:
            groups.append(_PeriodGroup(role, period_raw, cols[0], cols[1]))
        index = end
    return groups


def _period_groups(header: list[str]) -> tuple[list[_PeriodGroup], list[int]]:
    roles = [_col_role(cell) for cell in header]
    groups = _groups_from_roles(header, roles)
    if not groups:
        roles = _roles_from_gi_or_position(header, roles)
        groups = _groups_from_roles(header, roles)
    label_cols = [i for i, role in enumerate(roles) if role is None]
    return groups, label_cols


def _roles_from_gi_or_position(
    header: list[str], base_roles: list[str | None]
) -> list[str | None]:
    """당기/전기 그룹이 없을 때 기수 또는 왼쪽·오른쪽으로 채운다."""
    roles = list(base_roles)
    gi_cols: list[tuple[int, int]] = []
    for index, cell in enumerate(header):
        if roles[index] == "note":
            continue
        token = compact(cell)
        if _is_excluded_period_cell(token):
            continue
        match = _GI_RE.search(token)
        if match:
            gi_cols.append((index, int(match.group(1))))
    numbers = {n for _i, n in gi_cols}
    if len(gi_cols) == 1:
        roles[gi_cols[0][0]] = "current"
        return roles
    if len(gi_cols) >= 2 and len(numbers) >= 2:
        lo, hi = min(numbers), max(numbers)
        for index, number in gi_cols:
            if number == hi:
                roles[index] = "current"
            elif number == lo:
                roles[index] = "prior"
        return roles
    amount_cols = [
        i
        for i, role in enumerate(roles)
        if role != "note" and not _is_excluded_period_cell(compact(header[i]))
    ]
    if not amount_cols:
        return roles
    roles[amount_cols[0]] = "current"
    if len(amount_cols) >= 2:
        roles[amount_cols[1]] = "prior"
    return roles
```

`_extract_from_table`의 “그룹이 있는 헤더만 채택” 루프는 그대로 둔다. 가짜 `당기순` 행은 `_is_header_row`에서 걸러지거나, 헤더라도 그룹이 비면 skip된다.

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py -q`

Expected: PASS (기존 5·4·6칸 + 신규)

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/accounts.py packages/web-api/tests/test_extracting_accounts.py
git commit -m "feat: 제N기 비교열을 당기·전기로 읽는다"
```

---

### Task 2: extractor v12

**Files:**
- Modify: `packages/web-api/app/extracting/constants.py`
- Modify: `packages/web-api/tests/test_audit_report_fact_repository.py`
- Modify: `packages/web-api/tests/test_extraction_service.py`
- Modify: `packages/web-api/README.md`

**Interfaces:**
- Consumes: Task 1 파서 (변경 없음)
- Produces: `EXTRACTOR_VERSION == "audit_opinion.v12"`

- [ ] **Step 1: 실패하는 테스트 수정**

`test_audit_report_fact_repository.py`의 `assert EXTRACTOR_VERSION == "audit_opinion.v11"` → `"audit_opinion.v12"`.

`test_extraction_service.py`의 `assert fact.extractor_version == "audit_opinion.v11"` 두 곳과
시드 `extractor_version="audit_opinion.v11"` 두 곳(hours/accounts reparse, 현재 버전과 같아야 함)을 `v12`로 바꾼다.
`extractor_version="audit_opinion.v2"` refetch fixture는 그대로 둔다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_audit_report_fact_repository.py::test_extractor_version_constant -q`

Expected: FAIL (`v11` != `v12`)

- [ ] **Step 3: 상수·README**

```python
EXTRACTOR_VERSION = "audit_opinion.v12"
```

README의 `audit_opinion.v11` 두 곳을 `v12`로 바꾸고, 제N기 비교열을 당기·전기로 읽는다는 한 줄을 계정 문단에 추가한다.

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py tests/test_audit_report_fact_repository.py tests/test_extraction_service.py tests/test_facts_api.py -q`

Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/constants.py packages/web-api/tests packages/web-api/README.md
git commit -m "feat: 계정 추출기를 audit_opinion.v12로 올린다"
```

---

## Self-review (스펙 대응)

| 스펙 | 태스크 |
|------|--------|
| 당기/전기 우선, 제N기 큰 기=당기 | 1 |
| 기수 실패·제N기 없음 → 왼쪽/오른쪽 | 1 (`_SAME_GI`, `_NO_GI_TWO_AMOUNTS`) |
| 당기순 가짜 헤더 → not_found | 1 (`_FAKE_NI_HEADER`) |
| 5칸 제 3(당) 기 회귀 | 1 (기존 five-col 테스트) |
| v12 | 2 |
| 시그니처·selector·fetch 불변 | 전역 제약 |
