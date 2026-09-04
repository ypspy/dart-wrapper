# 부채총계·계속기업·연결 종속기업 수 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 감사 추출 잡이 같은 `audit_report_facts` 행에 부채총계, 당기 계속기업 MU, 연결 종속기업 수를 붙인다.

**Architecture:** 부채총계는 `extract_accounts`에 계정 키만 더한다. 계속기업은 이미 가져온 의견서 HTML을 `extract_going_concern`이 compact로 읽는다(`classify_opinion` 창은 그대로). 종속기업은 연결만 주석 HTML(없으면 제표 부모의 `주석 ` 이후)을 세고, 실패 시에만 같은 접수 A001 계열회사 표를 본다. `extractor_version`은 `audit_opinion.v16`이다.

**Tech Stack:** Python 3.11+, BeautifulSoup/lxml, pytest, SQLAlchemy, Pydantic v2, FastAPI

**Spec:** `docs/superpowers/specs/2026-09-04-liability-gc-subsidiary-extraction-design.md`

## Global Constraints

- Python 3.11+, 모든 함수 타입 힌트
- 주석·Docstring·로그·예외·테스트 설명은 한국어
- extracting 순수 함수는 sync
- Black/Flake8, line length 100
- 테스트는 실제 DART를 호출하지 않음
- 한공회 doc 원문을 저장하지 않음. compact 한글 fixture만
- 작업 디렉터리 기본: `packages/web-api`
- 실행: `.\.venv\Scripts\python.exe -m pytest <path> -q`
- git 커밋은 **사용자가 요청한 경우에만**. 아래 Commit 스텝은 메시지 초안이다
- 새 잡·새 `extractor_id`·새 테이블·HTML 저장 금지
- `classify_opinion` 키워드·창 자르기 변경 금지
- `extract_accounts` 시그니처·`cut_notes` 구분자 `주석 ` 변경 금지
- D-7·상장 배지·업종·FSS·KIS·원표 JSON 덤프·관계/공동 포함 세기·청산=GC1 금지
- `period=unknown` 금지. 별도 문서 종속 카운트를 `0`으로 채우지 않음

---

## File map

| 파일 | 역할 |
|------|------|
| `app/extracting/accounts.py` | `total_liability` 키·`_TOTAL_ACCOUNTS` |
| `app/extracting/going_concern.py` | `extract_going_concern` (신규) |
| `app/extracting/subsidiaries.py` | `extract_subsidiaries`·`notes_tail` (신규) |
| `app/extracting/selector.py` | `notes_entry_id`, `a001_affiliate_entry_id` |
| `app/extracting/constants.py` | `audit_opinion.v16` |
| `app/models/audit_report_fact.py` | GC·종속 컬럼 |
| `app/db/session.py` | `ensure_schema` 패치 |
| `app/services/extraction_service.py` | fetch·파서 연결·reparse |
| `app/services/completeness_service.py` | `field_partial` (`not_applicable` 제외) |
| `app/schemas/facts.py` | Public 응답 필드 |
| `packages/web-api/README.md` | v16·세 필드 |
| `tests/test_extracting_accounts.py` | 부채총계 |
| `tests/test_extracting_going_concern.py` | GC fixture |
| `tests/test_extracting_subsidiaries.py` | 주석·A001 세기 |
| `tests/test_extracting_selector.py` | 주석·계열회사 leaf |
| `tests/test_extraction_service.py` | 잡 연결 |
| `tests/test_extract_admin_api.py` | field_partial |
| `tests/test_audit_report_fact_repository.py` | 컬럼·버전 |
| `tests/test_ensure_schema.py` | 패치 |

---

### Task 1: `total_liability` 매핑

**Files:**
- Modify: `packages/web-api/app/extracting/accounts.py`
- Test: `packages/web-api/tests/test_extracting_accounts.py`

**Interfaces:**
- Consumes: `extract_accounts(*, bs_html: str | None, is_html: str | None) -> tuple[list[dict[str, object]], str]`, `_account_of`, `_TOTAL_ACCOUNTS`
- Produces: 동일 시그니처. `account` 키 `"total_liability"`. `_ACCOUNTS`에서 `current_liability` **앞**. `_TOTAL_ACCOUNTS`에 포함

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_extracting_accounts.py`의 `_FIVE_COL_BS`에서 `Ⅰ. 유동부채` 행 **다음**에 부채총계 행을 넣는다.

```html
<tr><td>부 채 총 계</td><td></td><td>20,000,000</td><td></td><td>19,000,000</td></tr>
```

같은 파일에 테스트를 추가한다.

```python
def test_total_liability_five_col_uses_total_cell() -> None:
    """부채총계는 합계 칸이고, 부채와자본총계·유동부채와 키가 갈린다."""
    rows, status = extract_accounts(bs_html=_FIVE_COL_BS, is_html=None)
    assert status == "ok"
    current = _by_account_period(rows, "total_liability", "current")
    assert current["status"] == "ok"
    assert current["value"] == 20000000
    prior = _by_account_period(rows, "total_liability", "prior")
    assert prior["value"] == 19000000
    assert _by_account_period(rows, "current_liability", "current")["value"] == 12345678


def test_liability_and_equity_total_is_not_total_liability() -> None:
    """부채와자본총계만 있는 표는 total_liability가 not_found다."""
    html = """
    <html><body>
    <p>재무상태표</p>
    <table>
    <tr><td>과 목</td><td>당기</td><td>전기</td></tr>
    <tr><td>자 산 총 계</td><td>100</td><td>90</td></tr>
    <tr><td>부채와자본총계</td><td>100</td><td>90</td></tr>
    </table>
    </body></html>
    """
    rows, status = extract_accounts(bs_html=html, is_html=None)
    assert status == "ok"
    item = _by_account_period(rows, "total_liability", "current")
    assert item["status"] == "not_found"
    assert item["value"] is None
```

기존 `_by_account_period`는 없으면 KeyError가 난다. `not_found` 원소가 반드시 배열에 있도록 `_ACCOUNTS`에 키를 넣은 뒤에만 두 번째 테스트가 통과한다. 키가 없으면 Step 2에서 Import/KeyError 또는 원소 없음으로 실패한다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py::test_total_liability_five_col_uses_total_cell tests/test_extracting_accounts.py::test_liability_and_equity_total_is_not_total_liability -q`

Expected: FAIL (`total_liability` 원소 없음 또는 value 불일치)

- [ ] **Step 3: 최소 구현**

