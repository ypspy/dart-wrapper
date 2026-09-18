# 감사보고서일 전수 후보·인증일 일치 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 의견 본문의 날짜를 구간 자르기 없이 모두 후보로 모으고, `rcept_no` 앞 8자리(인증일)와 같은 날만 규칙으로 확정하며, 나머지는 운영자가 `limit` 있는 해소 잡을 누를 때만 LLM이 고르게 한다.

**Architecture:** `_preprocess`를 없애고 compact 전체에서 여러 날짜 패턴을 찾는다. `pick_audit_report_date`는 창 안 개수가 아니라 인증일 일치만 본다. LLM 저장 전 창 검증은 `date_in_auth_window`로 분리한다(pick을 재쓰면 LLM도 인증일만 통과한다). 해소 잡은 기존 POST이며 `limit`과 인증일만 바꾼다.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, pytest, httpx mock(기존 LLM 테스트).

## Global Constraints

- 패키지: `packages/web-api`만.
- 주석·Docstring·로그·사용자 메시지는 한국어.
- 테스트: `packages/web-api`에서 `.\.venv\Scripts\python.exe -m pytest <파일> -q --tb=short`. Windows에서 pytest가 통과 후 hang하면 해당 파일 테스트가 모두 통과한 뒤 hang으로 본다.
- KSIC/OpenDART 워킹 트리 변경은 커밋에 넣지 않음.
- 한자 숫자 변환, `not_found`를 해소 잡에 넣기, 본문을 LLM에 첨부하기, 새 ISO 생성, 후반·머리글 우선, `rcept_dt`로 일치, 날짜 전용 reparse, Admin 해소 UI 없음.
- live DART·live OpenAI 호출 없음.
- [스펙](../specs/2026-09-18-audit-report-date-all-candidates-auth-match-design.md). 머리글 전처리 스펙·계획은 구현하지 않음.

## File map

| 파일 | 책임 |
|------|------|
| `packages/web-api/app/extracting/dates.py` | 전수 후보, `parse_auth_date`, `pick`(인증일), `date_in_auth_window` |
| `packages/web-api/tests/test_extracting_dates.py` | 후보·변칙 형식·인증일 선택 |
| `packages/web-api/app/extracting/constants.py` | `audit_opinion.v18` |
| `packages/web-api/app/services/extraction_service.py` | pick에 `parse_auth_date(rcept_no)` |
| `packages/web-api/tests/test_extraction_service.py` | 의견 HTML 날짜를 인증일과 맞춤, 버전 문자열 |
| `packages/web-api/tests/test_audit_report_fact_repository.py` | 버전 문자열 |
| `packages/web-api/app/ports/date_resolver.py` | `auth_date` 인자 |
| `packages/web-api/app/adapters/llm_date_resolver.py` | 프롬프트·payload `auth_date` |
| `packages/web-api/app/services/date_resolver_service.py` | `limit`, 인증일 창 |
| `packages/web-api/app/schemas/extract.py` | `ResolveDatesRequest.limit` |
| `packages/web-api/app/api/admin/extract.py` | POST body `limit` |
| `packages/web-api/tests/test_date_resolver.py` | `limit`·`auth_date` |
| `packages/web-api/README.md` | 해소 잡 `limit`·인증일 |

---

### Task 1: 전수 후보와 인증일 선택

**Files:**
- Modify: `packages/web-api/tests/test_extracting_dates.py`
- Modify: `packages/web-api/app/extracting/dates.py`

**Interfaces:**
- Consumes: `compact(text: str | None) -> str`
- Produces:
  - `extract_date_candidates(text: str) -> list[DateCandidate]`
  - `parse_auth_date(rcept_no: str | None) -> date | None`
  - `date_in_auth_window(iso: date, *, period_end: date | None, auth_date: date | None) -> bool`
  - `pick_audit_report_date(candidates, *, period_end: date | None, auth_date: date | None) -> tuple[str | None, str, list[DateCandidate]]`
  - `parse_rcept_dt` / `parse_year_end` 시그니처 불변 (ICFR 연도 등)

- [ ] **Step 1: Write the failing tests**

`packages/web-api/tests/test_extracting_dates.py`를 아래 내용으로 **교체**한다. `rcept_dt=` 키워드를 pick에 쓰지 않는다.

