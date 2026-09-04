# 의견서 선행형·후행형 서식 분기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** compact 본문으로 2018년 감사기준서 700 전후 의견서 서식을 가른 뒤, 선행형은 끊는 표지 앞만, 후행형은 전문에서 D-3-2 키워드를 찾아 영신형 한정 미탐과 에코바이브형 인용 오탐을 같이 막는다.

**Architecture:** `classify_opinion`과 그 내부 순수 함수만 바꾼다. 선행 표지(`재무제표감사에대한보고` / `핵심감사사항` / `감사의견근거`)가 있으면 선행형 창을 쓰고, 없고 `경영진의책임` 뒤에 한정·거절·부적정 근거가 있으면 후행형으로 전문 검색한다. 어느 쪽도 아니면 선행형이다. `resolve_opinion`·GAAP·날짜 전처리·스키마는 그대로 둔다.

**Tech Stack:** Python 3.11+, `app.extracting.opinion` 순수 함수, pytest (live DART·LLM 없음)

**Spec:** `docs/superpowers/specs/2026-08-29-audit-opinion-letter-format-design.md`

## Global Constraints

- Python 3.11+, 모든 함수 타입 힌트
- 주석·Docstring·로그·예외·테스트 설명은 한국어
- extracting 순수 함수는 sync
- Black/Flake8, line length 100
- 테스트는 실제 DART·LLM을 호출하지 않음. 한공회 원문 파일은 저장하지 않음
- 작업 디렉터리 기본: `packages/web-api`
- 실행 시 git 커밋은 **사용자가 요청한 경우에만**. 아래 Commit 스텝은 메시지 초안이다
- D-3-2 키워드 튜플(`_DISCLAIMER_KEYWORDS` 등)과 그룹 순서는 바꾸지 않음. `의견을표명하지않`을 빼지 않음. 제목 `한정의견`/`의견거절`을 키워드로 추가하지 않음
- `resolve_opinion` 순위·A001 교차로 의견 코드를 뒤집지 않음
- `app/extracting/dates.py`의 `_FS_SECTION = "재무제표에대한경"`은 **그대로** 둔다
- 인용 무시(±80자, `일자로발행한감사보고서에서` / `비교표시목적으로`)는 v2와 동일
- `EXTRACTOR_VERSION`은 Task 2에서만 `audit_opinion.v3`로 올린다

---

## File map

| 파일 | 역할 |
|------|------|
| `app/extracting/opinion.py` | 서식 판별, 선행형 창, 후행형 전문, 기존 D-3-2 키워드·인용 무시 |
| `app/extracting/constants.py` | `EXTRACTOR_VERSION` → `audit_opinion.v3` |
| `tests/test_extracting_opinion_gaap.py` | 후행형·선행형 창·회귀 fixture |
| `tests/test_extraction_service.py` | 저장 행 `extractor_version` 기대값 |
| `tests/test_audit_report_fact_repository.py` | 버전 상수 테스트 |
| `app/extracting/dates.py` | **수정하지 않음** |

---

### Task 1: 서식 판별과 검색 구간

**Files:**
- Modify: `packages/web-api/app/extracting/opinion.py`
- Test: `packages/web-api/tests/test_extracting_opinion_gaap.py`

**Interfaces:**
- Consumes: `compact(value: str | None) -> str`, `FieldResult`, 기존 `_OPINION_GROUPS`, `_is_prior_report_citation`
- Produces:
  - `classify_opinion(text: str, *, looks_like_letter: bool) -> FieldResult` (시그니처 유지)
  - 내부 `_is_trailing_layout(compacted: str) -> bool`
  - 내부 `_preceding_window(compacted: str) -> str`
  - 내부 `_opinion_window(compacted: str) -> str` (후행형이면 전문, 아니면 선행형 창)
  - 상수 `_PRECEDING_HEADINGS`, `_TRAILING_GROUNDS`, `_PRECEDING_CUT_MARKERS` (기존 `_CUT_MARKERS`를 대체)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_extracting_opinion_gaap.py` 하단에 추가한다. 기존 테스트는 지우지 않는다. v2 회귀(`test_emphasis_of_matter_prior_disclaimer_is_unqualified` 등)는 그대로 통과해야 한다.

```python
def test_trailing_qualified_after_management_responsibility() -> None:
    """종전 후행형: 경영진의책임 뒤 한정의견근거는 전문에서 qualified이다."""
    text = (
        "우리는 연결재무제표를 감사하였습니다. "
        "연결재무제표에 대한 경영진의 책임 경영진은 작성 책임이 있습니다. "
        "감사인의 책임 우리는 감사하였습니다. "
        "한정의견근거 재고자산 과대계상. "
        "감사의견 한정의견근거단락에기술된사항이미치는영향을제외하고는 적정합니다."
    )
    result = classify_opinion(text, looks_like_letter=True)
    assert result.status == "ok"
    assert result.code == "qualified"
    assert result.raw == "한정의견근거"


