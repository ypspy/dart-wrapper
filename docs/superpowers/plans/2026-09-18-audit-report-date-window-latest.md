# 감사보고서일 창 안 최댓값 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 추출은 `결산월말 < 날짜 ≤ 인증일` 창 안의 가장 늦은 ISO를 `ok`로 두고, 창이 비면 `not_found`로 남기며, 운영자가 해소 잡을 누르면 후보가 있는 `not_found`만 LLM 인덱스로 패치한다.

**Architecture:** `pick_audit_report_date`가 `date_in_auth_window`로 거른 뒤 ISO 최댓값을 고른다. 해소 잡은 `list_not_found_dates`(후보 비어 있지 않음)를 순회하고 저장 때 창 검사를 하지 않는다. 추출기는 `audit_opinion.v19`이다.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, pytest, httpx mock.

## Global Constraints

- 패키지: `packages/web-api`만.
- 주석·Docstring·로그·사용자 메시지는 한국어.
- 테스트: `packages/web-api`에서 `.\.venv\Scripts\python.exe -m pytest <파일> -q --tb=short`. Windows에서 pytest가 통과 후 hang하면 해당 파일 테스트가 모두 통과한 뒤 hang으로 본다.
- KSIC/OpenDART 워킹 트리 변경은 커밋에 넣지 않음.
- 한자 숫자 변환, 본문을 LLM에 첨부하기, 새 ISO 생성, 후반·머리글 우선, `rcept_dt`로 창/일치, 날짜 전용 reparse, Admin 해소 UI, 후보 0건을 해소 잡에 넣기, `ambiguous`를 pick이 만들기 없음.
- live DART·live OpenAI 호출 없음.
- [스펙](../specs/2026-09-18-audit-report-date-window-latest-design.md). 인증일 일치 전용 pick은 구현하지 않음.

## File map

| 파일 | 책임 |
|------|------|
| `packages/web-api/app/extracting/dates.py` | `pick`이 창 안 최댓값 / 빈 창 `not_found` |
| `packages/web-api/tests/test_extracting_dates.py` | 창 안 최댓값·빈 창 `not_found` |
| `packages/web-api/app/extracting/constants.py` | `audit_opinion.v19` |
| `packages/web-api/tests/test_extraction_service.py` | 버전 문자열 |
| `packages/web-api/tests/test_audit_report_fact_repository.py` | 버전·`list_not_found_dates` |
| `packages/web-api/app/repositories/fact_repository.py` | `list_not_found_dates` |
| `packages/web-api/app/services/date_resolver_service.py` | `not_found` 순회, 저장 시 창 없음 |
| `packages/web-api/app/adapters/llm_date_resolver.py` | 프롬프트에서 창 제한 삭제 |
| `packages/web-api/tests/test_date_resolver.py` | `not_found` 대상·창 밖 저장 |
| `packages/web-api/README.md` | 보고일·DATE_RESOLVER |

`ExtractionService._build_fact`의 `parse_auth_date(rcept_no)` 배선은 유지한다.

---

### Task 1: 창 안 최댓값 pick

**Files:**
- Modify: `packages/web-api/tests/test_extracting_dates.py`
- Modify: `packages/web-api/app/extracting/dates.py`

**Interfaces:**
- Consumes: `extract_date_candidates`, `date_in_auth_window(iso, *, period_end, auth_date) -> bool`, `parse_auth_date`
- Produces: `pick_audit_report_date(candidates: Sequence[DateCandidate], *, period_end: date | None, auth_date: date | None) -> tuple[str | None, str, list[DateCandidate]]` — 창 안 최댓값 `ok` 또는 `not_found`. `ambiguous`를 반환하지 않음.

- [ ] **Step 1: Write the failing tests**

`test_ok_only_when_candidate_equals_auth_date`를 아래처럼 **교체**하고, `test_ambiguous_when_auth_date_missing`·`test_trailing_header_is_candidate`의 불일치 단언을 `not_found`로 바꾼다. 후보 추출 테스트는 그대로 둔다.

