# 의견서 강조사항 오탐 방지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 의견서 compact 본문에서 거절·한정·부적정 키워드를 근거 단락까지만 찾고, 과거 감사보고서 인용 히트는 버려 당기 적정이 거절로 오탐되지 않게 한다.

**Architecture:** `classify_opinion`만 바꾼다. compact 후 끊는 표지 앞에서 구간을 자르고, D-3-2 키워드를 그 안에서만 순회하며, 히트 앞뒤 80자에 인용 표지가 있으면 그 위치를 건너뛴다. `resolve_opinion`·GAAP·날짜·스키마는 그대로 둔다.

**Tech Stack:** Python 3.11+, `app.extracting.opinion` 순수 함수, pytest (live DART 없음)

**Spec:** `docs/superpowers/specs/2026-08-29-audit-opinion-letter-window-design.md`

## Global Constraints

- Python 3.11+, 모든 함수 타입 힌트
- 주석·Docstring·로그·예외·테스트 설명은 한국어
- extracting 순수 함수는 sync
- Black/Flake8, line length 100
- 테스트는 실제 DART·LLM을 호출하지 않음
- 작업 디렉터리 기본: `packages/web-api`
- 실행 시 git 커밋은 **사용자가 요청한 경우에만**. 아래 Commit 스텝은 메시지 초안이다
- D-3-2 키워드 목록에서 `의견을표명하지않`을 삭제하지 않음
- `resolve_opinion` 순위·A001 교차로 의견 코드를 뒤집지 않음

---

## File map

| 파일 | 역할 |
|------|------|
| `app/extracting/opinion.py` | 구간 자르기 + 인용 무시 + 기존 D-3-2 키워드 |
| `app/extracting/constants.py` | `EXTRACTOR_VERSION` → `audit_opinion.v2` |
| `tests/test_extracting_opinion_gaap.py` | 구간·인용·기존 분류 테스트 |
| `tests/test_extraction_service.py` | 저장 행 `extractor_version` 기대값 |
| `tests/test_audit_report_fact_repository.py` | 버전 상수 테스트 |

---

### Task 1: 검색 구간과 과거 인용 무시

**Files:**
- Modify: `packages/web-api/app/extracting/opinion.py`
- Test: `packages/web-api/tests/test_extracting_opinion_gaap.py`

**Interfaces:**
- Consumes: `compact(value: str | None) -> str`, `FieldResult`, 기존 `_OPINION_GROUPS`
- Produces:
  - `classify_opinion(text: str, *, looks_like_letter: bool) -> FieldResult` (시그니처 유지)
  - 내부 `_opinion_window(compacted: str) -> str`
  - 내부 `_is_prior_report_citation(compacted: str, start: int, length: int) -> bool`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_extracting_opinion_gaap.py` 하단에 추가한다. 기존 테스트는 지우지 않는다.

```python
def test_emphasis_of_matter_prior_disclaimer_is_unqualified() -> None:
    """강조사항의 과거 거절 인용은 당기 적정을 덮지 않는다."""
    text = (
        "감사의견 우리는 재무제표를 감사하였습니다. "
        "감사의견근거 대한민국의 회계감사기준에 따라 감사를 수행하였습니다. "
        + ("본문" * 40)
        + " 감사의견에는 영향을 미치지 않는 사항으로서 "
        "우리는 회사의 2021년 12월 31일로 종료되는 회계연도의 재무제표에 대하여 "
        "2022년 5월 16일자로 발행한 감사보고서에서 의견을 표명하지 않았습니다."
    )
    result = classify_opinion(text, looks_like_letter=True)
    assert result.status == "ok"
    assert result.code == "unqualified"
    assert result.raw == "boilerplate_unqualified"


def test_disclaimer_in_opinion_paragraph_still_disclaimer() -> None:
    """결론 문단의 거절 키워드는 그대로 disclaimer이다."""
    text = (
        "감사의견 우리는 의견을 표명하지 않습니다. "
        "의견거절근거 감사범위 제한. "
        + ("가" * 80)
        + " 강조사항 과거 보고서는 무효입니다."
    )
    result = classify_opinion(text, looks_like_letter=True)
    assert result.code == "disclaimer"
    assert result.raw == "의견을표명하지않"


def test_qualified_grounds_before_kam_still_qualified() -> None:
    """한정의견 근거 문구는 핵심감사사항 앞 구간에 있으면 qualified이다."""
    text = (
        "감사의견 한정의견근거단락에기술된사항이미치는영향을제외하고는 적정합니다. "
        "핵심감사사항 재고자산."
        + ("가" * 80)
    )
    result = classify_opinion(text, looks_like_letter=True)
    assert result.code == "qualified"


def test_no_cut_marker_keeps_full_text_disclaimer() -> None:
    """끊는 표지가 없으면 본문 전체에서 거절 키워드를 찾는다."""
    result = classify_opinion(
        "의견을표명하지아니합니다" + ("가" * 200),
        looks_like_letter=True,
    )
    assert result.code == "disclaimer"