def test_trailing_disclaimer_after_management_responsibility() -> None:
    """종전 후행형: 경영진의책임 뒤 의견거절근거는 전문에서 disclaimer이다."""
    text = (
        "우리는 연결재무제표를 감사하였습니다. "
        "연결재무제표에 대한 경영진의 책임 경영진은 작성 책임이 있습니다. "
        "의견거절근거 감사범위 제한. "
        "감사의견 우리는 의견을 표명하지 않습니다."
    )
    result = classify_opinion(text, looks_like_letter=True)
    assert result.code == "disclaimer"
    assert result.raw == "의견거절근거"


def test_new_unlisted_qualified_before_governance_responsibility() -> None:
    """신 비상장: KAM·감사의견근거 없이 근거는 창 안, 책임 단락의 거절은 창 밖이다."""
    text = (
        "감사의견 한정의견근거단락에기술된사항이미치는영향을제외하고는 적정합니다. "
        "경영진과 지배기구의 책임 경영진은 책임이 있습니다. "
        "과거 감사에서 의견을 표명하지 않았습니다."
    )
    result = classify_opinion(text, looks_like_letter=True)
    assert result.code == "qualified"
    assert result.raw == "한정의견근거단락에기술된사항이미치는영향을제외"


def test_going_concern_paragraph_after_opinion_is_cut() -> None:
    """선행형: 계속기업 단락의 거절 문구는 창 밖이라 적정이 된다."""
    text = (
        "감사의견 우리는 적정하다고 봅니다. "
        "감사의견근거 회계감사기준에 따라 감사를 수행하였습니다. "
        "계속기업 관련 중요한 불확실성. 의견을 표명하지 않습니다."
    )
    result = classify_opinion(text, looks_like_letter=True)
    assert result.code == "unqualified"
    assert result.raw == "boilerplate_unqualified"


def test_new_format_disclaimer_before_kam() -> None:
    """신 상장: 앞쪽 의견을표명하지않습니다는 disclaimer이다."""
    text = (
        "재무제표감사에 대한 보고 "
        "감사의견 우리는 의견을 표명하지 않습니다. "
        "의견거절근거 감사범위 제한. "
        "핵심감사사항 수익인식."
    )
    result = classify_opinion(text, looks_like_letter=True)
    assert result.code == "disclaimer"
    assert result.raw == "의견을표명하지않"


def test_preceding_cut_at_start_stays_unqualified() -> None:
    """선행형 표지가 맨 앞이면 구간이 비어 적정이 되고 전문으로 되돌리지 않는다."""
    text = "강조사항 의견을 표명하지 않습니다. " + ("가" * 80)
    result = classify_opinion(text, looks_like_letter=True)
    assert result.status == "ok"
    assert result.code == "unqualified"
    assert result.raw == "boilerplate_unqualified"
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run (cwd: `packages/web-api`):

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_extracting_opinion_gaap.py::test_trailing_qualified_after_management_responsibility tests/test_extracting_opinion_gaap.py::test_trailing_disclaimer_after_management_responsibility tests/test_extracting_opinion_gaap.py::test_new_unlisted_qualified_before_governance_responsibility tests/test_extracting_opinion_gaap.py::test_going_concern_paragraph_after_opinion_is_cut tests/test_extracting_opinion_gaap.py::test_new_format_disclaimer_before_kam tests/test_extracting_opinion_gaap.py::test_preceding_cut_at_start_stays_unqualified -v --tb=short
```

Expected:
- `test_trailing_qualified_after_management_responsibility` FAIL (`unqualified` vs `qualified`) — v2가 `재무제표에대한경`에서 잘라 근거가 창 밖
- `test_trailing_disclaimer_after_management_responsibility` FAIL (`unqualified` vs `disclaimer`) — 같은 이유
- `test_going_concern_paragraph_after_opinion_is_cut` FAIL (`disclaimer` vs `unqualified`) — `계속기업관련중요한불확실성`이 v2 표지에 없음
- 나머지 신규 테스트는 구현 전 실패하거나, 빈 창·비상장 창이 우연히 맞으면 PASS여도 된다. 구현 후 전부 PASS가 목표다

이어서 기존 파일 전체가 아직 깨지지 않았는지도 본다.

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_extracting_opinion_gaap.py -v --tb=short
```