```python
"""감사보고서일 후보 추출·인증일 선택 테스트."""

from datetime import date

from app.extracting.dates import (
    date_in_auth_window,
    extract_date_candidates,
    parse_auth_date,
    parse_rcept_dt,
    parse_year_end,
    pick_audit_report_date,
)


def test_keeps_dates_between_opinion_grounds_and_fs_section() -> None:
    """구간 전처리가 없어 중간 날짜도 후보다."""
    text = (
        "머리 2018년12월31일 의견근거 중간날짜 2019년1월10일 "
        "재무제표에대한경 서명 2019년3월15일"
    )
    candidates = extract_date_candidates(text)
    assert [c.iso for c in candidates] == [
        "2018-12-31",
        "2019-01-10",
        "2019-03-15",
    ]


def test_ok_only_when_candidate_equals_auth_date() -> None:
    """인증일과 같은 ISO만 ok다. 창 안 다른 날짜가 하나여도 고르지 않는다."""
    text = (
        "우리는 2018년12월31일로 종료되는 회계연도를 감사하였습니다. "
        "감사의견 적정. 의견근거 중간설명 "
        "재무제표에대한경영진의책임. 2019년3월15일"
    )
    candidates = extract_date_candidates(text)
    iso, status, passing = pick_audit_report_date(
        candidates,
        period_end=date(2018, 12, 31),
        auth_date=date(2019, 3, 15),
    )
    assert status == "ok"
    assert iso == "2019-03-15"
    assert [c.iso for c in passing] == ["2019-03-15"]

    iso, status, _passing = pick_audit_report_date(
        candidates,
        period_end=date(2018, 12, 31),
        auth_date=date(2019, 3, 31),
    )
    assert status == "ambiguous"
    assert iso is None


def test_not_found_when_no_dates() -> None:
    """날짜 패턴이 없으면 not_found이다."""
    candidates = extract_date_candidates("의견근거 본문 재무제표에대한경영진의책임")
    assert candidates == []
    iso, status, passing = pick_audit_report_date(
        candidates,
        period_end=date(2018, 12, 31),
        auth_date=date(2019, 3, 31),
    )
    assert status == "not_found"
    assert iso is None
    assert passing == []


def test_ambiguous_when_auth_date_missing() -> None:
    """후보가 있는데 인증일을 못 읽으면 ambiguous다."""
    candidates = extract_date_candidates("서명 2019년3월15일")
    iso, status, _passing = pick_audit_report_date(
        candidates,
        period_end=date(2018, 12, 31),
        auth_date=None,
    )
    assert status == "ambiguous"
    assert iso is None


def test_variant_date_formats_become_iso() -> None:
    """점·대시·슬래시·年月日·전각이 ISO가 된다."""
    cases = [
        "머리 2016.01.22 끝",
        "머리 2016-01-22 끝",
        "머리 2016/1/22 끝",
        "머리 2016年1月22日 끝",
        "머리 ２０１６년１월２２일 끝",
        "머리 2016년 1월 22일 끝",
    ]
    for text in cases:
        candidates = extract_date_candidates(text)
        assert [c.iso for c in candidates] == ["2016-01-22"], text


def test_skips_invalid_calendar_and_hanja_numerals() -> None:
    """달력에 없는 날과 한자 숫자는 후보가 아니다."""
    assert extract_date_candidates("2016년13월1일 이십년") == []
    assert extract_date_candidates("二〇一六年一月二十二일") == []


def test_zero_pads_iso_and_reads_compact_dates() -> None:
    """공백을 제거한 뒤 매칭하고 ISO는 zero-pad한다."""
    candidates = extract_date_candidates("머리 2019년 3월 5일")
    assert len(candidates) == 1
    assert candidates[0].date_raw == "2019년3월5일"
    assert candidates[0].iso == "2019-03-05"


def test_snippet_uses_original_text_around_match() -> None:
    """snippet은 원문 매칭 전후 40자를 쓴다."""
    prefix = "가" * 10
    suffix = "나" * 10
    text = f"{prefix}2019년3월15일{suffix}"
    candidates = extract_date_candidates(text)
    assert len(candidates) == 1
    assert candidates[0].snippet == text


def test_snippet_is_capped_at_forty_chars_each_side() -> None:
    """매칭 앞뒤가 길면 snippet은 각각 40자만 남긴다."""
    prefix = "가" * 50
    suffix = "나" * 50
    text = f"{prefix}2019년3월15일{suffix}"
    candidates = extract_date_candidates(text)
    assert len(candidates) == 1
    assert candidates[0].snippet == ("가" * 40) + "2019년3월15일" + ("나" * 40)


def test_trailing_header_is_candidate() -> None:
    """후행형 머리글 날짜가 후보다. 인증일이 다르면 ambiguous다."""
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
        auth_date=date(2015, 12, 24),
    )
    assert status == "ok"
    assert iso == "2015-12-24"
    assert [c.iso for c in passing] == ["2015-12-24"]

    iso, status, _passing = pick_audit_report_date(
        candidates,
        period_end=date(2015, 10, 31),
        auth_date=date(2016, 1, 13),
    )
    assert status == "ambiguous"
    assert iso is None


def test_parse_auth_date_from_rcept_no() -> None:
    """접수번호 앞 8자리가 인증일이다."""
    assert parse_auth_date("20160122000020") == date(2016, 1, 22)
    assert parse_auth_date("20160230xxxxxx") is None
    assert parse_auth_date("short") is None
    assert parse_auth_date(None) is None


def test_date_in_auth_window() -> None:
    """LLM 저장 전 창은 결산 초과·인증일 이하다."""
    assert date_in_auth_window(
        date(2019, 3, 15),
        period_end=date(2018, 12, 31),
        auth_date=date(2019, 3, 31),
    )
    assert date_in_auth_window(
        date(2019, 3, 31),
        period_end=date(2018, 12, 31),
        auth_date=date(2019, 3, 31),
    )
    assert not date_in_auth_window(
        date(2018, 12, 31),
        period_end=date(2018, 12, 31),
        auth_date=date(2019, 3, 31),
    )
    assert not date_in_auth_window(
        date(2019, 4, 1),
        period_end=date(2018, 12, 31),
        auth_date=date(2019, 3, 31),
    )


def test_parse_year_end_and_rcept_dt() -> None:
    """year_end·접수일 문자열을 date로 파싱한다."""
    assert parse_year_end("(2019.12)") == date(2019, 12, 31)
    assert parse_year_end(None) is None
    assert parse_rcept_dt("2019.03.31") == date(2019, 3, 31)
    assert parse_rcept_dt("2019-03-31") == date(2019, 3, 31)
    assert parse_rcept_dt(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_dates.py -q --tb=short`  