`accounts.py`의 `_ACCOUNTS`에서 `current_liability` **앞**에 `"total_liability"`를 넣는다.

`_TOTAL_ACCOUNTS`에 `"total_liability"`를 넣는다.

`_account_of`에서 자본총계 분기 **다음**, 유동자산 분기 **앞**:

```python
    if "부채총계" in token:
        if "부채와자본총계" in token or "부채및자본총계" in token:
            return None
        return "total_liability"
```

`부채와자본총계`는 `부채총계` 부분문자열이라 **반드시** 가드한다. `유동부채`는 `부채총계`가 아니므로 기존 분기를 탄다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/extracting/accounts.py packages/web-api/tests/test_extracting_accounts.py
git commit -m "feat: 재무상태표 부채총계를 accounts에 붙인다"
```

---

### Task 2: 계속기업 파서

**Files:**
- Create: `packages/web-api/app/extracting/going_concern.py`
- Test: `packages/web-api/tests/test_extracting_going_concern.py`

**Interfaces:**
- Consumes: `app.extracting.text.compact`, BeautifulSoup `get_text`
- Produces:

```python
@dataclass(frozen=True)
class GoingConcernResult:
    going_concern: int | None
    status: str
    raw: str | None
    source: str | None

def extract_going_concern(opinion_html: str | None) -> GoingConcernResult:
    ...
```

`opinion_html`이 없으면 `GoingConcernResult(None, "skipped", None, None)`.
MU 없으면 `GoingConcernResult(0, "ok", None, None)`.
1이면 `going_concern=1`, `status="ok"`, `raw`는 매칭 제목 또는 근거 한 줄, `source`는 `heading` / `eom` / `grounds`.
이 함수는 예외를 삼키지 않는다. 예외 처리는 Task 6.

- [ ] **Step 1: 실패하는 테스트 작성**

`packages/web-api/tests/test_extracting_going_concern.py`:

```python
from app.extracting.going_concern import extract_going_concern


def _html(*paragraphs: str) -> str:
    body = "".join(f"<p>{text}</p>" for text in paragraphs)
    return f"<html><body>{body}</body></html>"


_RESP = (
    "경영진은 재무제표를 작성할 때 회사의 계속기업으로서의 존속능력을 평가하고 "
    "계속기업 관련 사항을 공시할 책임이 있습니다."
)
_AUDITOR_RESP = (
    "경영진이 사용한 회계의 계속기업전제의 적절성과 중요한 불확실성이 존재하는지 "
    "여부에 대하여 결론을 내립니다."
)


def test_missing_html_is_skipped() -> None:
    result = extract_going_concern(None)
    assert result.status == "skipped"
    assert result.going_concern is None


def test_boilerplate_responsibility_only_is_zero() -> None:
    result = extract_going_concern(_html("감사의견", "적정입니다.", _RESP, _AUDITOR_RESP))
    assert result.status == "ok"
    assert result.going_concern == 0
    assert result.source is None


def test_2018_heading_is_one() -> None:
    result = extract_going_concern(
        _html(
            "감사의견",
            "적정입니다.",
            "계속기업 관련 중요한 불확실성",
            "주석 XXX에 주의를 기울여야 할 필요가 있습니다. "
            "계속기업으로서의 존속능력에 유의적 의문을 제기할 만한 중요한 불확실성이 존재함을 나타냅니다. "
            "우리의 의견은 이 사항으로부터 영향을 받지 아니합니다.",
            "핵심감사사항",
            "우리는 계속기업 관련 중요한 불확실성 단락에 기술된 사항에 추가하여 핵심감사사항을 결정하였습니다.",
            "재무제표에 대한 경영진과 지배기구의 책임",
            _RESP,
            "재무제표감사에 대한 감사인의 책임",
            _AUDITOR_RESP,
        )
    )
    assert result.going_concern == 1
    assert result.source == "heading"
    assert result.status == "ok"
    assert result.raw is not None


def test_2014_eom_is_one() -> None:
    result = extract_going_concern(
        _html(
            "감사의견",
            "적정입니다.",
            "강조사항",
            "감사의견에는 영향을 미치지 않는 사항으로서 이용자는 주석 X에 주의를 기울여야 할 필요가 있습니다. "
            "이러한 상황은 계속기업으로서의 존속능력에 유의적 의문을 제기할 만한 중요한 불확실성이 존재함을 나타냅니다.",
            "경영진의 책임",
            _RESP,
        )
    )
    assert result.going_concern == 1
    assert result.source == "eom"


def test_qualified_grounds_is_one() -> None:
    result = extract_going_concern(
        _html(
            "한정의견 근거",
            "이 상황은 계속기업으로서의 존속능력에 유의적 의문을 제기할 수 있는 중요한 불확실성의 존재를 나타냅니다. "
            "재무제표에는 이 사실이 적절하게 공시되지 않았습니다.",
            "한정의견",
            "한정의견근거문단에 기술된 사항을 제외하고는 공정하게 표시하고 있습니다.",
        )
    )
    assert result.going_concern == 1
    assert result.source == "grounds"


def test_litigation_eom_is_zero() -> None:
    result = extract_going_concern(
        _html(
            "강조사항",
            "회사를 상대로 소송이 제기되었으며 소송의 결과는 불확실합니다. "
            "우리의 의견은 이 사항과 관련하여 영향을 받지 아니합니다.",
        )
    )
    assert result.going_concern == 0


def test_liquidation_eom_is_zero() -> None:
    result = extract_going_concern(
        _html(
            "강조사항",
            "회사는 주주총회 결의에 따라 청산될 예정입니다. "
            "이에 따라 회사의 재무제표는 청산가치를 기반으로 작성되었습니다.",
        )
    )
    assert result.going_concern == 0


def test_other_matter_prior_year_is_zero() -> None:
    result = extract_going_concern(
        _html(
            "감사의견",
            "적정입니다.",
            "기타사항",
            "전기 감사보고서에는 계속기업 가정의 불확실성에 대한 부적절한 공시로 인한 한정의견이 표명되었습니다.",
            "재무제표에 대한 경영진과 지배기구의 책임",
            _RESP,
        )
    )
    assert result.going_concern == 0
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_going_concern.py -q`

Expected: FAIL (`going_concern.py` import error)

- [ ] **Step 3: 최소 구현**

`packages/web-api/app/extracting/going_concern.py` 전체:

```python
"""의견서 HTML에서 당기 계속기업 중요한 불확실성(MU)을 판정한다."""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.extracting.text import compact