```python
def test_picks_latest_iso_in_auth_window() -> None:
    """창 안에서는 인증일 일치가 아니라 가장 늦은 ISO를 고른다."""
    text = (
        "우리는 2018년12월31일로 종료되는 회계연도를 감사하였습니다. "
        "중간 2019년3월15일 재무제표에대한경영진의책임. 2019년3월31일"
    )
    candidates = extract_date_candidates(text)
    iso, status, passing = pick_audit_report_date(
        candidates,
        period_end=date(2018, 12, 31),
        auth_date=date(2019, 3, 31),
    )
    assert status == "ok"
    assert iso == "2019-03-31"
    assert [c.iso for c in passing] == ["2019-03-31"]


def test_picks_day_before_auth_when_it_is_latest_in_window() -> None:
    """창 안이 인증일 전날뿐이면 그날이 ok다."""
    text = (
        "우리는 2018년12월31일로 종료되는 회계연도를 감사하였습니다. "
        "감사의견 적정. 2019년3월15일"
    )
    candidates = extract_date_candidates(text)
    iso, status, passing = pick_audit_report_date(
        candidates,
        period_end=date(2018, 12, 31),
        auth_date=date(2019, 3, 31),
    )
    assert status == "ok"
    assert iso == "2019-03-15"
    assert [c.iso for c in passing] == ["2019-03-15"]


def test_not_found_when_candidates_exist_but_none_in_window() -> None:
    """후보는 있으나 모두 창 밖이면 not_found다."""
    candidates = extract_date_candidates("전기 2018년3월15일 결산 2018년12월31일")
    iso, status, passing = pick_audit_report_date(
        candidates,
        period_end=date(2018, 12, 31),
        auth_date=date(2019, 3, 31),
    )
    assert status == "not_found"
    assert iso is None
    assert passing == []


def test_not_found_when_auth_date_missing() -> None:
    """후보가 있어도 인증일이 없으면 not_found다."""
    candidates = extract_date_candidates("서명 2019년3월15일")
    iso, status, _passing = pick_audit_report_date(
        candidates,
        period_end=date(2018, 12, 31),
        auth_date=None,
    )
    assert status == "not_found"
    assert iso is None
```

`test_trailing_header_is_candidate` 두 번째 pick(인증일 `2016-01-13`)은 창 안 최댓값이 `2015-12-24`이므로 `ok` / `2015-12-24`가 된다. docstring을 「후행형 머리글 날짜가 후보다」로 두고 불일치=`ambiguous` 단언을 삭제한다.

```python
    iso, status, passing = pick_audit_report_date(
        candidates,
        period_end=date(2015, 10, 31),
        auth_date=date(2016, 1, 13),
    )
    assert status == "ok"
    assert iso == "2015-12-24"
    assert [c.iso for c in passing] == ["2015-12-24"]
```

`test_date_in_auth_window` docstring은 「추출 창은 결산 초과·인증일 이하다.」로 바꾼다.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_dates.py -q --tb=short`

Expected: `test_picks_day_before_auth_when_it_is_latest_in_window` 등이 `ambiguous` vs `ok` / `not_found`로 FAIL.

- [ ] **Step 3: Implement pick**

`packages/web-api/app/extracting/dates.py`의 `pick_audit_report_date` docstring과 본문을 교체한다. 모듈 docstring은 「감사보고서일 후보 추출과 창 안 최댓값 선택.」

```python
def pick_audit_report_date(
    candidates: Sequence[DateCandidate],
    *,
    period_end: date | None,
    auth_date: date | None,
) -> tuple[str | None, str, list[DateCandidate]]:
    """창 안 ISO 중 최댓값을 보고일로 고른다.

    후보 0·인증일 없음·창 통과 0 → not_found. ambiguous를 만들지 않는다.
    """
    if not candidates:
        return None, "not_found", []
    if auth_date is None:
        return None, "not_found", []
    in_window = [
        item
        for item in candidates
        if date_in_auth_window(
            date.fromisoformat(item.iso),
            period_end=period_end,
            auth_date=auth_date,
        )
    ]
    if not in_window:
        return None, "not_found", []
    latest = max(item.iso for item in in_window)
    passing = [item for item in in_window if item.iso == latest]
    return latest, "ok", passing
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_dates.py -q --tb=short`

Expected: 전부 PASS (기존 13개에서 테스트가 늘면 그 개수).

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/tests/test_extracting_dates.py packages/web-api/app/extracting/dates.py
git commit -m "feat(web-api): 감사보고서일은 창 안에서 가장 늦은 날을 고른다"
```

