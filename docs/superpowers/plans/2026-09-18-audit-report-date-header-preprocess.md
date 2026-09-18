# 감사보고서일 후행형 머리글 전처리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `의견근거`가 없는 후행형 의견서에서 `재무제표에대한경` 앞 머리글의 `YYYY년M월D일`이 감사보고서일 후보에 들어가게 한다.

**Architecture:** `_preprocess`만 바꾼다. `의견근거`가 있으면 지금과 같고, 없고 `재무제표에대한경`이 있으면 그 첫 마커 앞을 `first_part`로 붙인다. 창 선택·정규식·추출기 버전·reparse 모드는 그대로다.

**Tech Stack:** Python 3.11+, pytest.

## Global Constraints

- 패키지: `packages/web-api`만.
- 주석·Docstring·로그·사용자 메시지는 한국어.
- 테스트: `packages/web-api`에서 `.\.venv\Scripts\python.exe -m pytest <파일> -q --tb=short`. Windows에서 pytest가 통과 후 hang하면 해당 파일 테스트가 모두 통과한 뒤 hang으로 본다.
- KSIC/OpenDART 워킹 트리 변경은 커밋에 넣지 않음.
- `EXTRACTOR_VERSION`은 `audit_opinion.v17` 유지. `app/extracting/constants.py`를 수정하지 않음.
- `pick_audit_report_date`·날짜 정규식·snippet·ExtractionService·selector·완전성 SQL·Admin UI·LLM 해소 잡을 수정하지 않음.
- 점 찍은 날짜, `귀중` 직후 고정, 머리글 첫 날짜 우선, `감사보고서일(` 우선, 후반 우선, 날짜 전용 reparse 모드 없음.

## File map

| 파일 | 책임 |
|------|------|
| `packages/web-api/tests/test_extracting_dates.py` | 후행형 머리글 날짜 회귀 테스트 |
| `packages/web-api/app/extracting/dates.py` | `_preprocess` 규칙과 docstring |

배포 후 운영자가 기존 `reparse`를 돌리는 것은 코드 작업이 아니다.

---

### Task 1: 후행형 머리글을 `_preprocess`에 포함

**Files:**
- Modify: `packages/web-api/tests/test_extracting_dates.py`
- Modify: `packages/web-api/app/extracting/dates.py` (`_preprocess`, 대략 118–133행)

**Interfaces:**
- Consumes: `_OPINION_GROUNDS: str` = `"의견근거"`, `_FS_SECTION: str` = `"재무제표에대한경"`
- Produces: `_preprocess(compact_text: str) -> str` — 시그니처 불변. `extract_date_candidates`·`pick_audit_report_date` 시그니처 불변.

- [ ] **Step 1: Write the failing test**

`packages/web-api/tests/test_extracting_dates.py`에서 `test_single_in_window_date_ok_when_markers_missing_or_partial` 바로 위에 추가한다. import는 그대로 `extract_date_candidates`, `pick_audit_report_date`만 쓴다.

```python
def test_trailing_letter_header_date_is_candidate_and_ok() -> None:
    """의견근거가 없으면 재무제표에대한경 앞 머리글 날짜가 후보이고 창 1개면 ok다."""
    text = (
        "독립된감사인의감사보고서이케이에프제일차주식회사주주및이사회귀중"
        "2015년12월24일우리는별첨된회사의재무제표를감사하였습니다."
        "해당재무제표는2015년10월31일과2015년7월31일현재의재무상태표로구성되어있습니다."
        "재무제표에대한경영진의책임경영자는대한민국의일반기업회계기준에따라이재무제표를작성합니다."
        "이감사보고서는감사보고서일현재로유효한것입니다."
    )
    candidates = extract_date_candidates(text)
    assert [c.iso for c in candidates] == [
        "2015-12-24",
        "2015-10-31",
        "2015-07-31",
    ]

    iso, status, passing = pick_audit_report_date(
        candidates,
        period_end=date(2015, 10, 31),
        rcept_dt=date(2016, 1, 13),
    )
    assert status == "ok"
    assert iso == "2015-12-24"
    assert len(passing) == 1
    assert passing[0].iso == "2015-12-24"
```

이 본문에는 `의견근거`가 없고 `재무제표에대한경`은 「재무제표에대한경영진의책임」에만 있다. 지금 `_preprocess`는 그 마커 뒤만 남기므로 후보가 비고, `assert [c.iso for c in candidates] == [...]`에서 실패해야 한다.

- [ ] **Step 2: Run test to verify it fails**

Working directory: `packages/web-api`

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_extracting_dates.py::test_trailing_letter_header_date_is_candidate_and_ok -v --tb=short
```

Expected: FAIL. `candidates`가 `[]`이거나 `2015-12-24`가 없다. 구현을 먼저 넣고 이 테스트가 PASS하면 Step 1–2를 다시 한다.

- [ ] **Step 3: Write minimal implementation**

`packages/web-api/app/extracting/dates.py`의 `_preprocess`를 아래와 같이 바꾼다. `_OPINION_GROUNDS`·`_FS_SECTION` 상수와 `extract_date_candidates` 호출부는 그대로 둔다.

```python
def _preprocess(compact_text: str) -> str:
    """의견근거 앞(없으면 첫 재무제표에대한경 앞)과 마지막 재무제표에대한경 이후를 잇는다.

    마커가 없으면 본문을 두 번 붙이지 않는다.
    """
    if _OPINION_GROUNDS in compact_text:
        first_part = compact_text.split(_OPINION_GROUNDS)[0]
    elif _FS_SECTION in compact_text:
        first_part = compact_text.split(_FS_SECTION)[0]
    else:
        first_part = ""
    second_part = (
        compact_text.split(_FS_SECTION)[-1] if _FS_SECTION in compact_text else ""
    )
    if first_part or second_part:
        return first_part + second_part
    return compact_text
```

- [ ] **Step 4: Run the date tests and make sure they pass**

Working directory: `packages/web-api`

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_extracting_dates.py -q --tb=short
```

Expected: PASS (기존 14개 + 신규 1개 = 15 passed). 선행형 중간 구간 제외·마커 없음/하나만·창 0개 `not_found`·창 2개 `ambiguous`가 깨지면 `_preprocess`의 `의견근거` 분기를 되돌린다. `constants.py`의 버전이 바뀌었으면 되돌려 `audit_opinion.v17`로 둔다.

- [ ] **Step 5: Commit**

스펙 파일과 KSIC/OpenDART/추출 intake WIP는 넣지 않는다.

```powershell
git add -- packages/web-api/tests/test_extracting_dates.py packages/web-api/app/extracting/dates.py
git commit -m "fix: 후행형 의견서 머리글에서 감사보고서일을 후보에 넣는다"
```
