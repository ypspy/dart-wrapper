# 내부회계관리제도 감사·검토 의견 추출 (D-6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 같은 감사 dcm의 내부회계 leaf에서 감사/검토/none과 의견 코드를 읽어 `audit_report_facts` 컬럼에 저장하고, 기존 추출 잡·Public API·완전성에 붙인다.

**Architecture:** 재무제표 의견서 HTML은 이미 가져오므로 engagement 1차 판별에만 쓴다. 의견 코드는 내부회계 leaf compact만 본다. D-3 `classify_opinion`에 분기를 섞지 않고 `icfr.py` 순수 함수로 둔다. 기존 `POST /admin/extract/audit-opinion`이 ICFR leaf를 0~1장 더 fetch한다.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2 async, BeautifulSoup/lxml, pytest

**Spec:** `docs/superpowers/specs/2026-09-03-audit-icfr-opinion-extraction-design.md`

## Global Constraints

- Python 3.11+, 모든 함수 타입 힌트
- 주석·Docstring·로그·예외·테스트 설명은 한국어
- extracting 순수 함수는 sync. I/O는 async
- Black/Flake8, line length 100
- 테스트는 실제 DART를 호출하지 않음. 한공회·기준서 원문 파일은 저장하지 않음
- 작업 디렉터리 기본: `packages/web-api`
- 실행: `.\.venv\Scripts\python.exe -m pytest <path> -q`
- git 커밋은 **사용자가 요청한 경우에만**. 아래 Commit 스텝은 메시지 초안이다
- OpenDART 사용 금지. HTML 원문 DB 저장 금지
- D-3 `classify_opinion` 변경 금지. 운영보고서·D-7·ICFR 보고일·감사인명 금지
- 한 행에 별도+연결 두 세트 금지. 키워드 첫 매칭. 원전 D-6-1 마지막 매칭 금지
- 제목·키워드는 스펙 §6–§7 문자열을 **그대로** 쓴다

---

## File map

| 파일 | 역할 |
|------|------|
| `app/extracting/selector.py` | `LeafIds.icfr_entry_id`, `fs_scope` 맞춤 |
| `app/extracting/icfr.py` | `IcfrResult`, `extract_icfr` |
| `app/extracting/constants.py` | `EXTRACTOR_VERSION = "audit_opinion.v14"` |
| `app/models/audit_report_fact.py` | icfr 컬럼 |
| `app/db/session.py` | `ensure_schema` 패치 |
| `app/services/extraction_service.py` | ICFR fetch + 파서, reparse |
| `app/services/completeness_service.py` | `field_partial`에 `icfr_status` |
| `app/schemas/facts.py` | Public 응답 |
| `packages/web-api/README.md` | v14·ICFR 필드 |

TSV export는 `AuditReportFact.__table__.columns`를 쓰므로 모델만 추가하면 헤더가 따라온다.

---

### Task 1: Selector — 내부회계 leaf (`fs_scope` 맞춤)

**Files:**
- Modify: `app/extracting/selector.py`
- Test: `tests/test_extracting_selector.py`

