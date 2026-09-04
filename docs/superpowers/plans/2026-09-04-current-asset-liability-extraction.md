# 재무상태표 유동자산·유동부채 소계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 첨부 재무상태표에서 유동자산·유동부채 소계를 읽어 기존 `accounts` JSON에 `current_asset`·`current_liability`로 붙인다.

**Architecture:** `extract_accounts` 시그니처·selector·fetch는 그대로다. `_account_of`에 소계 두 키를 넣고, `_TOTAL_ACCOUNTS`로 합계 칸을 고르며, 계정 튜플 뒤에 두 키를 둔다. 추출기 버전만 `audit_opinion.v15`로 올린다.

**Tech Stack:** Python 3.11+, BeautifulSoup/lxml, pytest

**Spec:** `docs/superpowers/specs/2026-09-04-current-asset-liability-extraction-design.md`

## Global Constraints

- Python 3.11+, 모든 함수 타입 힌트
- 주석·Docstring·로그·예외·테스트 설명은 한국어
- extracting 순수 함수는 sync
- Black/Flake8, line length 100
- 테스트는 실제 DART를 호출하지 않음
- 작업 디렉터리 기본: `packages/web-api`
- 실행: `.\.venv\Scripts\python.exe -m pytest <path> -q`
- git 커밋은 **사용자가 요청한 경우에만**. 아래 Commit 스텝은 메시지 초안이다
- `extract_accounts` 시그니처·`cut_notes`·selector·fetch·제N기 기간 그룹·`_parse_amount` 변경 금지
- 새 잡·새 컬럼·유동비율 파생·비유동 소계·현금/당좌 합산으로 유동자산을 만들기 금지
- `period=unknown` 금지. D-6·D-7 금지
- 제외 키는 compact `비유동`·`기타`다. 글자 `비` 단독이 아니다

---

## File map

| 파일 | 역할 |
|------|------|
| `app/extracting/accounts.py` | 계정 튜플, `_account_of`, `_TOTAL_ACCOUNTS` |
| `app/extracting/constants.py` | `EXTRACTOR_VERSION = "audit_opinion.v15"` |
| `tests/test_extracting_accounts.py` | 5칸 소계·비유동·기타·SPC fixture |
| `tests/test_audit_report_fact_repository.py` | 버전 단언 v15 |
| `tests/test_extraction_service.py` | 버전 단언·시드 v15 |
| `packages/web-api/README.md` | v15, 계정 목록 10개 |

---

### Task 1: current_asset·current_liability 매핑

**Files:**
- Modify: `packages/web-api/app/extracting/accounts.py`
- Test: `packages/web-api/tests/test_extracting_accounts.py`

**Interfaces:**
- Consumes: 기존 `extract_accounts(*, bs_html: str | None, is_html: str | None) -> tuple[list[dict[str, object]], str]`, `_account_of`, `_TOTAL_ACCOUNTS`, `_pick_amount`
- Produces: 동일 시그니처. `account` 키 `"current_asset"` / `"current_liability"`. 계정 목록 순서: 기존 여덟 키 다음 두 키. 소계는 `_TOTAL_ACCOUNTS`라 내역·합계가 둘 다 차면 합계 칸

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_extracting_accounts.py`의 `_FIVE_COL_BS`에서 `자 산 총 계` 행 **다음**에 유동부채 소계 행을 넣는다.

```html
<tr><td>Ⅰ. 유동부채</td><td></td><td>12,345,678</td><td></td><td>11,111,111</td></tr>
```

같은 파일 하단에 fixture와 테스트를 추가한다.

```python
_NONCURRENT_ONLY_BS = """
<html><body>
<p>재무상태표</p>
<p>(단위: 원)</p>
<table>
<tr><td>과 목</td><td>당기</td><td>전기</td></tr>
<tr><td>비유동자산</td><td>800</td><td>700</td></tr>
<tr><td>자 산 총 계</td><td>1000</td><td>900</td></tr>
<tr><td>비유동부채</td><td>200</td><td>150</td></tr>
<tr><td>자 본 총 계</td><td>800</td><td>750</td></tr>
</table>
</body></html>
"""

_OTHER_CURRENT_ONLY_BS = """
<html><body>
<p>재무상태표</p>
<p>(단위: 원)</p>
<table>
<tr><td>과 목</td><td>당기</td><td>전기</td></tr>
<tr><td>기타유동자산</td><td>50</td><td>40</td></tr>
<tr><td>자 산 총 계</td><td>1000</td><td>900</td></tr>
<tr><td>기타유동부채</td><td>30</td><td>20</td></tr>
<tr><td>자 본 총 계</td><td>800</td><td>750</td></tr>
</table>
</body></html>
"""