(cwd: `packages/web-api`)  
Expected: FAIL (`auth_date` unexpected, 중간 날짜 제외, `parse_auth_date` 없음)

- [ ] **Step 3: Write minimal implementation**

`packages/web-api/app/extracting/dates.py`를 아래와 같이 바꾼다. `_preprocess`·`_OPINION_GROUNDS`·`_FS_SECTION`를 삭제한다. `parse_rcept_dt`는 남긴다.

```python
"""감사보고서일 후보 추출과 인증일 선택."""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

from app.extracting.text import compact

_DATE_PATTERN = re.compile(
    r"(?P<ymd>[0-9]{4}년[0-9]{1,2}월[0-9]{1,2}일)"
    r"|(?P<cjk>[0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)"
    r"|(?P<dot>[0-9]{4}[.][0-9]{1,2}[.][0-9]{1,2})"
    r"|(?P<dash>[0-9]{4}[-][0-9]{1,2}[-][0-9]{1,2})"
    r"|(?P<slash>[0-9]{4}[/][0-9]{1,2}[/][0-9]{1,2})"
)
_YEAR_END_PATTERN = re.compile(r"(\d{4})\.(\d{1,2})")
_SNIPPET_RADIUS = 40


@dataclass(frozen=True)
class DateCandidate:
    """감사보고서일 후보(원문, ISO, 주변 문장, 등장 순번)."""

    date_raw: str
    iso: str
    snippet: str
    index: int


def extract_date_candidates(text: str) -> list[DateCandidate]:
    """NFKC·compact 본문에서 날짜 후보를 모두 찾는다."""
    normalized = unicodedata.normalize("NFKC", text)
    scanned = compact(normalized)
    candidates: list[DateCandidate] = []
    original_from = 0
    for index, match in enumerate(_DATE_PATTERN.finditer(scanned)):
        date_raw = match.group(0)
        iso = _raw_to_iso(date_raw)
        if iso is None:
            continue
        found_at = text.find(date_raw, original_from)
        if found_at < 0:
            found_at = normalized.find(date_raw, original_from)
            snippet_src = normalized if found_at >= 0 else scanned
            snippet_at = found_at if found_at >= 0 else match.start()
            snippet = _slice_around(snippet_src, snippet_at, len(date_raw))
            if found_at >= 0:
                original_from = found_at + 1
        else:
            snippet = _slice_around(text, found_at, len(date_raw))
            original_from = found_at + 1
        candidates.append(
            DateCandidate(
                date_raw=date_raw,
                iso=iso,
                snippet=snippet,
                index=len(candidates),
            )
        )
    return candidates


def pick_audit_report_date(
    candidates: Sequence[DateCandidate],
    *,
    period_end: date | None,
    auth_date: date | None,
) -> tuple[str | None, str, list[DateCandidate]]:
    """인증일과 같은 후보 ISO만 보고일로 고른다.

    후보 0 → not_found. 인증일 없음·결산 이후가 아님·불일치 → ambiguous.
    창 안 개수로 ok를 만들지 않는다.
    """
    if not candidates:
        return None, "not_found", []
    if auth_date is None:
        return None, "ambiguous", []
    if period_end is not None and not (period_end < auth_date):
        return None, "ambiguous", []
    target = auth_date.isoformat()
    matching = [item for item in candidates if item.iso == target]
    if not matching:
        return None, "ambiguous", []
    unique: dict[str, DateCandidate] = {}
    for item in matching:
        unique.setdefault(item.iso, item)
    passing = list(unique.values())
    return passing[0].iso, "ok", passing


def date_in_auth_window(
    iso: date,
    *,
    period_end: date | None,
    auth_date: date | None,
) -> bool:
    """period_end < iso ≤ auth_date. 한쪽 None이면 그 비교는 생략한다."""
    if period_end is not None and not (period_end < iso):
        return False
    if auth_date is not None and not (iso <= auth_date):
        return False
    return True


def parse_auth_date(rcept_no: str | None) -> date | None:
    """접수번호 앞 8자리 YYYYMMDD를 인증일로 읽는다."""
    if not rcept_no or len(rcept_no) < 8:
        return None
    raw = rcept_no[:8]
    if not raw.isdigit():
        return None
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError:
        return None


def parse_year_end(year_end: str | None) -> date | None:
    """목록 year_end 문자열(예: (2019.12))을 해당 월 말일로 변환한다."""
    if not year_end:
        return None
    match = _YEAR_END_PATTERN.search(year_end)
    if match is None:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    try:
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, last_day)
    except ValueError:
        return None


def parse_rcept_dt(rcept_dt: str | None) -> date | None:
    """접수일 문자열(2019.03.31 또는 2019-03-31)을 date로 변환한다."""
    if not rcept_dt:
        return None
    value = rcept_dt.strip()
    for fmt in ("%Y.%m.%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _raw_to_iso(date_raw: str) -> str | None:
    """매칭 원문을 ISO로 바꾼다. 달력이 아니면 None."""
    if "년" in date_raw:
        year_s, rest = date_raw.split("년", 1)
        month_s, rest = rest.split("월", 1)
        day_s = rest.removesuffix("일")
    elif "年" in date_raw:
        year_s, rest = date_raw.split("年", 1)
        month_s, rest = rest.split("月", 1)
        day_s = rest.removesuffix("日")
    elif "." in date_raw:
        year_s, month_s, day_s = date_raw.split(".")
    elif "-" in date_raw:
        year_s, month_s, day_s = date_raw.split("-")
    elif "/" in date_raw:
        year_s, month_s, day_s = date_raw.split("/")
    else:
        return None
    try:
        parsed = date(int(year_s), int(month_s), int(day_s))
    except ValueError:
        return None
    return parsed.isoformat()


def _slice_around(source: str, start: int, length: int) -> str:
    left = max(0, start - _SNIPPET_RADIUS)
    right = min(len(source), start + length + _SNIPPET_RADIUS)
    return source[left:right]
```

