# 당기순이익·순손실 금액 부호 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `당기순이익(손실)`은 칸마다 `()`만 음수로 두고, `당기순손실` 행은 괄호가 없어도 `net_income` `value`를 음수로 저장한다.

**Architecture:** `_parse_amount`는 그대로다. `net_income`을 고른 뒤 compact 라벨에 `순이익`이 없고 `순손실`이 있으면 `value = -abs(value)`하고 `value_won`을 다시 곱한다. 추출기 버전만 `audit_opinion.v13`으로 올린다.

**Tech Stack:** Python 3.11+, BeautifulSoup/lxml, pytest

**Spec:** `docs/superpowers/specs/2026-09-03-net-income-sign-design.md`

## Global Constraints

- Python 3.11+, 모든 함수 타입 힌트
- 주석·Docstring·로그·예외·테스트 설명은 한국어
- extracting 순수 함수는 sync
- Black/Flake8, line length 100
- 테스트는 실제 DART를 호출하지 않음
- 작업 디렉터리 기본: `packages/web-api`
- 실행: `.\.venv\Scripts\python.exe -m pytest <path> -q`
- git 커밋은 **사용자가 요청한 경우에만**. 아래 Commit 스텝은 메시지 초안이다
- `extract_accounts` 시그니처·여덟 계정·내역/합계·`cut_notes`·selector·fetch·제N기 기간 그룹 변경 금지
- `_parse_amount`의 `()`/`△`/선행 `-` 로직을 바꾸지 않음
- 이익잉여금/결손금 계정 추가 금지. 비교 두 열 부호를 서로 맞추지 않음
- `period=unknown` 금지. D-6·D-7 금지

---

## File map

| 파일 | 역할 |
|------|------|
| `app/extracting/accounts.py` | `_is_net_loss_label`, `net_income` `-abs` |
| `app/extracting/constants.py` | `EXTRACTOR_VERSION = "audit_opinion.v13"` |
| `tests/test_extracting_accounts.py` | 이익(손실) 혼합·순손실 fixture |
| `tests/test_audit_report_fact_repository.py` | 버전 단언 v13 |
| `tests/test_extraction_service.py` | 버전 단언·시드 v13 |
| `packages/web-api/README.md` | v13, 순손실 부호 한 줄 |

---

### Task 1: net_income 순손실 부호

**Files:**
- Modify: `packages/web-api/app/extracting/accounts.py`
- Test: `packages/web-api/tests/test_extracting_accounts.py`

**Interfaces:**
- Consumes: 기존 `extract_accounts(*, bs_html: str | None, is_html: str | None) -> tuple[list[dict[str, object]], str]`, `_pick_amount`, `_parse_amount`, `_account_of`
- Produces: 동일 시그니처. `_is_net_loss_label(token: str) -> bool`. `net_income`이고 순손실 라벨이면 저장 `value`가 `-abs(parsed)`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_extracting_accounts.py`에 fixture와 테스트를 추가한다.

```python
_NI_PROFIT_LOSS_MIXED = """
<html><body>
<p>포괄손익계산서</p>
<p>(단위: 원)</p>
<table>
<tr><td>과 목</td><td>당기</td><td>전기</td></tr>
<tr><td>당기순이익(손실)</td><td>1,000</td><td>(500)</td></tr>
<tr><td>당기총포괄이익</td><td>9</td><td>8</td></tr>
</table>
</body></html>
"""

_NI_LOSS_LABEL = """
<html><body>
<p>손익계산서</p>
<p>(단위: 원)</p>
<table>
<tr><td>과 목</td><td>당기</td><td>전기</td></tr>
<tr><td>당기순손실</td><td>1,000</td><td>(200)</td></tr>
</table>
</body></html>
"""


def test_extract_accounts_net_income_paren_loss_is_per_cell() -> None:
    """당기순이익(손실)은 칸마다 괄호만 음수이고 총포괄은 당기순이 아니다."""
    accounts, status = extract_accounts(bs_html=None, is_html=_NI_PROFIT_LOSS_MIXED)
    assert status == "ok"
    assert _by_account_period(accounts, "net_income", "current")["value"] == 1000
    assert _by_account_period(accounts, "net_income", "prior")["value"] == -500
    assert not any(
        r["account"] == "net_income" and r["value"] == 9 for r in accounts
    )