_HEADING = "계속기업관련중요한불확실성"
_GC_STEMS = ("계속기업가정", "계속기업전제", "계속기업")
_MU_MARKERS = ("중요한불확실성",)
_DOUBT_MARKERS = ("존속능력", "유의적의문", "유의적의문을")
_LIQUIDATION = ("청산가치", "청산기준")
_GROUNDS_HEADS = ("한정의견근거", "부적정의견근거", "의견거절근거")
_EOM_HEADS = ("강조사항", "특기사항")
_STRIP_FROM = (
    "재무제표에대한경영진과지배기구의책임",
    "연결재무제표에대한경영진과지배기구의책임",
    "재무제표에대한경영진의책임",
    "연결재무제표에대한경영진의책임",
    "재무제표감사에대한감사인의책임",
    "연결재무제표감사에대한감사인의책임",
    "감사인의책임",
    "기타사항",
)
_EOM_END = (
    "핵심감사사항",
    "기타사항",
    "재무제표에대한경영진과지배기구의책임",
    "재무제표에대한경영진의책임",
    "경영진의책임",
    "한정의견근거",
    "부적정의견근거",
    "의견거절근거",
)
_GROUNDS_END = (
    "한정의견",
    "부적정의견",
    "의견거절",
    "강조사항",
    "특기사항",
    "핵심감사사항",
    "기타사항",
    "재무제표에대한경영진과지배기구의책임",
    "재무제표에대한경영진의책임",
)


@dataclass(frozen=True)
class GoingConcernResult:
    """당기 계속기업 MU 판정."""

    going_concern: int | None
    status: str
    raw: str | None
    source: str | None


def _compact_html(html: str) -> str:
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    return compact(text)


def _cut_from(compacted: str, markers: tuple[str, ...]) -> str:
    cuts = [compacted.find(marker) for marker in markers]
    hits = [index for index in cuts if index >= 0]
    if not hits:
        return compacted
    return compacted[: min(hits)]


def _section_after(compacted: str, head: str, ends: tuple[str, ...]) -> str | None:
    start = compacted.find(head)
    if start < 0:
        return None
    body = compacted[start + len(head) :]
    return _cut_from(body, ends)


def _has_gc_heading(compacted: str) -> bool:
    start = 0
    while True:
        found = compacted.find(_HEADING, start)
        if found < 0:
            return False
        after = compacted[found + len(_HEADING) :]
        if not after.startswith("단락"):
            return True
        start = found + 1


def _has_mu(compacted: str) -> bool:
    if not any(stem in compacted for stem in _GC_STEMS):
        return False
    if any(marker in compacted for marker in _MU_MARKERS):
        return True
    return any(marker in compacted for marker in _DOUBT_MARKERS)


def _is_liquidation_only(compacted: str) -> bool:
    if not any(token in compacted for token in _LIQUIDATION):
        return False
    return "중요한불확실성" not in compacted


def extract_going_concern(opinion_html: str | None) -> GoingConcernResult:
    """의견서 HTML에서 당기 MU가 있으면 1, 없으면 0이다. HTML이 없으면 skipped."""
    if not opinion_html:
        return GoingConcernResult(None, "skipped", None, None)

    full = _compact_html(opinion_html)
    searchable = _cut_from(full, _STRIP_FROM)

    if _has_gc_heading(searchable):
        return GoingConcernResult(1, "ok", "계속기업 관련 중요한 불확실성", "heading")

    for head in _EOM_HEADS:
        section = _section_after(searchable, head, _EOM_END)
        if not section:
            continue
        if _is_liquidation_only(section):
            continue
        if _has_mu(section):
            snippet = section[:80]
            return GoingConcernResult(1, "ok", snippet, "eom")

    for head in _GROUNDS_HEADS:
        section = _section_after(full, head, _GROUNDS_END)
        if not section:
            continue
        if _has_mu(section):
            snippet = section[:80]
            return GoingConcernResult(1, "ok", snippet, "grounds")

    return GoingConcernResult(0, "ok", None, None)
```

근거 단락은 책임·기타사항 자르기 **전** `full`에서 찾는다. 한정의견 근거가 경영진 책임보다 앞에 있는 신 서식과, 뒤에 있는 종전 후행형을 모두 잡기 위함이다. `기타사항`만 잘린 `searchable`에서는 전기 인용이 빠진다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_going_concern.py -q`

Expected: PASS. 실패하면 fixture compact와 `_STRIP_FROM`/`_EOM_END`를 맞춘다. `classify_opinion`은 수정하지 않는다.

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/extracting/going_concern.py packages/web-api/tests/test_extracting_going_concern.py
git commit -m "feat: 의견서에서 당기 계속기업 불확실성을 판정한다"
```

---

### Task 3: 종속기업 세기 파서

**Files:**
- Create: `packages/web-api/app/extracting/subsidiaries.py`
- Test: `packages/web-api/tests/test_extracting_subsidiaries.py`

**Interfaces:**
- Consumes: `compact`, `expand_table_matrix`, BeautifulSoup
- Produces:

```python
@dataclass(frozen=True)
class SubsidiaryResult:
    count: int | None
    status: str
    source: str | None

def notes_tail(html: str) -> str: ...

def extract_subsidiaries(
    *,
    fs_scope: str,
    notes_html: str | None,
    a001_html: str | None,
) -> SubsidiaryResult: ...
```

`fs_scope != "consolidated"`이면 즉시 `not_applicable`, count/source null (HTML 무시).
주석에서 세면 `source="notes"`. A001만 성공하면 `source="a001"`.
표를 세었으면 행 수 0도 `ok`. 구분이 안 되면 `not_found`.
둘 다 HTML이 없고 연결이면 `skipped`가 아니라 **호출측**이 skipped를 넣는다. 이 함수에 둘 다 None이면 `not_found`.

- [ ] **Step 1: 실패하는 테스트 작성**

`packages/web-api/tests/test_extracting_subsidiaries.py`:

```python
from app.extracting.accounts import cut_notes
from app.extracting.subsidiaries import extract_subsidiaries, notes_tail


def test_separate_is_not_applicable() -> None:
    result = extract_subsidiaries(
        fs_scope="separate",
        notes_html="<p>종속기업</p>",
        a001_html=None,
    )
    assert result.status == "not_applicable"
    assert result.count is None