이 커밋 전에 `extraction_service.py`의 `rcept_dt=`는 아직 있어 import 오류가 날 수 있다. Task 1 커밋 범위는 dates 테스트만 돌린다.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_dates.py -q --tb=short`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/tests/test_extracting_dates.py packages/web-api/app/extracting/dates.py
git commit -m "feat(web-api): 감사보고서일 후보를 전수 수집하고 인증일과 맞춘다"
```

---

### Task 2: 추출 잡에 인증일과 v18 연결

**Files:**
- Modify: `packages/web-api/app/extracting/constants.py`
- Modify: `packages/web-api/app/services/extraction_service.py` (import와 `_build_fact` pick 호출)
- Modify: `packages/web-api/tests/test_extraction_service.py` (의견 HTML 날짜, `v17` 문자열)
- Modify: `packages/web-api/tests/test_audit_report_fact_repository.py` (`v17` 단언)

**Interfaces:**
- Consumes: `parse_auth_date`, `pick_audit_report_date(..., auth_date=)`
- Produces: `EXTRACTOR_VERSION == "audit_opinion.v18"`

- [ ] **Step 1: Write the failing tests**

1. `packages/web-api/tests/test_audit_report_fact_repository.py`의 `assert EXTRACTOR_VERSION == "audit_opinion.v17"`를 `"audit_opinion.v18"`로 바꾼다.
2. `packages/web-api/tests/test_extraction_service.py`에서 `audit_opinion.v17` 단언 두 곳을 `v18`로 바꾼다.
3. 같은 파일 의견 fixture HTML의 `2020년 2월 20일`을 `2020년 3월 31일`로 바꾼다. `rcept_no`는 `20200331000001`이라 인증일과 같아야 `letter`/`ok`가 된다.