def test_extract_accounts_net_loss_label_is_always_negative() -> None:
    """당기순손실은 괄호 없는 칸도 음수이고, 이미 괄호인 칸은 한 번만 음수다."""
    accounts, status = extract_accounts(bs_html=None, is_html=_NI_LOSS_LABEL)
    assert status == "ok"
    assert _by_account_period(accounts, "net_income", "current")["value"] == -1000
    assert _by_account_period(accounts, "net_income", "prior")["value"] == -200
```

기존 `당기순이익` 양수 테스트(제N기·6칸)는 그대로 둔다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py::test_extract_accounts_net_income_paren_loss_is_per_cell tests/test_extracting_accounts.py::test_extract_accounts_net_loss_label_is_always_negative -q`

Expected: FAIL (`당기순손실` 당기가 `1000`이거나, 전기 괄호 처리만 되고 라벨 `-abs`가 없음)

- [ ] **Step 3: 최소 구현**

`accounts.py`에 헬퍼를 두고, `_extract_from_table`에서 `net_income` 저장 직전에 적용한다.

```python
def _is_net_loss_label(token: str) -> bool:
    """순이익이 없는 순손실 과목인지 본다."""
    return "순손실" in token and "순이익" not in token
```

`_extract_from_table`의 `raw, value = parsed` 직후:

```python
            raw, value = parsed
            if account == "net_income" and _is_net_loss_label(label_compact):
                value = -abs(value)
            value_won = value * unit_scale if unit_scale is not None else None
```

`_parse_amount`는 수정하지 않는다. `label_compact`는 이미 `_row_label`에서 compact다.

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py -q`

Expected: PASS (기존 + 신규 2)

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/accounts.py packages/web-api/tests/test_extracting_accounts.py
git commit -m "feat: 당기순손실 행의 net_income을 음수로 저장한다"
```

---

### Task 2: extractor v13

**Files:**
- Modify: `packages/web-api/app/extracting/constants.py`
- Modify: `packages/web-api/tests/test_audit_report_fact_repository.py`
- Modify: `packages/web-api/tests/test_extraction_service.py`
- Modify: `packages/web-api/README.md`

**Interfaces:**
- Consumes: Task 1 파서 (변경 없음)
- Produces: `EXTRACTOR_VERSION == "audit_opinion.v13"`

- [ ] **Step 1: 실패하는 테스트 수정**

`test_audit_report_fact_repository.py`의 `assert EXTRACTOR_VERSION == "audit_opinion.v12"` → `"audit_opinion.v13"`.

`test_extraction_service.py`의 `assert fact.extractor_version == "audit_opinion.v12"` 두 곳과
시드 `extractor_version="audit_opinion.v12"` 두 곳(hours/accounts reparse, 현재 버전과 같아야 함)을 `v13`으로 바꾼다.
`extractor_version="audit_opinion.v2"` refetch fixture는 그대로 둔다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_audit_report_fact_repository.py::test_extractor_version_constant -q`

Expected: FAIL (`v12` != `v13`)

- [ ] **Step 3: 상수·README**

```python
EXTRACTOR_VERSION = "audit_opinion.v13"
```

README의 `audit_opinion.v12`를 `v13`으로 바꾸고, 계정 문단에 `당기순손실` 과목은 칸 괄호가 없어도 음수로 읽는다는 한 줄을 넣는다.

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py tests/test_audit_report_fact_repository.py tests/test_extraction_service.py tests/test_facts_api.py -q`

Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/constants.py packages/web-api/tests packages/web-api/README.md
git commit -m "feat: 계정 추출기를 audit_opinion.v13로 올린다"
```

---

## Self-review (스펙 대응)

| 스펙 | 태스크 |
|------|--------|
| 칸마다 독립, 이익(손실) 괄호만 음수 | 1 (`_NI_PROFIT_LOSS_MIXED`) |
| 순손실 `-abs`, 이중 부호 없음 | 1 (`_NI_LOSS_LABEL`) |
| `_parse_amount` 불변 | 1 |
| v13 | 2 |
| 시그니처·selector·이익잉여금 미추가 | 전역 제약 |