def test_notes_counts_body_rows() -> None:
    html = """
    <html><body>
    <p>3. 종속기업</p>
    <table>
    <tr><td>회사명</td><td>소재지</td><td>지분율</td></tr>
    <tr><td>갑주식회사</td><td>한국</td><td>100%</td></tr>
    <tr><td>을주식회사</td><td>한국</td><td>80%</td></tr>
    <tr><td>합계</td><td></td><td></td></tr>
    </table>
    </body></html>
    """
    result = extract_subsidiaries(fs_scope="consolidated", notes_html=html, a001_html=None)
    assert result.status == "ok"
    assert result.count == 2
    assert result.source == "notes"


def test_kind_column_counts_subsidiary_only() -> None:
    html = """
    <html><body>
    <p>연결대상 및 관계기업</p>
    <table>
    <tr><td>회사명</td><td>구분</td></tr>
    <tr><td>갑</td><td>종속기업</td></tr>
    <tr><td>을</td><td>관계기업</td></tr>
    <tr><td>병</td><td>공동기업</td></tr>
    </table>
    </body></html>
    """
    result = extract_subsidiaries(fs_scope="consolidated", notes_html=html, a001_html=None)
    assert result.status == "ok"
    assert result.count == 1


def test_related_party_title_without_kind_is_not_found() -> None:
    html = """
    <html><body>
    <p>특수관계자</p>
    <table>
    <tr><td>회사명</td><td>거래</td></tr>
    <tr><td>갑</td><td>매출</td></tr>
    </table>
    </body></html>
    """
    result = extract_subsidiaries(fs_scope="consolidated", notes_html=html, a001_html=None)
    assert result.status == "not_found"
    assert result.count is None


def test_empty_subsidiary_table_is_zero() -> None:
    html = """
    <html><body>
    <p>종속기업</p>
    <table>
    <tr><td>회사명</td><td>소재지</td></tr>
    </table>
    </body></html>
    """
    result = extract_subsidiaries(fs_scope="consolidated", notes_html=html, a001_html=None)
    assert result.status == "ok"
    assert result.count == 0


def test_a001_requires_kind_column() -> None:
    mixed = """
    <html><body>
    <p>계열회사의 현황</p>
    <table>
    <tr><td>회사명</td><td>업종</td></tr>
    <tr><td>갑</td><td>제조</td></tr>
    <tr><td>을</td><td>판매</td></tr>
    </table>
    </body></html>
    """
    result = extract_subsidiaries(fs_scope="consolidated", notes_html=None, a001_html=mixed)
    assert result.status == "not_found"

    ok_html = """
    <html><body>
    <p>계열회사의 현황</p>
    <table>
    <tr><td>회사명</td><td>관계</td></tr>
    <tr><td>갑</td><td>종속회사</td></tr>
    <tr><td>을</td><td>관계회사</td></tr>
    </table>
    </body></html>
    """
    result = extract_subsidiaries(fs_scope="consolidated", notes_html=None, a001_html=ok_html)
    assert result.status == "ok"
    assert result.count == 1
    assert result.source == "a001"


def test_notes_tail_is_inverse_of_cut_notes() -> None:
    html = "<p>재무상태표</p><table><tr><td>자산총계</td></tr></table>주석 1. 종속기업"
    assert "자산총계" in cut_notes(html)
    assert "종속기업" in notes_tail(html)
    assert "자산총계" not in notes_tail(html)
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_subsidiaries.py -q`

Expected: FAIL (import error)

- [ ] **Step 3: 최소 구현**

`packages/web-api/app/extracting/subsidiaries.py`:

```python
"""연결 주석·A001 계열회사 표에서 종속기업 수를 센다."""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from app.extracting.table_matrix import expand_table_matrix
from app.extracting.text import compact

_SKIP_ROW = ("합계", "소계")
_KIND_HEADERS = ("구분", "관계", "기업구분")
_NAME_HINTS = ("회사명", "기업명", "종속기업명", "법인명")
_NOTES_MARKER = "주석 "


@dataclass(frozen=True)
class SubsidiaryResult:
    """연결 종속기업 수."""

    count: int | None
    status: str
    source: str | None


def notes_tail(html: str) -> str:
    """cut_notes와 같은 구분자 뒤만 남긴다."""
    if _NOTES_MARKER not in html:
        return ""
    return html.split(_NOTES_MARKER, 1)[1]


def _heading_before(table: Tag) -> str:
    for sibling in table.previous_siblings:
        if not isinstance(sibling, Tag):
            continue
        if sibling.name in {"p", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "span", "div"}:
            token = compact(sibling.get_text(" ", strip=True))
            if token:
                return token
        if sibling.name == "table":
            break
    return ""


def _is_notes_candidate_heading(heading: str) -> bool:
    if any(token in heading for token in ("특수관계자",)):
        if "종속기업" not in heading and "연결대상" not in heading:
            return False
    if "관계기업" in heading and "종속" not in heading:
        return False
    if "공동기업" in heading and "종속" not in heading:
        return False
    return "종속기업" in heading or "연결대상" in heading or "종속" in heading


def _header_row_index(matrix: list[list[str]]) -> int:
    for index, row in enumerate(matrix[:3]):
        joined = compact("".join(row))
        if any(hint in joined for hint in _NAME_HINTS + _KIND_HEADERS):
            return index
    return 0


def _kind_col(header: list[str]) -> int | None:
    for index, cell in enumerate(header):
        token = compact(cell)
        if any(name in token for name in _KIND_HEADERS):
            return index
    return None


def _is_skip_row(cells: list[str]) -> bool:
    token = compact("".join(cells))
    if not token:
        return True
    return any(marker in token for marker in _SKIP_ROW)


def _is_subsidiary_kind(cell: str) -> bool:
    token = compact(cell)
    if "관계" in token or "공동" in token:
        return False
    return "종속" in token


def _count_table(table: Tag, *, require_kind: bool) -> int | None:
    matrix = expand_table_matrix(table)
    if not matrix:
        return None
    header_i = _header_row_index(matrix)
    header = matrix[header_i]
    kind_i = _kind_col(header)
    if require_kind and kind_i is None:
        return None
    body_rows = 0
    count = 0
    for row in matrix[header_i + 1 :]:
        if _is_skip_row(row):
            continue
        if not any(compact(cell) for cell in row):
            continue
        body_rows += 1
        if kind_i is not None:
            kind_cell = row[kind_i] if kind_i < len(row) else ""
            if not _is_subsidiary_kind(kind_cell):
                continue
        count += 1
    if require_kind and body_rows > 0 and count == 0:
        return None
    return count