```html
<p>2020년 3월 31일</p>
```

(COVER/OPINION 두 곳 모두 의견 본문 날짜가 있는 `<p>`를 맞춘다.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_audit_report_fact_repository.py tests/test_extraction_service.py -q --tb=line`  
Expected: FAIL (버전 문자열, 그리고 `pick_audit_report_date`에 `rcept_dt` 전달 TypeError 가능)

- [ ] **Step 3: Write minimal implementation**

`packages/web-api/app/extracting/constants.py`:

```python
EXTRACTOR_VERSION = "audit_opinion.v18"
```

`extraction_service.py` import에서 `parse_rcept_dt`를 `parse_auth_date`로 바꾸고(다른 곳에서 `parse_rcept_dt`를 안 쓰면), pick 호출을 다음으로 바꾼다.

```python
date_iso, date_status, _passing = pick_audit_report_date(
    date_candidates,
    period_end=parse_year_end(sample.year_end),
    auth_date=parse_auth_date(sample.rcept_no),
)
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_dates.py tests/test_audit_report_fact_repository.py tests/test_extraction_service.py tests/test_extract_admin_api.py tests/test_extract_admin_ui.py tests/test_field_bundles.py -q --tb=line`  
Expected: PASS. `v17` 하드코딩이 남은 테스트가 있으면 같은 커밋에서 `EXTRACTOR_VERSION` 상수 비교로 맞춘다.

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/extracting/constants.py packages/web-api/app/services/extraction_service.py packages/web-api/tests/test_extraction_service.py packages/web-api/tests/test_audit_report_fact_repository.py
git commit -m "feat(web-api): 추출기에 인증일 선택과 v18을 연결한다"
```

버전 픽스처를 고친 다른 테스트 파일이 있으면 같은 커밋에 넣는다.

---

### Task 3: 해소 잡 한도와 인증일 창

**Files:**
- Modify: `packages/web-api/app/ports/date_resolver.py`
- Modify: `packages/web-api/app/adapters/llm_date_resolver.py`
- Modify: `packages/web-api/app/services/date_resolver_service.py`
- Modify: `packages/web-api/app/schemas/extract.py`
- Modify: `packages/web-api/app/api/admin/extract.py`
- Modify: `packages/web-api/tests/test_date_resolver.py`
- Modify: `packages/web-api/README.md` (`DATE_RESOLVER` 절)

**Interfaces:**
- Consumes: `parse_auth_date`, `date_in_auth_window`, `pick_audit_report_date`는 LLM 저장 검증에 **쓰지 않음**
- Produces:
  - `DateResolver.pick_index(..., period_end: str, auth_date: str) -> int | None`
  - `DateResolverService.start(limit: int | None = None) -> str`
  - `POST /admin/extract/resolve-dates` body `{ "limit": int }?`
  - job `params["limit"]`이 있으면 `list_ambiguous_dates()`의 앞 N건만

- [ ] **Step 1: Write the failing tests**

`packages/web-api/tests/test_date_resolver.py`에서:

1. `FakeDateResolver.pick_index`와 `calls` 키를 `rcept_dt` → `auth_date`로 바꾼다. 기존 성공 케이스 `resolver.calls[0]["rcept_dt"]` 단언을 `"auth_date": "2020-03-31"`로 바꾼다. (`rcept_no=20200331000001` → 인증일 2020-03-31. 고른 ISO `2020-03-15`는 창 안이라 계속 `llm` ok.)
2. `LlmDateResolver.pick_index(..., rcept_dt=)` 호출을 `auth_date=`로 바꾸고, 요청 JSON에 `auth_date`가 있고 `rcept_dt`가 없음을 단언하는 테스트를 기존 어댑터 테스트에 넣는다.
3. `FakeDateResolverService.start(self, limit: int | None = None)`로 시그니처를 맞춘다.
4. 아래 테스트를 **추가**한다.

```python
async def test_run_respects_limit_of_one(sessionmaker_fixture) -> None:
    """limit=1이면 rcept_no 순 첫 ambiguous만 llm이다."""
    await _seed(
        sessionmaker_fixture,
        entries=[
            _entry(),
            _entry(entry_id="e-2", rcept_no="20200331000002", dcm_no="22222"),
        ],
        facts=[
            _ambiguous_fact(),
            _ambiguous_fact(rcept_no="20200331000002", dcm_no="22222"),
        ],
    )
    resolver = FakeDateResolver(1)
    service = _service(sessionmaker_fixture, resolver)
    job_id = await service.start(limit=1)
    await service.run(job_id)

    async with sessionmaker_fixture() as session:
        first = await FactRepository(session).get("20200331000001", "11111")
        second = await FactRepository(session).get("20200331000002", "22222")
        job = await session.get(ExtractionJob, job_id)

    assert job is not None
    assert job.params.get("limit") == 1
    assert first is not None and first.audit_report_date_source == "llm"
    assert second is not None and second.audit_report_date_status == "ambiguous"
    assert len(resolver.calls) == 1


async def test_run_keeps_ambiguous_when_pick_is_after_auth_date(
    sessionmaker_fixture,
) -> None:
    """인증일보다 늦은 ISO는 저장하지 않는다."""
    stored = [
        {"date": "2020-02-01", "snippet": "머리"},
        {"date": "2020-04-01", "snippet": "뒤"},
    ]
    await _seed(
        sessionmaker_fixture,
        entries=[_entry()],
        facts=[_ambiguous_fact(audit_report_date_candidates=stored)],
    )
    resolver = FakeDateResolver(1)
    service = _service(sessionmaker_fixture, resolver)
    job_id = await service.start()
    await service.run(job_id)
    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")
    assert fact is not None
    assert fact.audit_report_date_status == "ambiguous"
    assert fact.audit_report_date is None


async def test_resolve_dates_limit_zero_returns_400(client_factory) -> None:
    """limit=0은 잡을 만들지 않고 400이다."""
    service = FakeDateResolverService()
    async with client_factory(_app_with_resolver(service)) as client:
        response = await client.post(
            "/admin/extract/resolve-dates",
            headers=TOKEN_HEADER,
            json={"limit": 0},
        )
    assert response.status_code == 400
    assert "limit" in response.json()["detail"]
    assert service.started == 0
```

기존 `test_run_keeps_ambiguous_when_llm_picks_out_of_window`는 결산 이전 날짜를 고르는 케이스라 그대로 두면 된다. 창 검증만 `date_in_auth_window`로 바뀐다.

기존 `test_resolve_dates_accepts_request_and_schedules_job`은 body 없는 POST 202를 유지한다.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_date_resolver.py -q --tb=line`  
Expected: FAIL (`auth_date`/`start(limit)`/`limit=0`)

- [ ] **Step 3: Write minimal implementation**

포트:

```python
    async def pick_index(
        self,
        *,
        candidates: list[dict],
        period_end: str,
        auth_date: str,
    ) -> int | None:
        """후보 목록에서 감사보고서일 인덱스를 반환한다."""
        ...
```

어댑터 `_PROMPTS["v1"]` 마지막 문장:

```python
"결산일(period_end) 이후이고 인증일(auth_date) 이하인 날짜만 고려하세요."
```

`pick_index`·`_payload` 인자 `rcept_dt` → `auth_date`, user JSON 키도 `auth_date`.

`DateResolverService.start`:

```python
    async def start(self, limit: int | None = None) -> str:
        ...
            params: dict[str, Any] = {}
            if limit is not None:
                params["limit"] = limit
            await jobs.create(job_id, RESOLVE_DATES_EXTRACTOR_ID, params)
```

`run`: `list_ambiguous_dates()` 뒤

```python
            facts = await FactRepository(session).list_ambiguous_dates()
            job_row = await session.get(ExtractionJob, job_id)
            limit = None
            if job_row is not None and isinstance(job_row.params, dict):
                raw_limit = job_row.params.get("limit")
                if isinstance(raw_limit, int):
                    limit = raw_limit
            if limit is not None:
                facts = facts[:limit]
```

(`run`의 첫 세션에서 status를 running으로 바꾼 뒤, facts를 읽는 세션에서 job을 다시 읽어 params를 쓴다.)

`_resolve_one`: `parse_rcept_dt` 대신 `parse_auth_date(sample.rcept_no)`. LLM 호출은 `auth_date=auth_iso`. 저장 전:

```python
        iso_date = date.fromisoformat(iso)
        if not date_in_auth_window(
            iso_date,
            period_end=period_date,
            auth_date=auth_parsed,
        ):
            return False
```

`pick_audit_report_date`를 해소 저장 검증에 호출하지 않는다.

스키마 `packages/web-api/app/schemas/extract.py`:

```python
class ResolveDatesRequest(BaseModel):
    """ambiguous 날짜 LLM 해소 요청. limit 생략 시 대기 행 전량."""

    limit: int | None = None
```

라우트:

```python
from app.schemas.extract import ResolveDatesRequest, ResolveDatesResponse

@router.post("/resolve-dates", ...)
async def resolve_dates(
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings_dep),
    service: DateResolverService = Depends(get_date_resolver_service),
    payload: ResolveDatesRequest | None = None,
) -> ResolveDatesResponse:
    if not settings.date_resolver_api_key:
        raise BadRequest(...)
    limit = payload.limit if payload is not None else None
    if limit is not None and limit < 1:
        raise BadRequest("limit는 1 이상의 정수여야 합니다.")
    job_id = await service.start(limit=limit)
    background_tasks.add_task(service.run, job_id)
    return ResolveDatesResponse(job_id=job_id, status="pending")