Expected: 기존 v2 테스트는 PASS, 위 후행형·계속기업 테스트는 FAIL.

- [ ] **Step 3: 서식 판별과 구간을 구현**

`app/extracting/opinion.py`에서 `_CUT_MARKERS`와 `_opinion_window`를 아래처럼 교체한다. `_OPINION_GROUPS`, `_DISCLAIMER_KEYWORDS`, `_QUALIFIED_KEYWORDS`, `_ADVERSE_KEYWORDS`, `_SNIPPET_RADIUS`, `_CITATION_MARKERS`, `_is_prior_report_citation`은 그대로 둔다. `dates.py`는 열지 않는다.

```python
_PRECEDING_HEADINGS = (
    "재무제표감사에대한보고",
    "연결재무제표감사에대한보고",
    "핵심감사사항",
    "감사의견근거",
)
_TRAILING_GROUNDS = (
    "한정의견근거",
    "의견거절근거",
    "부적정의견근거",
)
_PRECEDING_CUT_MARKERS = (
    "강조사항",
    "핵심감사사항",
    "기타사항",
    "계속기업관련중요한불확실성",
    "감사의견에는영향을미치지않는사항",
    "영향을미치지않는사항",
    "경영진과지배기구의책임",
)


def _is_trailing_layout(compacted: str) -> bool:
    """종전 후행형인지 본다. 신 서식 표지가 없고 경영진의책임 뒤에 근거 표지가 있을 때다."""
    if any(heading in compacted for heading in _PRECEDING_HEADINGS):
        return False
    start = compacted.find("경영진의책임")
    if start < 0:
        return False
    after = compacted[start + len("경영진의책임") :]
    return any(ground in after for ground in _TRAILING_GROUNDS)


def _preceding_window(compacted: str) -> str:
    """선행형: 끊는 표지 앞만 남긴다. 표지가 없으면 전체다."""
    cuts = [compacted.find(marker) for marker in _PRECEDING_CUT_MARKERS]
    cuts = [index for index in cuts if index >= 0]
    if not cuts:
        return compacted
    return compacted[: min(cuts)]


def _opinion_window(compacted: str) -> str:
    """후행형이면 전문, 아니면 선행형 창이다. 빈 창을 전문으로 되돌리지 않는다."""
    if _is_trailing_layout(compacted):
        return compacted
    return _preceding_window(compacted)
```

`classify_opinion`의 검색 루프는 그대로 두고, Docstring만 서식 분기를 반영한다.

```python
def classify_opinion(text: str, *, looks_like_letter: bool) -> FieldResult:
    """감사의견 본문을 분류한다.

    looks_like_letter가 False이면 즉시 not_found를 반환한다.
    True이면 compact 본문으로 선행형·후행형을 가른 뒤, 해당 구간에서
    D-3-2 키워드를 거절→한정→부적정 순으로 찾고 과거 보고서 인용 히트는
    건너뛴다. 없으면 boilerplate 적정을 반환한다.
    """
    if not looks_like_letter:
        return FieldResult(raw=None, code=None, status="not_found")

    window = _opinion_window(compact(text))
    for code, keywords in _OPINION_GROUPS:
        for keyword in keywords:
            start = 0
            while True:
                found = window.find(keyword, start)
                if found < 0:
                    break
                if not _is_prior_report_citation(window, found, len(keyword)):
                    return FieldResult(raw=keyword, code=code, status="ok")
                start = found + 1

    return FieldResult(
        raw="boilerplate_unqualified",
        code="unqualified",
        status="ok",
    )
```

주의:
- `한정의견근거`에 `감사의견근거`는 포함되지 않는다. `_PRECEDING_HEADINGS`의 `감사의견근거`는 신 서식 적정 근거 제목만 잡는다.
- `경영진과지배기구의책임`에 `경영진의책임`은 부분문자열이 아니다. 구제목과 신 제목을 같은 표지로 쓰지 않는다.
- 선행형 표지 목록에 `재무제표에대한경`과 짧은 `경영진의책임`을 넣지 않는다.

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_extracting_opinion_gaap.py -v --tb=short
```

Expected: 해당 파일 전부 PASS. 통과 후 Black (line length 100):

```bash
.\.venv\Scripts\python.exe -m black --line-length 100 app/extracting/opinion.py tests/test_extracting_opinion_gaap.py
```

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/opinion.py packages/web-api/tests/test_extracting_opinion_gaap.py
git commit -m "fix(web-api): 의견서 선행형·후행형 서식에 맞춰 검색 구간을 가른다"
```