---

### Task 2: 추출기 v19

**Files:**
- Modify: `packages/web-api/app/extracting/constants.py`
- Modify: `packages/web-api/tests/test_extraction_service.py` (`audit_opinion.v18` 문자열)
- Modify: `packages/web-api/tests/test_audit_report_fact_repository.py` (버전 단언)

**Interfaces:**
- Consumes: Task 1 `pick` (배선 유지)
- Produces: `EXTRACTOR_VERSION == "audit_opinion.v19"`

- [ ] **Step 1: Write the failing assertions**

다음을 `audit_opinion.v19`로 바꾼다. 아직 상수가 v18이면 FAIL.

- `packages/web-api/tests/test_extraction_service.py`의 `"audit_opinion.v18"` 전부
- `packages/web-api/tests/test_audit_report_fact_repository.py`의 `assert EXTRACTOR_VERSION == "audit_opinion.v18"`

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py tests/test_audit_report_fact_repository.py -q --tb=line`

Expected: 버전 AssertionError.

- [ ] **Step 3: Bump the constant**

`packages/web-api/app/extracting/constants.py`:

```python
EXTRACTOR_VERSION = "audit_opinion.v19"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py tests/test_audit_report_fact_repository.py tests/test_extracting_dates.py -q --tb=short`

Expected: PASS. (WIP 워킹 트리의 다른 실패는 이 커밋에 넣지 않음.)

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/extracting/constants.py packages/web-api/tests/test_extraction_service.py packages/web-api/tests/test_audit_report_fact_repository.py
git commit -m "feat(web-api): 추출기 버전을 v19로 올려 보고일 창 규칙을 다시 받는다"
```

---

### Task 3: not_found LLM 패치 (창 검사 없음)

**Files:**
- Modify: `packages/web-api/app/repositories/fact_repository.py`
- Modify: `packages/web-api/tests/test_audit_report_fact_repository.py`
- Modify: `packages/web-api/app/services/date_resolver_service.py`
- Modify: `packages/web-api/app/adapters/llm_date_resolver.py`
- Modify: `packages/web-api/tests/test_date_resolver.py`
- Modify: `packages/web-api/README.md`

**Interfaces:**
- Consumes: `pick_index(..., period_end: str, auth_date: str) -> int | None` (시그니처 유지, 프롬프트만 변경)
- Produces:
  - `FactRepository.list_not_found_dates() -> list[AuditReportFact]` — status `not_found`이고 `audit_report_date_candidates`가 비어 있지 않은 행. 정렬 `rcept_no`, `dcm_no`
  - `DateResolverService.run`이 그 목록을 쓰고 `_resolve_one`은 창 없이 저장

- [ ] **Step 1: Write the failing tests**

`test_list_ambiguous_dates` 옆에 추가 (기존 ambiguous 목록 테스트는 유지):

```python
async def test_list_not_found_dates_skips_empty_candidates(
    sessionmaker_fixture,
) -> None:
    """not_found이면서 후보가 있는 행만 반환한다."""
    async with sessionmaker_fixture() as session:
        repo = FactRepository(session)
        await repo.upsert(_make_fact(dcm_no="ok-date", audit_report_date_status="ok"))
        await repo.upsert(
            _make_fact(
                dcm_no="nf-empty",
                audit_report_date=None,
                audit_report_date_status="not_found",
                audit_report_date_candidates=[],
            )
        )
        await repo.upsert(
            _make_fact(
                dcm_no="nf-has",
                audit_report_date=None,
                audit_report_date_status="not_found",
                audit_report_date_candidates=[{"date": "2019-03-15", "snippet": "서명"}],
            )
        )
        await repo.upsert(
            _make_fact(
                rcept_no="20260331000002",
                dcm_no="amb",
                audit_report_date=None,
                audit_report_date_status="ambiguous",
                audit_report_date_candidates=[{"date": "2019-03-15", "snippet": "서명"}],
            )
        )
        await session.commit()

    async with sessionmaker_fixture() as session:
        rows = await FactRepository(session).list_not_found_dates()

    keys = [(row.rcept_no, row.dcm_no) for row in rows]
    assert keys == [("20260331000001", "nf-has")]
```