```

body 없는 POST가 400이 되면 `payload: ResolveDatesRequest = ResolveDatesRequest()`로 기본값을 둔다.

README `### DATE_RESOLVER`에 한 줄 추가: 비교 기준은 접수번호 앞 8자리(인증일)이고, `{ "limit": N }`으로 건수를 자를 수 있다. 추출 잡은 LLM을 호출하지 않는다.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_date_resolver.py tests/test_extracting_dates.py tests/test_extraction_service.py -q --tb=line`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/ports/date_resolver.py packages/web-api/app/adapters/llm_date_resolver.py packages/web-api/app/services/date_resolver_service.py packages/web-api/app/schemas/extract.py packages/web-api/app/api/admin/extract.py packages/web-api/tests/test_date_resolver.py packages/web-api/README.md
git commit -m "feat(web-api): 날짜 LLM 해소에 한도와 인증일 창을 넣는다"
```

---

## Self-review (spec coverage)

| 스펙 | 태스크 |
|------|--------|
| `_preprocess` 삭제, 중간 날짜 후보 | Task 1 |
| 점·대시·슬래시·年月日·전각, 한자 숫자 제외 | Task 1 |
| `parse_auth_date`, 인증일 일치만 `ok` | Task 1 |
| `rcept_dt`로 고르지 않음 | Task 1–2 |
| `date_in_auth_window` (LLM 창) | Task 1·3 |
| 추출 중 LLM 없음 | Task 2 (호출 추가 안 함) |
| `EXTRACTOR_VERSION` v18 | Task 2 |
| 해소 POST `limit`, `not_found` 제외, 인덱스만 | Task 3 |
| 프롬프트 인증일 | Task 3 |
| 머리글 전처리 스펙 대체 | 구현 안 함 (이 계획이 대체) |
