# F001·F002 목록 감사인 최후 해소 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 표지·본문이 `not_found`인 F001·F002에서만 목록 `submitter`를 `normalize_firm_name`한 뒤 `auditor_source=listing`으로 해소한다.

**Architecture:** `resolve_auditor`만 바꾼다. 문서 출처(표지 → A001 당기 칸 → 본문)가 하나라도 `ok`이면 지금과 같고, listing은 conflict에 넣지 않는다. 문서 출처가 모두 없고 `report_type`이 F001·F002이며 listing이 정규화 후 비어 있지 않을 때만 4순위로 채택한다. 호출자(`extraction_service`)는 이미 F001·F002만 `submitter`를 listing으로 넘기고, `_field_status`는 해소 값이 있으면 `ok`이므로 서비스·스키마·버전은 그대로 둔다.

**Tech Stack:** Python 3.11+, `app.extracting.resolve` 순수 함수, pytest (live DART·LLM 없음)

**Spec:** `docs/superpowers/specs/2026-08-30-auditor-listing-fallback-design.md`

## Global Constraints

- Python 3.11+, 모든 함수 타입 힌트
- 주석·Docstring·로그·예외·테스트 설명은 한국어
- extracting 순수 함수는 sync
- Black/Flake8, line length 100
- 테스트는 실제 DART·LLM을 호출하지 않음
- 작업 디렉터리 기본: `packages/web-api`
- 실행 시 git 커밋은 **사용자가 요청한 경우에만**. 아래 Commit 스텝은 메시지 초안이다
- `resolve_auditor` 시그니처는 유지한다 (`cover` / `a001` / `body` / `listing` / `report_type`)
- `extract_cover_auditor`·`extract_body_auditor` 마커·사전은 바꾸지 않는다. `會計法人`/`監査班`을 추가하지 않는다
- `EXTRACTOR_VERSION`은 `audit_opinion.v3` 유지. `app/extracting/constants.py`를 수정하지 않는다
- `audit_report_facts` 컬럼·`submitter_corp_code`를 추가하지 않는다
- listing을 문서 출처와 짝지어 auditor conflict에 넣지 않는다
- A001 listing(회사명)은 해소에 쓰지 않는다. A001 2순위는 기존 「1. 외부감사에 관한 사항」 당기 칸이다
- `app/services/extraction_service.py`는 수정하지 않는다. F001·F002 listing 전달과 `auditor_listing` 저장·`_field_status`는 이미 맞다
- 재추출은 운영자가 기존 `reparse`를 쓴다. extract skip 규칙을 바꾸지 않는다
- 감사인에 LLM을 쓰지 않는다

---

## File map

| 파일 | 역할 |
|------|------|
| `app/extracting/resolve.py` | `resolve_auditor` 4순위 listing. Docstring 갱신 |
| `tests/test_extracting_resolve.py` | F001·F002 listing 채택·순위 회귀. 기존 테스트는 지우지 않음 |
| `app/services/extraction_service.py` | **수정하지 않음** |
| `app/extracting/constants.py` | **수정하지 않음** |
| `app/extracting/cover.py` / 본문 감사인 추출 | **수정하지 않음** |

---

### Task 1: F001·F002 listing 최후 순위

**Files:**
- Modify: `packages/web-api/app/extracting/resolve.py`
- Test: `packages/web-api/tests/test_extracting_resolve.py`

**Interfaces:**
- Consumes: `FieldResult`, `normalize_firm_name(value: str | None) -> str`, `_is_ok`, `_pairwise_conflicts`
- Produces: `resolve_auditor(*, cover, a001, body, listing, report_type) -> ResolvedAuditor` (시그니처 유지). listing이 이기면 `value`는 정규화한 상호, `source`는 `"listing"`, `conflicts`는 `[]`

기존 테스트는 그대로 통과해야 한다.