_SPC_BS = """
<html><body>
<p>재무상태표</p>
<p>(단위: 원)</p>
<table>
<tr>
  <td>과 목</td><td>제 3(당) 기</td><td>제 3(당) 기</td>
  <td>제 2(전) 기</td><td>제 2(전) 기</td>
</tr>
<tr><td>Ⅰ. 유동자산</td><td></td><td>588,065,798</td><td></td><td>644,317,902</td></tr>
<tr><td>Ⅱ. 유동화자산(주석4)</td><td></td><td>30,000,000,000</td><td></td><td>29,700,000,000</td></tr>
<tr><td>자 산 총 계</td><td></td><td>30,588,065,798</td><td></td><td>30,344,317,902</td></tr>
<tr><td>Ⅱ. 유동화부채(주석2,5)</td><td></td><td>30,000,000,000</td><td></td><td>29,700,000,000</td></tr>
<tr><td>자 본 총 계</td><td></td><td>100</td><td></td><td>100</td></tr>
</table>
</body></html>
"""


def test_extract_accounts_current_totals_use_pair_not_blank() -> None:
    """5칸 유동자산·유동부채 소계는 합계 칸이고 내역 공란은 0이 아니다."""
    accounts, status = extract_accounts(bs_html=_FIVE_COL_BS, is_html=None)
    assert status == "ok"
    asset = _by_account_period(accounts, "current_asset", "current")
    assert asset["status"] == "ok"
    assert asset["value"] == 665809879
    assert asset["value_won"] == 665809879
    prior_asset = _by_account_period(accounts, "current_asset", "prior")
    assert prior_asset["value"] == 622084856
    liab = _by_account_period(accounts, "current_liability", "current")
    assert liab["status"] == "ok"
    assert liab["value"] == 12345678
    prior_liab = _by_account_period(accounts, "current_liability", "prior")
    assert prior_liab["value"] == 11111111
    assert not any(
        r["account"] == "current_asset" and r.get("value") == 0 for r in accounts
    )


def test_extract_accounts_noncurrent_is_not_current() -> None:
    """비유동자산·비유동부채는 유동 소계가 아니다."""
    accounts, status = extract_accounts(bs_html=_NONCURRENT_ONLY_BS, is_html=None)
    assert status == "ok"
    asset = _by_account_period(accounts, "current_asset", "current")
    assert asset["status"] == "not_found"
    assert asset["value"] is None
    liab = _by_account_period(accounts, "current_liability", "current")
    assert liab["status"] == "not_found"
    assert liab["value"] is None
    assert not any(
        r["account"] in {"current_asset", "current_liability"} and r.get("value")
        for r in accounts
    )


def test_extract_accounts_other_current_is_not_subtotal() -> None:
    """기타유동자산·기타유동부채는 소계가 아니다."""
    accounts, status = extract_accounts(bs_html=_OTHER_CURRENT_ONLY_BS, is_html=None)
    assert status == "ok"
    asset = _by_account_period(accounts, "current_asset", "current")
    assert asset["status"] == "not_found"
    liab = _by_account_period(accounts, "current_liability", "current")
    assert liab["status"] == "not_found"
    assert not any(
        r["account"] in {"current_asset", "current_liability"}
        and "기타" in (r["account_raw"] or "")
        for r in accounts
    )


def test_extract_accounts_securitized_liability_is_not_current() -> None:
    """유동화자산은 유동자산이 아니고, 유동화부채만 있으면 유동부채는 not_found다."""
    accounts, status = extract_accounts(bs_html=_SPC_BS, is_html=None)
    assert status == "ok"
    asset = _by_account_period(accounts, "current_asset", "current")
    assert asset["status"] == "ok"
    assert asset["value"] == 588065798
    assert "유동화" not in (asset["account_raw"] or "")
    liab = _by_account_period(accounts, "current_liability", "current")
    assert liab["status"] == "not_found"
    assert liab["value"] is None
    assert not any(
        r["account"] == "current_liability" and r.get("value") == 30000000000
        for r in accounts
    )
```

기존 `test_extract_accounts_five_col_uses_pair_not_blank`는 그대로 둔다 (자산총계 단언).

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py::test_extract_accounts_current_totals_use_pair_not_blank tests/test_extracting_accounts.py::test_extract_accounts_noncurrent_is_not_current tests/test_extracting_accounts.py::test_extract_accounts_other_current_is_not_subtotal tests/test_extracting_accounts.py::test_extract_accounts_securitized_liability_is_not_current -q`

Expected: FAIL (`current_asset` 키가 없어 `StopIteration`, 또는 목록에만 넣고 매핑이 없어 `not_found`)

- [ ] **Step 3: 최소 구현**

`accounts.py`의 계정 튜플을 뒤에 두 키만 늘리고, `_finalize_records`가 그 튜플을 쓰게 한다. 이름은 `_EIGHT_ACCOUNTS`를 `_ACCOUNTS`로 바꿔 세 곳(정의, `extract_accounts` docstring, `_finalize_records`)을 맞춘다.