def _count_from_html(html: str, *, require_kind: bool, notes_mode: bool) -> int | None:
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        heading = _heading_before(table)
        if notes_mode and not require_kind:
            if not _is_notes_candidate_heading(heading):
                continue
        counted = _count_table(table, require_kind=require_kind)
        if counted is None:
            continue
        heading_ok = "종속기업" in heading or "연결대상" in heading
        if notes_mode and not heading_ok and not require_kind:
            continue
        return counted
    return None


def extract_subsidiaries(
    *,
    fs_scope: str,
    notes_html: str | None,
    a001_html: str | None,
) -> SubsidiaryResult:
    """연결만 종속기업 행을 센다. 별도는 not_applicable."""
    if fs_scope != "consolidated":
        return SubsidiaryResult(None, "not_applicable", None)

    if notes_html:
        counted = _count_from_html(notes_html, require_kind=False, notes_mode=True)
        if counted is not None:
            return SubsidiaryResult(counted, "ok", "notes")

    if a001_html:
        counted = _count_from_html(a001_html, require_kind=True, notes_mode=False)
        if counted is not None:
            return SubsidiaryResult(counted, "ok", "a001")

    return SubsidiaryResult(None, "not_found", None)
```

`_count_from_html`의 `expand_table_matrix` 중복 호출은 Step 4에서 한 번만 부르도록 정리해도 된다. 동작이 테스트와 같으면 충분하다.

혼합 제목 `연결대상 및 관계기업`은 `연결대상`이 있어 후보가 되고, 구분 칸으로 종속만 센다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_subsidiaries.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/extracting/subsidiaries.py packages/web-api/tests/test_extracting_subsidiaries.py
git commit -m "feat: 주석·A001에서 종속기업만 센다"
```

---

### Task 4: selector에 주석·계열회사 leaf

**Files:**
- Modify: `packages/web-api/app/extracting/selector.py`
- Test: `packages/web-api/tests/test_extracting_selector.py`

**Interfaces:**
- Consumes: 기존 `SelectorEntry`, `fs_scope_for`, `_is_notes_section`
- Produces: `LeafIds`에 `notes_entry_id: str | None`, `a001_affiliate_entry_id: str | None`. 연결일 때만 `notes_entry_id`. A001 계열은 접수 전체 entry에서 고른다.

- [ ] **Step 1: 실패하는 테스트 작성**

`test_extracting_selector.py`에 추가:

```python
def test_select_leaves_consolidated_picks_exact_notes() -> None:
    """연결 문서의 정확 주석 leaf만 고르고 본표 주석은 제외한다."""
    rows = [
        SelectorEntry("c", "r", "d", "F002", "body", "연결감사보고서", "감사보고서"),
        SelectorEntry("n", "r", "d", "F002", "body", "연결감사보고서", "주석"),
        SelectorEntry(
            "bsn", "r", "d", "F002", "body", "연결감사보고서", "재무상태표에 대한 주석"
        ),
    ]
    leaves = select_leaves(rows)
    assert leaves.notes_entry_id == "n"


def test_select_leaves_separate_skips_notes() -> None:
    """별도 문서는 주석 leaf를 고르지 않는다."""
    rows = [
        SelectorEntry("c", "r", "d", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry("n", "r", "d", "F001", "body", "감사보고서", "주석"),
    ]
    leaves = select_leaves(rows)
    assert leaves.notes_entry_id is None


def test_select_leaves_a001_affiliate_prefers_status_section() -> None:
    """계열회사 현황이 부모보다 앞이고 타법인출자는 제외한다."""
    rows = [
        SelectorEntry("c", "r", "d1", "A001", "attachment", "연결감사보고서", "감사보고서"),
        SelectorEntry(
            "parent", "r", "d2", "A001", "body", "사업보고서", "IX. 계열회사 등에 관한 사항"
        ),
        SelectorEntry(
            "status", "r", "d2", "A001", "body", "사업보고서", "1. 계열회사의 현황"
        ),
        SelectorEntry(
            "inv", "r", "d2", "A001", "body", "사업보고서", "타법인출자 현황"
        ),
    ]
    leaves = select_leaves(rows)
    assert leaves.a001_affiliate_entry_id == "status"
```

기존 F001 테스트는 `notes_entry_id is None`, `a001_affiliate_entry_id is None`을 추가로 단언해도 된다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_selector.py::test_select_leaves_consolidated_picks_exact_notes tests/test_extracting_selector.py::test_select_leaves_separate_skips_notes tests/test_extracting_selector.py::test_select_leaves_a001_affiliate_prefers_status_section -q`

Expected: FAIL (`LeafIds`에 필드 없음)

- [ ] **Step 3: 최소 구현**

`LeafIds`에 두 필드를 추가한다.

```python
def _is_a001_affiliate_leaf(entry: SelectorEntry) -> bool:
    if entry.report_type != "A001" or entry.source != "body":
        return False
    token = compact(entry.section_name)
    if "타법인출자" in token:
        return False
    return "계열회사" in token


def _a001_affiliate_priority(entry: SelectorEntry) -> int:
    token = compact(entry.section_name)
    if "계열회사현황" in token or "계열회사의현황" in token:
        return 0
    return 1
```

`select_leaves`에서 `icfr_scope` 계산 뒤에:

```python
    notes_entry_id = None
    if icfr_scope == "consolidated":
        notes_entry_id = next(
            (entry.entry_id for entry in audit_entries if _is_notes_section(entry)),
            None,
        )

    affiliate_candidates = [entry for entry in entries if _is_a001_affiliate_leaf(entry)]
    a001_affiliate_entry_id = (
        min(affiliate_candidates, key=_a001_affiliate_priority).entry_id
        if affiliate_candidates
        else None
    )
```

`return LeafIds(...)`에 두 인자를 넣는다. `_is_notes_section`은 이미 compact `== "주석"`이다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_selector.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/extracting/selector.py packages/web-api/tests/test_extracting_selector.py
git commit -m "feat: 연결 주석과 A001 계열회사 leaf를 고른다"
```

---

### Task 5: 스키마·버전·Public 필드

**Files:**
- Modify: `packages/web-api/app/models/audit_report_fact.py`
- Modify: `packages/web-api/app/db/session.py`
- Modify: `packages/web-api/app/schemas/facts.py`
- Modify: `packages/web-api/app/extracting/constants.py`
- Modify: `packages/web-api/tests/test_audit_report_fact_repository.py`
- Modify: `packages/web-api/tests/test_ensure_schema.py`