- `test_f001_listing_differs_from_cover_no_conflict_cover_wins` — 표지가 listing을 이기고 conflict 없음
- `test_a001_listing_argument_is_ignored` — A001 회사명을 resolved에 쓰지 않음
- `test_a001_falls_back_cover_then_a001_then_body` — A001 listing `"무시됨"`은 본문을 덮지 않음
- `test_f001_cover_versus_body_conflict` — listing이 표지와 같아도 문서 출처끼리만 conflict

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_extracting_resolve.py`에서 `test_a001_listing_argument_is_ignored` **다음**에 추가한다. 기존 테스트를 지우거나 기대값을 바꾸지 않는다. 헬퍼 `_ok` / `_missing`을 그대로 쓴다.

```python
def test_f002_listing_fills_when_cover_and_body_missing() -> None:
    """F002 표지·본문이 없으면 listing을 정규화해 고른다."""
    resolved = resolve_auditor(
        cover=_missing(),
        a001=None,
        body=_missing(),
        listing="우리회계법인",
        report_type="F002",
    )
    assert resolved["value"] == "우리회계법인"
    assert resolved["source"] == "listing"
    assert resolved["conflicts"] == []


def test_f001_listing_fills_when_cover_and_body_missing() -> None:
    """F001도 표지·본문이 없으면 listing을 고른다."""
    resolved = resolve_auditor(
        cover=_missing(),
        a001=None,
        body=_missing(),
        listing="우리회계법인",
        report_type="F001",
    )
    assert resolved["value"] == "우리회계법인"
    assert resolved["source"] == "listing"
    assert resolved["conflicts"] == []


def test_f001_listing_is_normalized() -> None:
    """listing 승자도 주식회사·공백을 뺀다."""
    resolved = resolve_auditor(
        cover=_missing(),
        a001=None,
        body=_missing(),
        listing="우리 회계법인주식회사",
        report_type="F001",
    )
    assert resolved["value"] == "우리회계법인"
    assert resolved["source"] == "listing"


def test_f001_empty_listing_stays_not_found() -> None:
    """F001이어도 listing이 비면 resolved는 없다."""
    resolved = resolve_auditor(
        cover=_missing(),
        a001=None,
        body=_missing(),
        listing="  ",
        report_type="F001",
    )
    assert resolved["value"] is None
    assert resolved["source"] is None
    assert resolved["conflicts"] == []


def test_f001_body_wins_over_listing_without_conflict() -> None:
    """본문만 ok이면 listing이 달라도 본문이고 conflict가 없다."""
    resolved = resolve_auditor(
        cover=_missing(),
        a001=None,
        body=_ok("한영회계법인"),
        listing="우리회계법인",
        report_type="F001",
    )
    assert resolved["value"] == "한영회계법인"
    assert resolved["source"] == "body"
    assert resolved["conflicts"] == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run:

```bash
python -m pytest tests/test_extracting_resolve.py::test_f002_listing_fills_when_cover_and_body_missing tests/test_extracting_resolve.py::test_f001_listing_fills_when_cover_and_body_missing tests/test_extracting_resolve.py::test_f001_listing_is_normalized tests/test_extracting_resolve.py::test_f001_empty_listing_stays_not_found tests/test_extracting_resolve.py::test_f001_body_wins_over_listing_without_conflict -v
```

작업 디렉터리: `packages/web-api`

Expected: FAIL. listing 채택 테스트는 `assert resolved["value"] == "우리회계법인"`에서 `None`과 불일치한다. `test_f001_body_wins_over_listing_without_conflict`는 **지금 구현에서도 통과**할 수 있다(본문이 이미 1순위). 통과해도 지우지 않는다. 회귀 고정이다.

- [ ] **Step 3: 최소 구현**

`app/extracting/resolve.py`의 `resolve_auditor` docstring과 본문을 아래처럼 교체한다. `ranked` 구성과 `_pairwise_conflicts` 호출은 기존과 같다. listing은 `ranked`에 넣지 않는다.