```python
_ACCOUNTS: tuple[str, ...] = (
    "total_asset",
    "total_equity",
    "net_income",
    "inventory",
    "receivable",
    "long_term_receivable",
    "contract_asset",
    "unbilled",
    "current_asset",
    "current_liability",
)

_TOTAL_ACCOUNTS = frozenset(
    {
        "total_asset",
        "total_equity",
        "net_income",
        "current_asset",
        "current_liability",
    }
)
```

`extract_accounts` docstring: `여덟 계정×기간` → `계정×기간`.
`_finalize_records` docstring: `여덟 계정×기간` → `계정×기간`. `for account in _ACCOUNTS:`.

`_account_of`에서 자본총계 분기 **다음**, `당기순` **앞**에 둔다.

```python
    if "자본총계" in token:
        if "부채와자본총계" in token or "부채및자본총계" in token:
            return None
        return "total_equity"
    if "유동자산" in token and "비유동" not in token and "기타" not in token:
        return "current_asset"
    if "유동부채" in token and "비유동" not in token and "기타" not in token:
        return "current_liability"
    if "당기순" in token and not any(ex in token for ex in _NET_INCOME_EXCLUDES):
        return "net_income"
```

`cut_notes`·`_pick_amount`·기간 헤더·selector는 수정하지 않는다. `_pick_amount`는 `account in _TOTAL_ACCOUNTS`이면 합계 칸을 쓰므로 두 키만 넣으면 5칸 내역 공란이 0이 되지 않는다.

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py -q`

Expected: PASS (기존 + 신규 4)

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/accounts.py packages/web-api/tests/test_extracting_accounts.py
git commit -m "feat: 재무상태표 유동자산·유동부채 소계를 accounts에 넣는다"
```

---

### Task 2: extractor v15

**Files:**
- Modify: `packages/web-api/app/extracting/constants.py`
- Modify: `packages/web-api/tests/test_audit_report_fact_repository.py`
- Modify: `packages/web-api/tests/test_extraction_service.py`
- Modify: `packages/web-api/README.md`

**Interfaces:**
- Consumes: Task 1 파서 (변경 없음)
- Produces: `EXTRACTOR_VERSION == "audit_opinion.v15"`

- [ ] **Step 1: 실패하는 테스트 수정**

`test_audit_report_fact_repository.py`의 `assert EXTRACTOR_VERSION == "audit_opinion.v14"` → `"audit_opinion.v15"`.

`test_extraction_service.py`의 리터럴 `"audit_opinion.v14"` 다섯 곳(단언 두 곳·시드 세 곳)을 `"audit_opinion.v15"`로 바꾼다.
`extractor_version="audit_opinion.v2"` refetch fixture는 그대로 둔다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_audit_report_fact_repository.py::test_extractor_version_constant -q`

Expected: FAIL (`v14` != `v15`)

- [ ] **Step 3: 상수·README**

```python
EXTRACTOR_VERSION = "audit_opinion.v15"
```

`packages/web-api/README.md`:

- Extracting 줄과 추출기 버전 문장의 `audit_opinion.v14` → `audit_opinion.v15`
- 계정 문단을 아래처럼 고친다.

```text
첨부 제표에서는 E-4 연구 계정 8개(자산총계·자본총계·당기순손익·재고·매출채권·장기매출채권·계약자산·미청구공사)와
유동자산·유동부채 소계의 당기·전기 금액을 읽으며, `제N기` 비교열 헤더는 큰 기수를 당기·작은 기수를 전기로 해석합니다.
`당기순손실` 과목은 칸 괄호가 없어도 음수로 읽습니다.
`비유동`·`기타` 과목과 `유동화부채`는 유동 소계로 쓰지 않습니다.
```

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py tests/test_audit_report_fact_repository.py tests/test_extraction_service.py tests/test_facts_api.py -q`

Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/constants.py packages/web-api/tests/test_audit_report_fact_repository.py packages/web-api/tests/test_extraction_service.py packages/web-api/README.md
git commit -m "feat: 계정 추출기를 audit_opinion.v15로 올린다"
```

---

## Self-review (스펙 대응)

| 스펙 | 태스크 |
|------|--------|
| `current_asset` / `current_liability`, E-4 뒤 | 1 (`_ACCOUNTS`) |
| `비유동`·`기타` 제외, `비` 단독 아님 | 1 (비유동·기타 fixture) |
| `유동화자산`/`유동화부채` 미매칭, SPC `current_liability=not_found` | 1 (`_SPC_BS`) |
| `_TOTAL_ACCOUNTS`, 5칸 내역 공란 ≠ 0 | 1 (5칸 fixture) |
| 행 없으면 `not_found` | 1 (비유동·기타·SPC 부채) |
| 시그니처·selector·`cut_notes` 불변 | 전역 제약 |
| v15, README 10계정 | 2 |
| 유동비율·비유동 소계·합산 추정 없음 | 전역 제약 |