**Interfaces:**
- Consumes: Task 없음 (컬럼만)
- Produces: `going_concern: int | None`, `going_concern_status`, `going_concern_raw`, `going_concern_source`, `subsidiary_count: int | None`, `subsidiary_status`, `subsidiary_source`, `notes_entry_id`, `a001_affiliate_entry_id`. `EXTRACTOR_VERSION = "audit_opinion.v16"`. `AuditReportFactItem`에 동일 필드. `ensure_schema` 패치.

- [ ] **Step 1: 실패하는 테스트 작성**

`test_audit_report_fact_repository.py`의 `SPEC_FACT_COLUMNS` 튜플 끝에 추가:

```python
    "going_concern",
    "going_concern_status",
    "going_concern_raw",
    "going_concern_source",
    "subsidiary_count",
    "subsidiary_status",
    "subsidiary_source",
    "notes_entry_id",
    "a001_affiliate_entry_id",
```

`test_extractor_version_constant`를 `audit_opinion.v16`으로 바꾼다.

`test_ensure_schema.py`의 `test_ensure_schema_adds_hours_to_legacy_audit_report_facts` 단언에 새 컬럼 이름을 추가한다 (기존 icfr 단언 옆).

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_audit_report_fact_repository.py::test_audit_report_fact_has_all_spec_columns tests/test_audit_report_fact_repository.py::test_extractor_version_constant tests/test_ensure_schema.py::test_ensure_schema_adds_hours_to_legacy_audit_report_facts -q`

Expected: FAIL (컬럼 누락 또는 버전 v15)

- [ ] **Step 3: 최소 구현**

`constants.py`: `EXTRACTOR_VERSION = "audit_opinion.v16"`

`audit_report_fact.py` — `icfr_status` 다음에, `fetch_status` 앞에:

```python
    going_concern: Mapped[int | None] = mapped_column()
    going_concern_status: Mapped[str | None] = mapped_column(String(32))
    going_concern_raw: Mapped[str | None] = mapped_column(Text)
    going_concern_source: Mapped[str | None] = mapped_column(String(32))
    subsidiary_count: Mapped[int | None] = mapped_column()
    subsidiary_status: Mapped[str | None] = mapped_column(String(32))
    subsidiary_source: Mapped[str | None] = mapped_column(String(32))
    notes_entry_id: Mapped[str | None] = mapped_column(String(128))
    a001_affiliate_entry_id: Mapped[str | None] = mapped_column(String(128))
```

Integer 컬럼은 SQLite/Postgres 모두 INTEGER. `mapped_column()`만으로 충분하다.

`session.py` `_COLUMN_PATCHES`에 icfr_status 다음으로 같은 형식 튜플을 추가한다.

| column | sqlite/postgres ddl |
|--------|---------------------|
| `going_concern` | `INTEGER` |
| `going_concern_status` | `VARCHAR(32)` |
| `going_concern_raw` | `TEXT` |
| `going_concern_source` | `VARCHAR(32)` |
| `subsidiary_count` | `INTEGER` |
| `subsidiary_status` | `VARCHAR(32)` |
| `subsidiary_source` | `VARCHAR(32)` |
| `notes_entry_id` | `VARCHAR(128)` |
| `a001_affiliate_entry_id` | `VARCHAR(128)` |

`schemas/facts.py` `AuditReportFactItem`의 icfr 필드 다음에 같은 이름을 넣는다.

```python
    going_concern: int | None = None
    going_concern_status: str | None = None
    going_concern_raw: str | None = None
    going_concern_source: str | None = None
    subsidiary_count: int | None = None
    subsidiary_status: str | None = None
    subsidiary_source: str | None = None
    notes_entry_id: str | None = None
    a001_affiliate_entry_id: str | None = None
```

`test_extraction_service.py` 등에서 `EXTRACTOR_VERSION == "audit_opinion.v15"` 단언이 있으면 v16으로 바꾼다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_audit_report_fact_repository.py tests/test_ensure_schema.py tests/test_facts_schema.py -q`

Expected: PASS. `test_facts_schema.py`가 생성자에 새 필드를 요구하지 않으면 기본 None으로 통과한다.

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/models/audit_report_fact.py packages/web-api/app/db/session.py packages/web-api/app/schemas/facts.py packages/web-api/app/extracting/constants.py packages/web-api/tests/test_audit_report_fact_repository.py packages/web-api/tests/test_ensure_schema.py
git commit -m "feat: 계속기업·종속기업 컬럼과 v16을 넣는다"
```

---

### Task 6: 추출 잡 연결과 field_partial

**Files:**
- Modify: `packages/web-api/app/services/extraction_service.py`
- Modify: `packages/web-api/app/services/completeness_service.py`
- Test: `packages/web-api/tests/test_extraction_service.py`
- Test: `packages/web-api/tests/test_extract_admin_api.py`

**Interfaces:**
- Consumes: `extract_going_concern`, `extract_subsidiaries`, `notes_tail`, `LeafIds.notes_entry_id`, `LeafIds.a001_affiliate_entry_id`
- Produces: fact 행에 GC·종속 필드. `_LEAF_ROLES`에 `notes_entry_id`. A001 계열은 주석 실패 후에만 fetch. `_NOT_FOUND_STATUSES`에 `going_concern_status`, `subsidiary_status`. `field_partial`은 `going_concern_status != "ok"` 또는 `subsidiary_status in {"skipped", "not_found"}`. `not_applicable`은 부분실패 아님.

- [ ] **Step 1: 실패하는 테스트 작성**

`test_extract_admin_api.py`의 `_ok_fact` 기본값에 다음을 넣는다. 넣지 않으면 Task 5 이후 F001 완전성 테스트가 `going_concern_status is None`으로 `field_partial`이 된다.

```python
        "going_concern": 0,
        "going_concern_status": "ok",
        "subsidiary_status": "not_applicable",
```

새 테스트:

```python
async def test_completeness_field_partial_includes_going_concern_skipped(
    memory_app,
) -> None:
    """다른 필드가 ok여도 going_concern_status=skipped면 field_partial이다."""
    app, sessionmaker = memory_app
    await _seed_completeness(sessionmaker, [_ok_fact(going_concern_status="skipped")])
    ...
    assert body["field_partial"] == 1


async def test_completeness_separate_not_applicable_is_not_field_partial(
    memory_app,
) -> None:
    """별도 문서의 subsidiary_status=not_applicable은 field_partial이 아니다."""
    app, sessionmaker = memory_app
    await _seed_completeness(sessionmaker, [_ok_fact()])
    ...
    assert body["field_partial"] == 0