```python
def resolve_auditor(
    *,
    cover: FieldResult | None,
    a001: FieldResult | None,
    body: FieldResult | None,
    listing: str | None,
    report_type: str,
) -> ResolvedAuditor:
    """문서 출처 순위로 감사인을 고르고, listing은 conflict에 넣지 않는다.

    순위는 표지 → (A001만 당기 칸) → 본문 → (F001·F002만 목록 submitter).
    listing은 앞 출처가 모두 없고 정규화 후 비어 있지 않을 때만 쓴다.
    A001 listing(회사명)은 호출자가 넘기더라도 이 함수에서 무시한다.
    """
    ranked: list[tuple[str, FieldResult]] = []
    if _is_ok(cover):
        ranked.append(("cover", cover))
    if report_type == "A001" and _is_ok(a001):
        ranked.append(("a001", a001))
    if _is_ok(body):
        ranked.append(("body", body))

    conflicts = _pairwise_conflicts(
        "auditor",
        [(source, item.raw or "") for source, item in ranked],
        key=normalize_firm_name,
    )
    if ranked:
        source, winner = ranked[0]
        return ResolvedAuditor(
            value=normalize_firm_name(winner.raw) or None,
            source=source,
            conflicts=conflicts,
        )
    if report_type in {"F001", "F002"}:
        listing_name = normalize_firm_name(listing)
        if listing_name:
            return ResolvedAuditor(
                value=listing_name,
                source="listing",
                conflicts=conflicts,
            )
    return ResolvedAuditor(value=None, source=None, conflicts=conflicts)
```

`_ = listing` 줄은 삭제한다.

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run:

```bash
python -m pytest tests/test_extracting_resolve.py -v
```

작업 디렉터리: `packages/web-api`

Expected: PASS (기존 해소·의견·회사명·결산월 테스트 포함 전부).

이어서 포맷·린트:

```bash
python -m black --line-length 100 app/extracting/resolve.py tests/test_extracting_resolve.py
python -m flake8 app/extracting/resolve.py tests/test_extracting_resolve.py
```

Expected: Black이 필요 시 파일을 고치고, flake8 exit 0.

- [ ] **Step 5: Commit (사용자가 요청한 경우에만)**

```bash
git add packages/web-api/app/extracting/resolve.py packages/web-api/tests/test_extracting_resolve.py
git commit -m "feat: F001·F002 목록 감사인을 최후로 해소한다"
```

---

## 운영 메모 (구현 밖)

버전을 올리지 않으므로 `extract`/`resume`은 `fetch_status=ok`인 기존 행을 건너뛴다. 대동시스템처럼 감사인만 `not_found`인 행은 Admin `reparse`로 다시 넣는다. override·LLM 날짜 보존은 기존 reparse 규칙을 따른다.

---

## Spec coverage (self-review)

| Spec | Task |
|------|------|
| §3 순위 1–3 유지, listing은 4순위 | Task 1 Step 3. 기존 표지·A001·본문 테스트 유지 |
| §3 F001·F002만 listing, 정규화, `source=listing` | `test_f001_*` / `test_f002_*` / `test_f001_listing_is_normalized` |
| §3 A001 listing 미사용 | 기존 `test_a001_listing_argument_is_ignored` |
| §3 listing을 auditor conflict에 넣지 않음 | 기존 표지≠listing 테스트 + `test_f001_body_wins_over_listing_without_conflict` |
| §3 표지·본문 원문 컬럼은 None | 서비스 미수정. cover/body `not_found`면 기존처럼 raw None |
| §4 재추출은 reparse | 운영 메모. 코드 없음 |
| §5 다섯 케이스 | Step 1 신규 4 + 기존 A001 ignore 1 |
| §6 한자 마커·사전·corp_code·버전·LLM | Global Constraints. 파일 미수정 |