def test_citation_without_cut_skips_hit_then_unqualified() -> None:
    """표지는 없어도 인용 문맥의 거절 히트는 버리고 적정이 된다."""
    text = (
        "감사의견 우리는 재무제표를 감사하였습니다. "
        + ("본문" * 30)
        + " 비교표시목적으로 첨부된 전기 재무제표에 대하여 "
        "의견을 표명하지 않았습니다."
    )
    result = classify_opinion(text, looks_like_letter=True)
    assert result.code == "unqualified"
    assert result.raw == "boilerplate_unqualified"
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run (cwd: `packages/web-api`):

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_extracting_opinion_gaap.py -v --tb=short
```

Expected: `test_emphasis_of_matter_prior_disclaimer_is_unqualified` FAIL (`disclaimer` vs `unqualified`). `test_citation_without_cut_skips_hit_then_unqualified`도 FAIL. 기존 테스트는 PASS.

- [ ] **Step 3: 구간 자르기와 인용 무시를 구현**

`app/extracting/opinion.py`를 아래와 같이 바꾼다. `_OPINION_GROUPS`와 키워드 튜플은 그대로 둔다.

```python
_SNIPPET_RADIUS = 80
_CUT_MARKERS = (
    "강조사항",
    "핵심감사사항",
    "기타사항",
    "재무제표에대한경",
    "감사의견에는영향을미치지않는사항",
    "영향을미치지않는사항",
)
_CITATION_MARKERS = (
    "일자로발행한감사보고서에서",
    "비교표시목적으로",
)


def _opinion_window(compacted: str) -> str:
    """끊는 표지 앞만 남긴다. 표지가 없으면 전체다."""
    cuts = [compacted.find(marker) for marker in _CUT_MARKERS]
    cuts = [index for index in cuts if index >= 0]
    if not cuts:
        return compacted
    return compacted[: min(cuts)]


def _is_prior_report_citation(compacted: str, start: int, length: int) -> bool:
    """히트 앞뒤 80자에 과거 보고서 인용 표지가 있는지 본다."""
    left = max(0, start - _SNIPPET_RADIUS)
    right = min(len(compacted), start + length + _SNIPPET_RADIUS)
    snippet = compacted[left:right]
    return any(marker in snippet for marker in _CITATION_MARKERS)


def classify_opinion(text: str, *, looks_like_letter: bool) -> FieldResult:
    """감사의견 본문을 분류한다.

    looks_like_letter가 False이면 즉시 not_found를 반환한다.
    True이면 끊는 표지 앞 구간에서 D-3-2 키워드를 거절→한정→부적정 순으로 찾고,
    과거 보고서 인용 히트는 건너뛴다. 없으면 boilerplate 적정을 반환한다.
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

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_extracting_opinion_gaap.py -v --tb=short
```

Expected: 해당 파일 전부 PASS.

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/opinion.py packages/web-api/tests/test_extracting_opinion_gaap.py
git commit -m "fix(web-api): 의견서 강조사항의 과거 거절 인용을 당기 의견으로 쓰지 않는다"
```

---

### Task 2: 추출기 버전 v2

**Files:**
- Modify: `packages/web-api/app/extracting/constants.py`
- Modify: `packages/web-api/tests/test_audit_report_fact_repository.py`
- Modify: `packages/web-api/tests/test_extraction_service.py`

**Interfaces:**
- Consumes: Task 1의 `classify_opinion`
- Produces: `EXTRACTOR_VERSION == "audit_opinion.v2"` (신규 추출 행 기본값)

- [ ] **Step 1: 실패하는 테스트 수정**

`test_extractor_version_constant`와 `test_extract_f001_cover_and_opinion_saves_unqualified_fact`의 기대값을 `audit_opinion.v2`로 바꾼다. `test_audit_report_fact_repository.py`에서 `loaded.extractor_version == "audit_opinion.v1"`인 단언이 있으면 함께 `v2`로 바꾼다. (모델 default가 상수를 쓰므로 상수만 바꾸면 저장 테스트도 같이 맞춰야 한다.)

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_audit_report_fact_repository.py::test_extractor_version_constant tests/test_extraction_service.py::test_extract_f001_cover_and_opinion_saves_unqualified_fact -v --tb=short
```

Expected: FAIL (`audit_opinion.v1` vs `v2`).

- [ ] **Step 3: 상수 변경**

`app/extracting/constants.py`:

```python
"""추출기 버전 등 공유 상수."""

EXTRACTOR_VERSION = "audit_opinion.v2"
```

- [ ] **Step 4: 관련 테스트 통과 확인**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_extracting_opinion_gaap.py tests/test_audit_report_fact_repository.py tests/test_extraction_service.py -q --tb=short
```

Expected: PASS. 전체 스위트에서 `audit_opinion.v1` 문자열이 남으면 같은 값으로 고친 뒤 다시 돌린다.

```bash
rg "audit_opinion\.v1" packages/web-api
```

Expected: 매칭 없음(또는 주석·과거 설명만).

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```bash
git add packages/web-api/app/extracting/constants.py packages/web-api/tests/test_audit_report_fact_repository.py packages/web-api/tests/test_extraction_service.py
git commit -m "chore(web-api): 의견 구간 분류에 맞춰 추출기 버전을 v2로 올린다"
```

---

## Spec coverage

| 스펙 | 작업 |
|------|------|
| §3.1 끊는 표지·근거 단락 포함·표지 없으면 전체 | Task 1 `_opinion_window` |
| §3.2 키워드 순서·80자 인용 무시·버린 히트는 raw에 없음 | Task 1 `classify_opinion` |
| §4 `audit_opinion.v2`, reparse는 기존 모드(코드 변경 없음) | Task 2 |
| §5 fixture 케이스 | Task 1 테스트 |
| §6 밖 (A001 뒤집기, 짧은 키워드 삭제, conflicts, UI) | 계획에 넣지 않음 |

`resolve_opinion`·추출 잡·reparse 보존 로직은 기존 구현을 그대로 쓴다.