---

### Task 2: 추출기 버전 v3

**Files:**
- Modify: `packages/web-api/app/extracting/constants.py`
- Modify: `packages/web-api/tests/test_audit_report_fact_repository.py`
- Modify: `packages/web-api/tests/test_extraction_service.py`

**Interfaces:**
- Consumes: Task 1의 `classify_opinion`
- Produces: `EXTRACTOR_VERSION == "audit_opinion.v3"` (신규 추출 행 기본값)

reparse·extract 건너뛰기 로직은 바꾸지 않는다. 이미 `ok`인 행은 fact를 지운 뒤 `extract`한다(운영 절차, 코드 변경 없음).

- [ ] **Step 1: 실패하는 테스트 수정**

`test_extractor_version_constant`의 기대값을 `audit_opinion.v3`로 바꾼다.

```python
def test_extractor_version_constant() -> None:
    """추출기 버전 상수는 계획에 적힌 값을 쓴다."""
    assert EXTRACTOR_VERSION == "audit_opinion.v3"
```

`tests/test_extraction_service.py`의 `test_extract_f001_cover_and_opinion_saves_unqualified_fact`에서:

```python
assert fact.extractor_version == "audit_opinion.v3"
```

`tests/test_audit_report_fact_repository.py`의 roundtrip에서 `loaded.extractor_version == "audit_opinion.v2"`이면 `v3`로 바꾼다. (모델 default가 상수를 쓰므로 상수만 바꾸면 저장 테스트도 같이 맞춰야 한다.)

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_audit_report_fact_repository.py::test_extractor_version_constant tests/test_extraction_service.py::test_extract_f001_cover_and_opinion_saves_unqualified_fact -v --tb=short
```

Expected: FAIL (`audit_opinion.v2` vs `v3`).

- [ ] **Step 3: 상수 변경**

`app/extracting/constants.py`:

```python
"""추출기 버전 등 공유 상수."""

EXTRACTOR_VERSION = "audit_opinion.v3"
```

- [ ] **Step 4: 관련 테스트 통과 확인**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_extracting_opinion_gaap.py tests/test_audit_report_fact_repository.py tests/test_extraction_service.py tests/test_extracting_dates.py -q --tb=short
```

Expected: PASS. 날짜 전처리 테스트가 깨지면 `dates.py`를 고친 것이므로 되돌린다.

전체 스위트에서 `audit_opinion.v2` 문자열이 코드·테스트에 남으면 같은 값으로 고친 뒤 다시 돌린다. 스펙·계획의 역사적 언급은 그대로 둔다.

```bash
rg "audit_opinion\.v2" packages/web-api
```

Expected: 매칭 없음(또는 주석·과거 설명만).

전체 web-api 테스트:

```bash
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

Expected: PASS.

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/constants.py packages/web-api/tests/test_audit_report_fact_repository.py packages/web-api/tests/test_extraction_service.py
git commit -m "chore(web-api): 의견 서식 분기에 맞춰 추출기 버전을 v3로 올린다"
```

---

## Spec coverage

| 스펙 | 작업 |
|------|------|
| §3.1 선행 표지 1→2→3, 후행은 그 밖+`경영진의책임` 뒤 근거, 아니면 선행 | Task 1 `_is_trailing_layout` |
| §3.2 선행 끊는 표지(GC·지배기구 책임 포함, `재무제표에대한경`/`경영진의책임` 제외) | Task 1 `_PRECEDING_CUT_MARKERS` |
| §3.2 후행형 전문, 빈 창 폴백 없음 | Task 1 `_opinion_window` + `test_preceding_cut_at_start_stays_unqualified` |
| §3.3 키워드 순서·80자 인용 무시 | Task 1 기존 루프 유지, v2 회귀 테스트 유지 |
| §4 `audit_opinion.v3`, reparse는 기존 모드(코드 변경 없음) | Task 2 |
| §5 영신형·에코바이브형·비상장 신·신 한정·신 거절·v2 회귀 | Task 1 테스트 + 기존 fixture |
| §2·§6 밖 (LLM, A001 뒤집기, 짧은 키워드 삭제, conflicts, UI, dates.py) | 계획에 넣지 않음 |

`resolve_opinion`·추출 잡·reparse 보존 로직은 기존 구현을 그대로 쓴다.
이미 `ok`인 fact 백필은 운영에서 행을 지운 뒤 `extract`한다.