`tests/test_date_resolver.py`:

- `_ambiguous_fact`를 `_unresolved_fact`로 바꾸고 기본 `audit_report_date_status="not_found"`.
- 모든 `_ambiguous_fact(` 호출을 `_unresolved_fact(`로.
- `test_run_keeps_ambiguous_when_resolver_returns_invalid_index`: 남은 status는 `"not_found"`.
- `test_run_respects_limit_of_one`: 두 번째 행 status `"not_found"`. docstring 「첫 not_found만 llm」.
- `test_run_keeps_ambiguous_when_pick_is_after_auth_date`를 **교체**:

```python
async def test_run_saves_when_pick_is_after_auth_date(
    sessionmaker_fixture,
) -> None:
    """인증일보다 늦은 ISO도 저장한다."""
    stored = [
        {"date": "2020-02-01", "snippet": "머리"},
        {"date": "2020-04-01", "snippet": "뒤"},
    ]
    await _seed(
        sessionmaker_fixture,
        entries=[_entry()],
        facts=[_unresolved_fact(audit_report_date_candidates=stored)],
    )
    resolver = FakeDateResolver(1)
    service = _service(sessionmaker_fixture, resolver)
    job_id = await service.start()
    await service.run(job_id)
    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")
    assert fact is not None
    assert fact.audit_report_date == "2020-04-01"
    assert fact.audit_report_date_status == "ok"
    assert fact.audit_report_date_source == "llm"
```

- `test_run_keeps_ambiguous_when_candidate_iso_invalid`: 행은 `not_found`로 남김. 잡은 `succeeded`.
- `test_run_keeps_ambiguous_when_llm_picks_out_of_window`를 **교체**:

```python
async def test_run_saves_when_llm_picks_out_of_window(
    sessionmaker_fixture,
) -> None:
    """창 밖 ISO를 골라도 저장한다."""
    stored = [
        {
            "date_raw": "2020년2월1일",
            "date": "2020-02-01",
            "snippet": "머리 2020년2월1일",
        },
        {
            "date_raw": "2018년6월1일",
            "date": "2018-06-01",
            "snippet": "옛날짜 2018년6월1일",
        },
    ]
    await _seed(
        sessionmaker_fixture,
        entries=[_entry()],
        facts=[_unresolved_fact(audit_report_date_candidates=stored)],
    )
    resolver = FakeDateResolver(1)
    service = _service(sessionmaker_fixture, resolver)
    job_id = await service.start()
    await service.run(job_id)

    async with sessionmaker_fixture() as session:
        fact = await FactRepository(session).get("20200331000001", "11111")

    assert fact is not None
    assert fact.audit_report_date == "2018-06-01"
    assert fact.audit_report_date_status == "ok"
    assert fact.audit_report_date_source == "llm"
```

추가:

```python
async def test_run_skips_ambiguous_and_empty_not_found(
    sessionmaker_fixture,
) -> None:
    """ambiguous와 후보 없는 not_found는 해소하지 않는다."""
    await _seed(
        sessionmaker_fixture,
        entries=[
            _entry(),
            _entry(entry_id="e-2", rcept_no="20200331000002", dcm_no="22222"),
            _entry(entry_id="e-3", rcept_no="20200331000003", dcm_no="33333"),
        ],
        facts=[
            _unresolved_fact(
                rcept_no="20200331000001",
                audit_report_date_status="ambiguous",
            ),
            _unresolved_fact(
                rcept_no="20200331000002",
                dcm_no="22222",
                audit_report_date_candidates=[],
            ),
            _unresolved_fact(rcept_no="20200331000003", dcm_no="33333"),
        ],
    )
    resolver = FakeDateResolver(1)
    service = _service(sessionmaker_fixture, resolver)
    job_id = await service.start()
    await service.run(job_id)
    async with sessionmaker_fixture() as session:
        amb = await FactRepository(session).get("20200331000001", "11111")
        empty = await FactRepository(session).get("20200331000002", "22222")
        filled = await FactRepository(session).get("20200331000003", "33333")
    assert amb is not None and amb.audit_report_date_status == "ambiguous"
    assert empty is not None and empty.audit_report_date_status == "not_found"
    assert empty.audit_report_date is None
    assert filled is not None and filled.audit_report_date_source == "llm"
    assert len(resolver.calls) == 1
```