async def test_completeness_subsidiary_not_found_is_field_partial(
    memory_app,
) -> None:
    await _seed_completeness(
        sessionmaker,
        [_ok_fact(fs_scope="consolidated", subsidiary_status="not_found")],
    )
    ...
    assert body["field_partial"] == 1
```

`_seed_completeness`와 HTTP 호출은 파일의 `test_completeness_field_partial_includes_icfr_skipped`를 그대로 복제하고 시드만 바꾼다.

`test_extraction_service.py`:

기존 F001 성공 테스트 단언에 추가:

```python
    assert fact.going_concern_status == "ok"
    assert fact.going_concern == 0  # fixture 의견서에 MU 없음
    assert fact.subsidiary_status == "not_applicable"
    assert fact.subsidiary_count is None
```

의견 HTML fixture에 MU가 있으면 0이 아니다. 기존 mock HTML을 확인하고, 책임 문단만 있으면 0이다.

새 테스트 (ICFR 테스트 패턴 복제. `_f002_leaves`가 없으면 F002 `document_name=연결감사보고서`로 커버·의견·주석 entry를 만든다):

```python
async def test_extract_job_counts_notes_subsidiaries(sessionmaker_fixture) -> None:
    """연결 주석 표를 세어 subsidiary_count를 넣는다."""
    ...


async def test_reparse_refetches_when_subsidiary_status_is_not_found(
    sessionmaker_fixture,
) -> None:
    """reparse는 subsidiary_status가 not_found여도 주석 HTML을 다시 가져온다."""
    ...
```

주석 HTML은 Task 3의 2행 fixture를 `http.fetch_html` mock이 `주석` URL에 반환하게 한다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_api.py::test_completeness_separate_not_applicable_is_not_field_partial tests/test_extraction_service.py -q`

Expected: FAIL (필드 미연결 또는 not_applicable이 partial)

- [ ] **Step 3: 최소 구현**

`extraction_service.py`:

- import `extract_going_concern`, `extract_subsidiaries`, `notes_tail`
- `_NOT_FOUND_STATUSES`에 `"going_concern_status"`, `"subsidiary_status"`
- `_LEAF_ROLES`에 `"notes_entry_id"` (required 아님)

`_extract_document`에서 기존 부모 제표 fetch **다음**, `_build_fact` **전**:

연결이고 `notes_entry_id`가 없고 `fs_parent_entry_id`가 있으며 `html_by_role`에 부모가 없으면 부모를 한 번 가져온다 (이미 제표용으로 가져왔으면 재사용).

`_build_fact` 안, icfr 블록과 비슷한 위치:

```python
        opinion_html = html_by_role.get("opinion_entry_id")
        try:
            gc = extract_going_concern(opinion_html)
        except Exception:
            logger.exception("계속기업 판정에 실패했습니다.")
            gc = None
        if gc is None:
            going_concern = None
            going_concern_status = "not_found"
            going_concern_raw = None
            going_concern_source = None
        else:
            going_concern = gc.going_concern
            going_concern_status = gc.status
            going_concern_raw = gc.raw
            going_concern_source = gc.source
```

종속: `_build_fact`는 sync이므로 **주석/A001 HTML은 `_extract_document`에서 이미 `html_by_role`에 넣어 둔다.**

`_extract_document` 추가 fetch:

1. `notes_entry_id`는 `_LEAF_ROLES`로 가져온다.
2. `fs_scope`는 `_build_fact` 안에서만 계산되므로, fetch 단계에서는 `fs_scope_for(sample.report_type or "", sample.document_name)`을 쓴다. A001 첨부는 `document_name`이 연결감사보고서/감사보고서라 기존 icfr와 같다.
3. 연결이고 주석 HTML이 없고 `fs_parent_entry_id`가 있으면 부모 HTML을 가져오거나 재사용한다. `_build_fact`에 `html_by_role["notes_html_resolved"]`를 넣지 말고, `_build_fact`에서:

```python
        notes_html = html_by_role.get("notes_entry_id")
        if notes_html is None and html_by_role.get("fs_parent_entry_id"):
            tail = notes_tail(html_by_role["fs_parent_entry_id"])
            notes_html = tail or None
```

A001 계열 fetch는 `_build_fact` 전이 아니라 `_extract_document`에서: 연결이고 (`notes_entry_id` HTML이 없으며 부모 꼬리도 비었거나, 여기선 파서를 아직 안 돌림).

**HTTP를 아끼려면** 주석 HTML을 `_extract_document`에서 파서까지 돌릴 수 없다(sync 파서는 가능). `_extract_document`에서 주석 HTML을 모은 뒤 `extract_subsidiaries`를 **fetch 단계에서 한 번** 호출하고, 실패이며 `leaves.a001_affiliate_entry_id`가 있으면 그 URL만 fetch한 다음 다시 `extract_subsidiaries`를 호출한다. 결과를 `_build_fact`에 인자로 넘기면 시그니처가 커진다.

더 작은 변경: `_build_fact`를 호출하기 **직전**에 로컬 변수로 종속 결과를 만들고, `_build_fact(..., subsidiary=..., going_concern=...)`는 피하고 `_build_fact` 안에서 파서만 호출하되, A001 fetch만 `_extract_document`에서 `html_by_role["a001_affiliate_entry_id"]`로 넣는다.

A001을 항상 fetch하면 스펙의 “1차 실패만”을 어긴다. 따라서 `_extract_document` 끝부분:

```python
        fs_scope_guess = fs_scope_for(sample.report_type or "", sample.document_name)
        notes_html = html_by_role.get("notes_entry_id")
        if notes_html is None and html_by_role.get("fs_parent_entry_id"):
            tail = notes_tail(html_by_role["fs_parent_entry_id"])
            if tail:
                notes_html = tail
        need_a001 = False
        if fs_scope_guess == "consolidated":
            preview = extract_subsidiaries(
                fs_scope=fs_scope_guess,
                notes_html=notes_html,
                a001_html=None,
            )
            need_a001 = preview.status != "ok" and bool(leaves.a001_affiliate_entry_id)
        if need_a001:
            aff = by_id.get(leaves.a001_affiliate_entry_id or "")
            if aff is not None and aff.viewer_url:
                try:
                    html = await self._http.fetch_html(aff.viewer_url)
                except SourceFetchError as exc:
                    if exc.status_code in _BLOCK_HTTP_STATUSES:
                        blocked = True
                else:
                    if html_looks_blocked(html):
                        blocked = True
                    else:
                        html_by_role["a001_affiliate_entry_id"] = html
```