**Interfaces:**
- Consumes: 기존 `SelectorEntry`, `select_leaves`, `is_audit_document`, `fs_scope_for`
- Produces: `LeafIds.icfr_entry_id: str | None`. 같은 감사 `dcm_no`. `separate`/`unknown`은 compact에 `내부회계관리제도`가 있고 `연결`이 없음. `consolidated`는 `연결내부회계관리제도`. `주석` 제외. 앞이 이김

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_extracting_selector.py`의 `test_select_leaves_f001` 단언에 `icfr_entry_id`를 추가하고, 아래 테스트를 같은 파일에 붙인다. `SelectorEntry` 순서는 기존과 같다.

```python
def test_select_leaves_f001() -> None:
    rows = [
        SelectorEntry("c", "r", "d", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry(
            "o", "r", "d", "F001", "body", "감사보고서", "독립된 감사인의 감사보고서"
        ),
        SelectorEntry("a", "r", "d", "F001", "body", "감사보고서", "외부감사 실시내용"),
        SelectorEntry(
            "x", "r", "d", "F001", "body", "감사보고서", "내부회계관리제도 검토의견"
        ),
    ]
    leaves = select_leaves(rows)
    assert leaves.cover_entry_id == "c"
    assert leaves.opinion_entry_id == "o"
    assert leaves.activity_entry_id == "a"
    assert leaves.icfr_entry_id == "x"
    assert leaves.a001_opinion_entry_id is None


def test_select_leaves_separate_ignores_consolidated_icfr() -> None:
    """별도 문서는 연결내부회계 leaf를 고르지 않는다."""
    rows = [
        SelectorEntry("c", "r", "d", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry(
            "con", "r", "d", "F001", "body", "감사보고서",
            "연결 내부회계관리제도 감사 또는 검토의견",
        ),
        SelectorEntry(
            "sep", "r", "d", "F001", "body", "감사보고서",
            "내부회계관리제도 감사 또는 검토의견",
        ),
    ]
    leaves = select_leaves(rows)
    assert leaves.icfr_entry_id == "sep"


def test_select_leaves_consolidated_prefers_consolidated_icfr() -> None:
    """연결 문서는 연결내부회계 leaf만 고른다."""
    rows = [
        SelectorEntry("c", "r", "d", "F002", "body", "연결감사보고서", "감사보고서"),
        SelectorEntry(
            "sep", "r", "d", "F002", "body", "연결감사보고서",
            "내부회계관리제도 검토의견",
        ),
        SelectorEntry(
            "con", "r", "d", "F002", "body", "연결감사보고서",
            "연결 내부회계관리제도 감사 또는 검토의견",
        ),
    ]
    leaves = select_leaves(rows)
    assert leaves.icfr_entry_id == "con"


def test_select_leaves_icfr_ignores_notes_and_other_dcm() -> None:
    """주석·다른 dcm의 내부회계는 고르지 않는다."""
    rows = [
        SelectorEntry("c", "r", "d1", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry(
            "n", "r", "d1", "F001", "body", "감사보고서", "내부회계관리제도 주석"
        ),
        SelectorEntry(
            "other", "r", "d2", "F001", "body", "감사보고서",
            "내부회계관리제도 검토의견",
        ),
    ]
    leaves = select_leaves(rows)
    assert leaves.icfr_entry_id is None
```

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_selector.py -q`  
Expected: FAIL (`LeafIds`에 `icfr_entry_id` 없음 또는 단언 실패)

- [ ] **Step 3: 최소 구현**

`LeafIds`에 `icfr_entry_id: str | None`을 추가한다. `select_leaves`에서 첫 감사 문서의 `fs_scope_for(report_type, document_name)`으로 범위를 정한다.

```python
def _is_notes_section(entry: SelectorEntry) -> bool:
    return compact(entry.section_name) == "주석"


def _is_icfr_section(entry: SelectorEntry, fs_scope: str) -> bool:
    """같은 dcm의 내부회계 leaf인지 본다. 주석은 제외한다."""
    token = compact(entry.section_name)
    if not token or "주석" in token:
        return False
    if "내부회계관리제도" not in token:
        return False
    if fs_scope == "consolidated":
        return "연결내부회계관리제도" in token
    return "연결" not in token


def select_leaves(entries: list[SelectorEntry]) -> LeafIds:
    audit_dcm_no = _first_audit_dcm_no(entries)
    audit_entries = (
        [entry for entry in entries if entry.dcm_no == audit_dcm_no]
        if audit_dcm_no is not None
        else []
    )
    sample = next(
        (
            entry
            for entry in audit_entries
            if is_audit_document(entry.report_type, entry.source, entry.document_name)
        ),
        None,
    )
    icfr_scope = (
        fs_scope_for(sample.report_type, sample.document_name)
        if sample is not None
        else "unknown"
    )
    # ... 기존 cover/opinion/activity/a001/bs/is/parent ...
    icfr_entry_id = next(
        (
            entry.entry_id
            for entry in audit_entries
            if _is_icfr_section(entry, icfr_scope)
        ),
        None,
    )
    return LeafIds(
        cover_entry_id=cover_entry_id,
        opinion_entry_id=opinion_entry_id,
        activity_entry_id=activity_entry_id,
        a001_opinion_entry_id=a001_opinion_entry_id,
        a001_cover_entry_id=a001_cover_entry_id,
        bs_entry_id=bs_entry_id,
        is_entry_id=is_entry_id,
        fs_parent_entry_id=fs_parent_entry_id,
        icfr_entry_id=icfr_entry_id,
    )
```

`is_audit_document`와 `_AUDIT_DOC_EXCLUDE_MARKERS`는 그대로 둔다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_selector.py -q`  
Expected: PASS

- [ ] **Step 5: Commit (요청 시에만)**

```bash
git add packages/web-api/app/extracting/selector.py packages/web-api/tests/test_extracting_selector.py
git commit -m "feat: 내부회계 leaf를 fs_scope에 맞춰 고른다"
```

---

### Task 2: `extract_icfr` 순수 파서

**Files:**
- Create: `app/extracting/icfr.py`
- Test: `tests/test_extracting_icfr.py`

**Interfaces:**
- Consumes: `compact` (`app/extracting/text.py`). BeautifulSoup `get_text`로 HTML→본문 (의견 잡 `_html_text`와 같음)
- Produces:

```python
@dataclass(frozen=True)
class IcfrResult:
    engagement: str | None  # audit / review / none / skipped일 때 None
    opinion_raw: str | None
    opinion_code: str | None
    status: str  # ok / skipped / not_found 는 서비스가 예외 시 씀. 파서는 skipped·ok


def extract_icfr(
    *,
    opinion_html: str | None,
    icfr_html: str | None,
    fs_scope: str,
) -> IcfrResult:
    ...
```

`icfr_html`이 없거나 빈 문자열이면 `status="skipped"`, 나머지 None.  
leaf는 있는데 서식 아니면 `engagement="none"`, `status="ok"`, code None.  
기본 적정 `raw="boilerplate_unqualified"`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_extracting_icfr.py`를 만든다.

```python
"""내부회계 감사·검토 의견 추출 테스트."""

from app.extracting.icfr import extract_icfr


def _html(*paragraphs: str) -> str:
    body = "".join(f"<p>{text}</p>" for text in paragraphs)
    return f"<html><body>{body}</body></html>"


def test_missing_leaf_is_skipped() -> None:
    """내부회계 HTML이 없으면 skipped이고 engagement를 채우지 않는다."""
    opinion = _html("우리는 또한 내부회계관리제도를 감사하였으며 적정의견을 표명하였습니다.")
    result = extract_icfr(opinion_html=opinion, icfr_html=None, fs_scope="separate")
    assert result.status == "skipped"
    assert result.engagement is None
    assert result.opinion_code is None


def test_placeholder_leaf_is_none() -> None:
    """leaf는 있으나 서식이 아니면 none이다."""
    result = extract_icfr(
        opinion_html=_html("재무제표 감사의견 적정"),
        icfr_html=_html("해당사항 없음"),
        fs_scope="separate",
    )
    assert result.status == "ok"
    assert result.engagement == "none"
    assert result.opinion_code is None


def test_fs_letter_separate_audit_phrase() -> None:
    """별도 의견서 추가 문단이면 감사이고, 제목 적정은 unqualified다."""
    opinion = _html(
        "우리는 또한 회계감사기준에 따라 내부회계관리제도를 감사하였으며 "
        "2024년 3월 6일자 감사보고서에서 적정의견을 표명하였습니다."
    )
    icfr = _html(
        "독립된 감사인의 내부회계관리제도 감사보고서",
        "내부회계관리제도에 대한 감사의견",
        "효과적으로 설계 및 운영되고 있습니다.",
    )
    result = extract_icfr(opinion_html=opinion, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "audit"
    assert result.opinion_code == "unqualified"
    assert result.opinion_raw == "내부회계관리제도에대한감사의견"
    assert result.status == "ok"


def test_consolidated_phrase_does_not_mark_separate_row() -> None:
    """연결…를감사하였은 별도 행을 audit으로 만들지 않는다."""
    opinion = _html("우리는 연결내부회계관리제도를 감사하였으며 적정의견을 표명하였습니다.")
    icfr = _html("해당사항 없음")
    result = extract_icfr(opinion_html=opinion, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "none"


def test_consolidated_fs_letter_and_heading() -> None:
    """연결 행은 연결 문단·연결 제목으로 audit unqualified다."""
    opinion = _html(
        "우리는 또한 회계감사기준에 따라 연결내부회계관리제도를 감사하였으며 "
        "적정의견을 표명하였습니다."
    )
    icfr = _html(
        "독립된 감사인의 연결내부회계관리제도 감사보고서",
        "연결내부회계관리제도에 대한 감사의견",
    )
    result = extract_icfr(opinion_html=opinion, icfr_html=icfr, fs_scope="consolidated")
    assert result.engagement == "audit"
    assert result.opinion_code == "unqualified"


def test_audit_adverse_heading_not_material_weakness() -> None:
    """부적정 제목이면 근거의 취약점 서술이 material_weakness가 되지 않는다."""
    icfr = _html(
        "내부회계관리제도에 대한 부적정의견",
        "중요한 취약점의 영향 때문에 효과적으로 설계 및 운영되고 있지 않습니다.",
        "내부회계관리제도 부적정의견근거",
        "다음의 중요한 취약점이 식별되었으며",
    )
    result = extract_icfr(opinion_html=None, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "audit"
    assert result.opinion_code == "adverse"
    assert result.opinion_raw == "내부회계관리제도에대한부적정의견"


def test_audit_disclaimer_heading() -> None:
    """의견거절 제목이면 disclaimer다."""
    icfr = _html(
        "내부회계관리제도에 대한 의견거절",
        "의견을 표명하지 않습니다.",
        "그러나 중요한 취약점이 식별되었습니다.",
    )
    result = extract_icfr(opinion_html=None, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "audit"
    assert result.opinion_code == "disclaimer"


def test_review_clean_not_material_weakness() -> None:
    """발견되지 아니하였은 취약점이 아니다."""
    icfr = _html(
        "외부감사인의 내부회계관리제도 검토보고서",
        "우리는 내부회계관리제도 검토기준에 따라 검토를 실시하였습니다.",
        "중요한 취약점이 발견되지 아니하였습니다.",
    )
    result = extract_icfr(opinion_html=None, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "review"
    assert result.opinion_code == "unqualified"
    assert result.opinion_raw == "boilerplate_unqualified"


def test_review_qualified() -> None:
    """미치는영향을제외하고는 한정이다."""
    icfr = _html(
        "외부감사인의 내부회계관리제도 검토보고서",
        "검토기준에 따라 검토를 실시하였습니다.",
        "절차를 수행하였을 경우 발견되었을 사항이 미치는 영향을 제외하고는 "
        "작성되지 않았다고 판단하게 하는 점이 발견되지 아니하였습니다.",
    )
    result = extract_icfr(opinion_html=None, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "review"
    assert result.opinion_code == "qualified"
    assert result.opinion_raw == "미치는영향을제외하고는"


def test_review_disclaimer() -> None:
    """검토의견을표명하지는 거절이다."""
    icfr = _html(
        "외부감사인의 내부회계관리제도 검토보고서",
        "검토의견을 표명하지 아니합니다.",
    )
    result = extract_icfr(opinion_html=None, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "review"
    assert result.opinion_code == "disclaimer"


def test_review_material_weakness() -> None:
    """중요한취약점이발견되었은 취약점이다."""
    icfr = _html(
        "외부감사인의 내부회계관리제도 검토보고서",
        "검토기준에 따라 검토를 실시하였습니다.",
        "다음과 같은 중요한 취약점이 발견되었습니다.",
    )
    result = extract_icfr(opinion_html=None, icfr_html=icfr, fs_scope="separate")
    assert result.engagement == "review"
    assert result.opinion_code == "material_weakness"
    assert result.opinion_raw == "중요한취약점이발견되었"
```

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_icfr.py -q`  
Expected: FAIL (`ModuleNotFoundError` 또는 import 오류)

- [ ] **Step 3: 최소 구현**

`app/extracting/icfr.py`:

```python
"""내부회계관리제도 감사·검토 의견 추출."""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.extracting.text import compact

_CONSOLIDATED_AUDIT_PHRASE = "연결내부회계관리제도를감사하였"
_SEPARATE_AUDIT_PHRASE = "내부회계관리제도를감사하였"
_REVIEW_REPORT = "내부회계관리제도검토보고서"
_REVIEW_STANDARD = "검토기준에따라검토"
_AUDIT_REPORT = "내부회계관리제도감사보고서"

_AUDIT_HEADINGS: tuple[tuple[str, str], ...] = (
    ("내부회계관리제도에대한의견거절", "disclaimer"),
    ("내부회계관리제도에대한부적정의견", "adverse"),
    ("내부회계관리제도에대한감사의견", "unqualified"),
)
_AUDIT_CUTS = (
    "내부회계관리제도감사의견근거",
    "내부회계관리제도부적정의견근거",
    "내부회계관리제도의견거절근거",
    "내부회계관리제도에대한경영진과지배기구의책임",
)
_AUDIT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("disclaimer", ("의견을표명하지", "의견거절근거")),
    ("adverse", ("효과적으로설계및운영되고있지", "부적정의견근거")),
)
_REVIEW_CUT = "내부회계관리제도에대한경영진과지배기구의책임"
_REVIEW_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("disclaimer", ("검토의견을표명하지",)),
    ("qualified", ("미치는영향을제외하고는",)),
    ("material_weakness", ("중요한취약점이발견되었", "중요한취약점이언급")),
)


@dataclass(frozen=True)
class IcfrResult:
    """내부회계 leaf 한 장의 판별·의견."""

    engagement: str | None
    opinion_raw: str | None
    opinion_code: str | None
    status: str


def _compact_html(html: str | None) -> str:
    if not html:
        return ""
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    return compact(text)


def _before_markers(compacted: str, markers: tuple[str, ...]) -> str:
    cuts = [compacted.find(marker) for marker in markers]
    hits = [index for index in cuts if index >= 0]
    if not hits:
        return compacted
    return compacted[: min(hits)]


def _first_keyword(
    compacted: str, groups: tuple[tuple[str, tuple[str, ...]], ...]
) -> tuple[str, str] | None:
    for code, keywords in groups:
        for keyword in keywords:
            if keyword in compacted:
                return keyword, code
    return None


def _classify_engagement(
    opinion_compact: str, icfr_compact: str, fs_scope: str
) -> str:
    """스펙 §6 순서. leaf가 있을 때만 호출한다."""
    if fs_scope == "consolidated":
        if _CONSOLIDATED_AUDIT_PHRASE in opinion_compact:
            return "audit"
    elif (
        _SEPARATE_AUDIT_PHRASE in opinion_compact
        and _CONSOLIDATED_AUDIT_PHRASE not in opinion_compact
    ):
        return "audit"
    if _REVIEW_REPORT in icfr_compact or _REVIEW_STANDARD in icfr_compact:
        return "review"
    if _AUDIT_REPORT in icfr_compact or _SEPARATE_AUDIT_PHRASE in icfr_compact:
        return "audit"
    return "none"


def _classify_audit(icfr_compact: str) -> tuple[str, str]:
    for heading, code in _AUDIT_HEADINGS:
        if heading in icfr_compact:
            return heading, code
    window = _before_markers(icfr_compact, _AUDIT_CUTS)
    hit = _first_keyword(window, _AUDIT_KEYWORDS)
    if hit is not None:
        return hit
    return "boilerplate_unqualified", "unqualified"


def _classify_review(icfr_compact: str) -> tuple[str, str]:
    start = icfr_compact.find(_REVIEW_CUT)
    window = icfr_compact if start < 0 else icfr_compact[:start]
    hit = _first_keyword(window, _REVIEW_KEYWORDS)
    if hit is not None:
        return hit
    return "boilerplate_unqualified", "unqualified"


def extract_icfr(
    *,
    opinion_html: str | None,
    icfr_html: str | None,
    fs_scope: str,
) -> IcfrResult:
    """내부회계 leaf와 재무제표 의견서 HTML에서 engagement·의견 코드를 뽑는다."""
    if not icfr_html:
        return IcfrResult(None, None, None, "skipped")
    icfr_compact = _compact_html(icfr_html)
    opinion_compact = _compact_html(opinion_html)
    engagement = _classify_engagement(opinion_compact, icfr_compact, fs_scope)
    if engagement == "none":
        return IcfrResult("none", None, None, "ok")
    if engagement == "audit":
        raw, code = _classify_audit(icfr_compact)
    else:
        raw, code = _classify_review(icfr_compact)
    return IcfrResult(engagement, raw, code, "ok")
```

`unknown` fs_scope는 `consolidated`가 아니므로 별도 분기를 탄다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_icfr.py -q`  
Expected: PASS

- [ ] **Step 5: Commit (요청 시에만)**

```bash
git add packages/web-api/app/extracting/icfr.py packages/web-api/tests/test_extracting_icfr.py
git commit -m "feat: 내부회계 감사·검토 의견을 leaf에서 분류한다"
```

---

### Task 3: 컬럼·스키마·버전 v14

**Files:**
- Modify: `app/extracting/constants.py`
- Modify: `app/models/audit_report_fact.py`
- Modify: `app/db/session.py` (`_COLUMN_PATCHES`)
- Modify: `tests/test_audit_report_fact_repository.py` (`SPEC_FACT_COLUMNS`, `_make_fact`, 버전 단언)
- Modify: `tests/test_ensure_schema.py`
- Modify: `tests/test_extraction_service.py` (버전 문자열 `audit_opinion.v13` → `v14`)

**Interfaces:**
- Consumes: Task 2 `IcfrResult` 필드명
- Produces: `AuditReportFact.icfr_entry_id`, `icfr_engagement`, `icfr_opinion_raw`, `icfr_opinion_code`, `icfr_status`. `EXTRACTOR_VERSION = "audit_opinion.v14"`

- [ ] **Step 1: 실패하는 테스트 작성**

`SPEC_FACT_COLUMNS` 튜플 끝에 다섯 컬럼을 추가한다. `test_extractor_version_constant`가 `"audit_opinion.v14"`를 기대하게 바꾼다. `_make_fact` 기본값에 `icfr_status: "skipped"`를 넣는다.

`tests/test_ensure_schema.py`의 `test_ensure_schema_adds_hours_to_legacy_audit_report_facts`에:

```python
assert "icfr_entry_id" in columns
assert "icfr_engagement" in columns
assert "icfr_opinion_raw" in columns
assert "icfr_opinion_code" in columns
assert "icfr_status" in columns
```

`tests/test_extraction_service.py`에서 리터럴 `"audit_opinion.v13"`을 `"audit_opinion.v14"`로 바꾼다 (단언·시드). 이 시점엔 서비스가 아직 v13이면 단언이 실패한다 — 상수만 먼저 올리고 서비스 테스트 버전 문자열은 이 태스크에서 함께 맞춘다.

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_audit_report_fact_repository.py tests/test_ensure_schema.py -q`  
Expected: FAIL (컬럼 목록 또는 pragma에 icfr 없음)

- [ ] **Step 3: 최소 구현**

`constants.py`: `EXTRACTOR_VERSION = "audit_opinion.v14"`

`audit_report_fact.py` `accounts_status` 다음에:

```python
    icfr_entry_id: Mapped[str | None] = mapped_column(String(128))
    icfr_engagement: Mapped[str | None] = mapped_column(String(16))
    icfr_opinion_raw: Mapped[str | None] = mapped_column(Text)
    icfr_opinion_code: Mapped[str | None] = mapped_column(String(32))
    icfr_status: Mapped[str | None] = mapped_column(String(32))
```

`session.py` `_COLUMN_PATCHES`에 다섯 튜플을 추가한다. SQLite/Postgres DDL:

- `icfr_entry_id`: `VARCHAR(128)`
- `icfr_engagement`: `VARCHAR(16)`
- `icfr_opinion_raw`: `TEXT`
- `icfr_opinion_code`: `VARCHAR(32)`
- `icfr_status`: `VARCHAR(32)`

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_audit_report_fact_repository.py tests/test_ensure_schema.py -q`  
Expected: PASS

extraction_service 테스트는 Task 4 전까지 버전 단언만 맞춰 두고, ICFR 필드 단언은 Task 4에서 추가한다. Task 3에서 버전 리터럴을 v14로 바꾸면 `EXTRACTOR_VERSION`과 같아져 기존 추출 테스트는 상수만 맞으면 통과한다.

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py -q`  
Expected: PASS (아직 icfr 컬럼은 ORM 기본 None, 기존 단언은 건드리지 않음)

- [ ] **Step 5: Commit (요청 시에만)**

```bash
git add packages/web-api/app/extracting/constants.py packages/web-api/app/models/audit_report_fact.py packages/web-api/app/db/session.py packages/web-api/tests/test_audit_report_fact_repository.py packages/web-api/tests/test_ensure_schema.py packages/web-api/tests/test_extraction_service.py
git commit -m "feat: audit_report_facts에 내부회계 컬럼과 v14를 둔다"
```

---

### Task 4: 추출 잡에 fetch·파서 연결

**Files:**
- Modify: `app/services/extraction_service.py`
- Test: `tests/test_extraction_service.py`

**Interfaces:**
- Consumes: `LeafIds.icfr_entry_id`, `extract_icfr`, `fs_scope_for` (fact.fs_scope와 동일하게 `_build_fact`에서 계산한 값)
- Produces: fact 행의 icfr 컬럼. `_LEAF_ROLES`에 `"icfr_entry_id"` (필수 아님). `_NOT_FOUND_STATUSES`에 `"icfr_status"`

규칙:

- leaf id 없음 → 파서 호출 없이 skipped, 나머지 icfr 필드 None
- leaf id는 있는데 HTML이 없음(fetch 실패) → `icfr_status="not_found"`, 나머지 None
- HTML이 있으면 `extract_icfr(opinion_html=..., icfr_html=..., fs_scope=...)`
- 파서 예외 → `not_found` (`_safe_activity_parse`와 같은 try/except)

- [ ] **Step 1: 실패하는 테스트 작성**

기존 F001 추출 성공 테스트(`test_extract_persists_unqualified_letter` 또는 동등한 첫 성공 테스트)에 내부회계 섹션이 없으면:

```python
assert fact.icfr_status == "skipped"
assert fact.icfr_entry_id is None
assert fact.icfr_engagement is None
```

새 테스트: 카탈로그에 `내부회계관리제도 검토의견` leaf와 그 HTML을 넣고, 검토 표준보고 fixture를 fetch하게 한다. `icfr_status=="ok"`, `icfr_engagement=="review"`, `icfr_opinion_code=="unqualified"`.

새 테스트: `icfr_status="not_found"`로 시드한 뒤 `reparse`하면 ICFR URL을 다시 가져온다 (`test_reparse_refetches_when_accounts_status_is_not_found` 복사, `icfr_status`만 바꾼다).

기존 테스트의 목 HTML 맵에 섹션명이 있으면 `_LEAF_ROLES` 순회가 `icfr_entry_id`를 fetch하므로, 셀렉터가 고르는 섹션을 넣지 않으면 skipped가 된다.

파서 예외 테스트: `extract_icfr`를 패치해 `RuntimeError`를 내고 `icfr_status=="not_found"`이며 `job.status=="succeeded"`.

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py -q`  
Expected: FAIL (icfr 필드 미설정 또는 reparse가 icfr_status를 안 봄)

- [ ] **Step 3: 최소 구현**

`extraction_service.py`:

```python
from app.extracting.icfr import extract_icfr
```

`_NOT_FOUND_STATUSES`에 `"icfr_status"`. `_LEAF_ROLES` 튜플 끝에 `"icfr_entry_id"`.

`_build_fact`에서 accounts 처리 다음, `document_name`/`fs_scope`를 쓰기 **전**에 scope를 먼저 계산하거나, `AuditReportFact(...)`에 넣기 직전에:

```python
        icfr_html = html_by_role.get("icfr_entry_id")
        opinion_html_for_icfr = html_by_role.get("opinion_entry_id")
        if not leaves.icfr_entry_id:
            icfr = None
            icfr_status = "skipped"
        elif icfr_html is None:
            icfr = None
            icfr_status = "not_found"
        else:
            try:
                icfr = extract_icfr(
                    opinion_html=opinion_html_for_icfr,
                    icfr_html=icfr_html,
                    fs_scope=fs_scope_for(sample.report_type or "", document_name),
                )
                icfr_status = icfr.status
            except Exception:
                logger.exception("내부회계 의견 파싱에 실패했습니다.")
                icfr = None
                icfr_status = "not_found"
```

`document_name`은 기존처럼 A001 cover 보정 **이후** 값을 `fs_scope_for`에 넘긴다. 위 블록은 `document_name` 보정 뒤로 둔다.

`AuditReportFact(...)`에:

```python
            icfr_entry_id=leaves.icfr_entry_id,
            icfr_engagement=None if icfr is None else icfr.engagement,
            icfr_opinion_raw=None if icfr is None else icfr.opinion_raw,
            icfr_opinion_code=None if icfr is None else icfr.opinion_code,
            icfr_status=icfr_status,
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py tests/test_extracting_icfr.py tests/test_extracting_selector.py -q`  
Expected: PASS

- [ ] **Step 5: Commit (요청 시에만)**

```bash
git add packages/web-api/app/services/extraction_service.py packages/web-api/tests/test_extraction_service.py
git commit -m "feat: 감사 의견 잡에서 내부회계 leaf를 가져와 저장한다"
```

---

### Task 5: 완전성·Public API·README

**Files:**
- Modify: `app/services/completeness_service.py`
- Modify: `app/schemas/facts.py`
- Modify: `packages/web-api/README.md`
- Test: `tests/test_extract_admin_api.py`, `tests/test_facts_api.py`

**Interfaces:**
- Consumes: `icfr_status` 컬럼
- Produces: `field_partial`이 `icfr_status != "ok"`를 포함. Public `AuditReportFactItem`에 icfr 네 필드(+ raw)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_extract_admin_api.py` `_ok_fact` 기본값에 `"icfr_status": "ok"`를 넣는다 (넣지 않으면 기존 `field_partial==0` 테스트가 깨진다).

추가:

```python
async def test_completeness_field_partial_includes_icfr_skipped(
    client_factory, memory_app: tuple[FastAPI, object]
) -> None:
    """다른 필드가 ok여도 icfr_status=skipped면 field_partial이다."""
    app, sessionmaker = memory_app
    await _seed(sessionmaker, [_entry()], [_ok_fact(icfr_status="skipped")])
    # ... 기존 accounts_skipped 테스트와 같은 GET ...
    assert body["field_partial"] == 1
```

`tests/test_facts_api.py` `_fact`에 `icfr_engagement="review"`, `icfr_opinion_code="unqualified"`, `icfr_status="ok"`를 넣고 응답 단언:

```python
    assert row["icfr_status"] == "ok"
    assert row["icfr_engagement"] == "review"
    assert row["icfr_opinion_code"] == "unqualified"
```

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_api.py tests/test_facts_api.py -q`  
Expected: FAIL (`field_partial`이 icfr를 안 세거나 스키마에 필드 없음)

- [ ] **Step 3: 최소 구현**

`completeness_service.py` `_FIELD_STATUS_ATTRS`에 `"icfr_status"`를 추가한다.

`facts.py` `accounts_status` 다음:

```python
    icfr_entry_id: str | None = None
    icfr_engagement: str | None = None
    icfr_opinion_raw: str | None = None
    icfr_opinion_code: str | None = None
    icfr_status: str | None = None
```

`README.md`: Extracting 줄과 추출기 버전을 `audit_opinion.v14`로. 감사보고서 추출 절에 내부회계 한 줄:

같은 행에 내부회계관리제도 감사·검토 의견(`icfr_engagement`, `icfr_opinion_code`, `icfr_status`)을 붙입니다. 감사는 적정·부적정·거절, 검토는 거기에 한정·중요한취약점입니다. 회사 운영보고서는 읽지 않습니다.

`field_partial` 설명에 `icfr_status`를 포함한다. Public 조회 줄에 icfr 필드를 언급한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extract_admin_api.py tests/test_facts_api.py tests/test_export_audit_report_facts.py tests/test_extracting_icfr.py tests/test_extracting_selector.py tests/test_extraction_service.py tests/test_audit_report_fact_repository.py tests/test_ensure_schema.py -q`  
Expected: PASS

- [ ] **Step 5: Commit (요청 시에만)**

```bash
git add packages/web-api/app/services/completeness_service.py packages/web-api/app/schemas/facts.py packages/web-api/README.md packages/web-api/tests/test_extract_admin_api.py packages/web-api/tests/test_facts_api.py
git commit -m "feat: 내부회계 의견을 API와 완전성 집계에 노출한다"
```

---

## Spec coverage

| 스펙 | 태스크 |
|------|--------|
| §5 selector, 운영보고서 제외 유지 | 1 |
| §6 engagement 순서, 연결 부분문자열 | 2 |
| §7.1 감사 제목·키워드·취약점≠코드 | 2 |
| §7.2 검토 거절·한정·취약점, 발견되지 | 2 |
| §7.3 skipped / none / not_found | 2, 4 |
| §4 컬럼, v14, ensure_schema | 3 |
| §3·§8 같은 잡, fetch, reparse | 4 |
| §8 Public·CSV·field_partial | 5 |
| §9 회귀·운영보고서 False | 1 (`is_audit_document` 기존 테스트), 5 |
| §10 밖 | 전역 제약 |