`test_llm_adapter_parses_index_json`에 시스템 프롬프트가 「이하인 날짜만」을 포함하지 않음을 단언한다.

```python
    system = payload["messages"][0]["content"]
    assert "이하인 날짜만" not in system
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_date_resolver.py tests/test_audit_report_fact_repository.py::test_list_not_found_dates_skips_empty_candidates -q --tb=short`

Expected: `list_not_found_dates` Import/AttributeError, 창 밖 저장 테스트 FAIL (`ambiguous` vs `ok`).

- [ ] **Step 3: Implement repository, service, prompt, README**

`fact_repository.py`에 추가 (`list_ambiguous_dates`는 유지):

```python
    async def list_not_found_dates(self) -> list[AuditReportFact]:
        """감사보고서일이 not_found이고 후보가 있는 행."""
        statement = (
            select(AuditReportFact)
            .where(AuditReportFact.audit_report_date_status == "not_found")
            .order_by(AuditReportFact.rcept_no, AuditReportFact.dcm_no)
        )
        result = await self._session.execute(statement)
        return [
            row
            for row in result.scalars().all()
            if row.audit_report_date_candidates
        ]
```

`date_resolver_service.py`:

- 모듈/클래스 docstring: 「후보가 있는 not_found 감사보고서일을 LLM 인덱스로 해소」.
- `run`: `list_ambiguous_dates()` → `list_not_found_dates()`.
- `_resolve_one`에서 `date_in_auth_window` import와 호출 블록을 삭제한다. ISO 파싱 실패 시 `return False`(행은 `not_found` 유지, 잡은 계속). `period_end`/`auth_iso`는 `_window_for`로 프롬프트에만 넘긴다.
- `_resolve_one` docstring: 「성공하면 True, 그대로 not_found면 False.」

`llm_date_resolver.py` `_PROMPTS["v1"]`:

```python
        "당신은 감사보고서일 후보 중 실제 서명일(감사보고서일)을 고릅니다. "
        "JSON만 답하세요. 형식은 {\"index\": n} 또는 {\"index\": null} 입니다. "
        "새 날짜를 만들지 마세요. 고를 수 없으면 null 을 주세요. "
        "결산일(period_end)과 인증일(auth_date)은 참고만 하세요."
```

`README.md`:

- 구조 표·추출기 버전: `audit_opinion.v19`
- **보고일**: compact 본문에서 날짜를 전수 모은 뒤 `period_end < iso ≤` 접수번호 앞 8자리(인증일) 중 **가장 늦은 날**이 `ok`/`letter`. 창이 비면 `not_found`(ISO는 null, 후보는 저장). 목록 `rcept_dt`는 쓰지 않음.
- DATE_RESOLVER: 후보가 있는 `not_found`를 LLM이 인덱스로 고른다. 저장 때 창 검사를 하지 않는다. `limit`·API 키는 지금과 같다. 추출 잡은 LLM을 호출하지 않는다.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_date_resolver.py tests/test_audit_report_fact_repository.py tests/test_extracting_dates.py -q --tb=short`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/repositories/fact_repository.py packages/web-api/app/services/date_resolver_service.py packages/web-api/app/adapters/llm_date_resolver.py packages/web-api/tests/test_date_resolver.py packages/web-api/tests/test_audit_report_fact_repository.py packages/web-api/README.md
git commit -m "feat(web-api): 창이 빈 보고일은 not_found로 두고 LLM이 후보를 고르게 한다"
```