부모를 주석용으로만 가져와야 하는 경우(연결, 주석 leaf 없음, BS/IS는 있어서 부모를 아직 안 가져옴):

```python
        if (
            fs_scope_guess == "consolidated"
            and not leaves.notes_entry_id
            and leaves.fs_parent_entry_id
            and "fs_parent_entry_id" not in html_by_role
        ):
            # 기존 부모 fetch와 동일한 try/except. 성공 시 html_by_role["fs_parent_entry_id"] = html
```

`_build_fact` 종속 블록:

```python
        notes_html = html_by_role.get("notes_entry_id")
        if notes_html is None and html_by_role.get("fs_parent_entry_id"):
            tail = notes_tail(html_by_role["fs_parent_entry_id"])
            notes_html = tail or None
        a001_aff_html = html_by_role.get("a001_affiliate_entry_id")
        if fs_scope != "consolidated":
            sub = extract_subsidiaries(fs_scope=fs_scope, notes_html=None, a001_html=None)
        elif notes_html is None and a001_aff_html is None:
            sub = SubsidiaryResult(None, "skipped", None)
        else:
            try:
                sub = extract_subsidiaries(
                    fs_scope=fs_scope,
                    notes_html=notes_html,
                    a001_html=a001_aff_html,
                )
            except Exception:
                logger.exception("종속기업 수 파싱에 실패했습니다.")
                sub = SubsidiaryResult(None, "not_found", None)
```

`AuditReportFact(...)`에 GC·종속 컬럼과 `notes_entry_id=leaves.notes_entry_id`, `a001_affiliate_entry_id=leaves.a001_affiliate_entry_id`를 넣는다.

`completeness_service.py`:

`_FIELD_STATUS_ATTRS`에 `"going_concern_status"`를 추가한다. `subsidiary_status`는 넣지 않는다.

```python
def _is_field_partial(fact: AuditReportFact) -> bool:
    if fact.fetch_status != "ok":
        return False
    if any(getattr(fact, name) != "ok" for name in _FIELD_STATUS_ATTRS):
        return True
    return fact.subsidiary_status in {"skipped", "not_found"}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py tests/test_extract_admin_api.py tests/test_extracting_going_concern.py tests/test_extracting_subsidiaries.py tests/test_extracting_accounts.py tests/test_extracting_selector.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/services/extraction_service.py packages/web-api/app/services/completeness_service.py packages/web-api/tests/test_extraction_service.py packages/web-api/tests/test_extract_admin_api.py
git commit -m "feat: 추출 잡에 계속기업·종속기업 수를 연결한다"
```

---

### Task 7: README와 공개 응답 회귀

**Files:**
- Modify: `packages/web-api/README.md`
- Modify: `packages/web-api/tests/test_facts_api.py` (목록 JSON에 새 키가 보이는지 단언 추가)

**Interfaces:**
- Consumes: Task 5 Public 스키마, Task 6 저장 행
- Produces: README v16·부채총계·GC·종속. `/api/v1/facts` 응답에 `going_concern`, `subsidiary_count` 키

- [ ] **Step 1: 실패하는 테스트 작성**

`test_facts_api.py`의 목록/단건 단언 근처에:

```python
    assert "going_concern" in row
    assert "subsidiary_status" in row
    assert "accounts" in row
```

시드 fact에 `going_concern=0`, `going_concern_status="ok"`, `subsidiary_status="not_applicable"`을 넣는다. 생성자가 새 컬럼을 모르면 Task 5 이후 기본 None으로도 키는 응답에 있다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

시드가 예전 `_ok` 헬퍼만 쓰면 키가 빠질 수 있다. FAIL이면 schema에 필드가 빠진 것이다.

- [ ] **Step 3: README 수정**

`packages/web-api/README.md`:

- Extracting 레이어 설명을 `audit_opinion.v16`으로
- 감사보고서 추출 절: 부채총계(`accounts`의 `total_liability`), 당기 계속기업 MU(`going_concern`), 연결 종속기업 수(`subsidiary_count`)를 같은 행에 붙인다고 적는다. 별도는 `not_applicable`. 주석 1차·A001 종속 구분 가능할 때만 2차.
- `field_partial` 설명에 `going_concern_status`를 넣고, `subsidiary_status`의 `skipped`/`not_found`만 부분실패이며 `not_applicable`은 아니라고 적는다.
- 계정 목록에 부채총계를 추가한다 (기존 8+유동 소계 + 부채총계).
- Public 조회 절에 `going_concern`·`subsidiary_count`를 언급한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_facts_api.py tests/test_facts_schema.py tests/test_export_audit_report_facts.py -q`

Expected: PASS

전체:

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_accounts.py tests/test_extracting_going_concern.py tests/test_extracting_subsidiaries.py tests/test_extracting_selector.py tests/test_extraction_service.py tests/test_extract_admin_api.py tests/test_audit_report_fact_repository.py tests/test_ensure_schema.py tests/test_extracting_opinion_gaap.py -q`

Expected: PASS. `classify_opinion`의 계속기업 창 자르기 테스트가 그대로 통과해야 한다.

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/README.md packages/web-api/tests/test_facts_api.py
git commit -m "docs: 추출 v16에 부채총계·계속기업·종속기업 수를 적는다"
```

---

## Self-review (spec coverage)

| 스펙 | 태스크 |
|------|--------|
| 부채총계 `accounts` / `_TOTAL_ACCOUNTS` / 부채와자본총계 제외 | Task 1 |
| GC 창 밖, heading/eom/grounds, 책임·소송·청산·기타사항=0 | Task 2 |
| 종속 주석 세기, 구분 칸, A001 구분 필수, 0행 ok, 별도 N/A | Task 3 |
| 정확 `주석`, 별도 skip, A001 계열·타법인출자 제외 | Task 4 |
| 컬럼·ensure_schema·Public·v16 | Task 5 |
| 같은 잡, 주석 HTTP, A001은 1차 실패만, reparse, field_partial | Task 6 |
| README·API 키 | Task 7 |
| `classify_opinion` 미변경 | Task 2 제약, Task 7 회귀 |
| 한공회 원문 미저장 | Global Constraints |

`notes_entry_id`가 부모 id와 같아질 수 있다는 스펙: 주석 leaf가 없고 부모 꼬리만 쓰면 DB `notes_entry_id`는 null이고 `fs_parent_entry_id`만 채운다. 꼬리 사용 여부를 별도 컬럼에 넣지 않는다.
