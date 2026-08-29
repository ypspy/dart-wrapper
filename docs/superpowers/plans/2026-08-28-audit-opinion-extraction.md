# 감사보고서 표지·의견 추출 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 카탈로그 `viewer_url`로 감사 표지·의견 5필드를 뽑아 `audit_report_facts`에 저장하고, Admin 추출/완전성/날짜해소 API와 Public 조회로 제공한다.

**Architecture:** `app/extracting/`에 순수 selector·파서·해소를 두고, 잡은 `DartHttp`+`extract_blocks`로 leaf만 fetch한다. HTML은 저장하지 않는다. 카탈로그 수집과 추출 잡(DART)은 상호 배타, 날짜 LLM 잡은 DART를 치지 않아 병행 가능하다.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2 async, httpx, BeautifulSoup/`extract_blocks`, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-08-28-audit-opinion-extraction-design.md`  
**원전:** [ypspy/dart-scraping](https://github.com/ypspy/dart-scraping) D-1~D-4-1, D-3-2~D-3-4. 키워드·섹션 규칙을 바꿀 때는 해당 파일을 연 뒤에만 수정한다.

## Global Constraints

- Python 3.11+, 모든 함수 타입 힌트
- 주석·Docstring·로그·예외·테스트 설명은 한국어
- I/O는 async. extracting 순수 함수는 sync
- Black/Flake8, line length 100
- 테스트는 실제 DART·LLM을 호출하지 않음
- 작업 디렉터리 기본: `packages/web-api`
- 실행 시 git 커밋은 **사용자가 요청한 경우에만**. 아래 Commit 스텝은 메시지 초안이다
- OpenDART 사용 금지. HTML 원문 DB 저장 금지

---

## File map

| 파일 | 역할 |
|------|------|
| `app/extracting/text.py` | `compact()` |
| `app/extracting/selector.py` | 대상 문서·leaf 선정 |
| `app/extracting/opinion.py` | D-3-2 의견 분류 |
| `app/extracting/gaap.py` | D-3-4 GAAP 분류 |
| `app/extracting/dates.py` | D-3-3 후보 + 창 선택 |
| `app/extracting/cover.py` | D-2 당기·표지 감사인 |
| `app/extracting/a001_section.py` | A001 `1. 외부감사에 관한 사항` 당기 칸 |
| `app/extracting/activity_header.py` | 실시내용 회사명·결산월 헤더 |
| `app/extracting/auditor_body.py` | D-3-1 사전 매칭 |
| `app/extracting/resolve.py` | 우선순위·conflicts |
| `app/extracting/data/auditor_names.txt` | D-3-1 사전 (GitHub `data01.auditor.txt` 복사) |
| `app/models/audit_report_fact.py` | facts 테이블 |
| `app/models/extraction_job.py` | 추출 잡·로그 |
| `app/repositories/fact_repository.py` | facts upsert/조회 |
| `app/repositories/extraction_job_repository.py` | 잡 CRUD |
| `app/services/dart_job_lock.py` | DART 잡 상호 배타 |
| `app/services/extraction_service.py` | 추출 오케스트레이션 |
| `app/services/completeness_service.py` | 완전성 집계 |
| `app/services/date_resolver_service.py` | ambiguous 날짜 LLM |
| `app/ports/date_resolver.py` | `DateResolver` 프로토콜 |
| `app/adapters/llm_date_resolver.py` | LLM 어댑터 |
| `app/api/admin/extract.py` | Admin 추출·완전성·PATCH |
| `app/api/v1/facts.py` | Public GET |
| `app/schemas/extract.py` / `facts.py` | 요청·응답 |
| `scripts/export_audit_report_facts.py` | CSV export |
| `app/config.py`, `app/main.py`, `app/api/deps.py`, `app/models/__init__.py` | 연결 |
| `packages/web-api/README.md`, `.env.example` | 문서·설정 |

---

### Task 1: `compact`와 selector

**Files:**
- Create: `app/extracting/__init__.py`, `app/extracting/text.py`, `app/extracting/selector.py`
- Test: `tests/test_extracting_selector.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `compact(value: str | None) -> str`
  - `fs_scope_for(report_type: str, document_name: str | None) -> str`
  - `is_audit_document(report_type: str | None, source: str, document_name: str | None) -> bool`
  - `select_leaves(entries: list[SelectorEntry]) -> LeafIds`
  - `SelectorEntry` dataclass: `entry_id`, `rcept_no`, `dcm_no`, `report_type`, `source`, `document_name`, `section_name`
  - `LeafIds` dataclass: `cover_entry_id`, `opinion_entry_id`, `activity_entry_id`, `a001_opinion_entry_id`, `a001_cover_entry_id` (모두 `str | None`)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from app.extracting.selector import SelectorEntry, is_audit_document, select_leaves
from app.extracting.text import compact

def test_compact_strips_spaces() -> None:
    assert compact("독립된 감사인의 감사보고서") == "독립된감사인의감사보고서"
    assert compact(None) == ""

def test_rejects_statutory_auditor_report() -> None:
    assert not is_audit_document("A001", "attachment", "감사의감사보고서")
    assert not is_audit_document("A001", "attachment", "내부회계관리제도운영보고서")

def test_accepts_f001_and_a001_attachment() -> None:
    assert is_audit_document("F001", "body", "감사보고서")
    assert is_audit_document("A001", "attachment", "연결감사보고서")
    assert not is_audit_document("A001", "body", "사업보고서")

def test_select_leaves_f001() -> None:
    rows = [
        SelectorEntry("c", "r", "d", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry("o", "r", "d", "F001", "body", "감사보고서", "독립된 감사인의 감사보고서"),
        SelectorEntry("a", "r", "d", "F001", "body", "감사보고서", "외부감사 실시내용"),
        SelectorEntry("x", "r", "d", "F001", "body", "감사보고서", "내부회계관리제도 검토의견"),
    ]
    leaves = select_leaves(rows)
    assert leaves.cover_entry_id == "c"
    assert leaves.opinion_entry_id == "o"
    assert leaves.activity_entry_id == "a"
    assert leaves.a001_opinion_entry_id is None

def test_select_a001_opinion_prefers_numbered_section() -> None:
    same = dict(rcept_no="r", dcm_no="att", report_type="A001", source="attachment")
    body = dict(rcept_no="r", dcm_no="body", report_type="A001", source="body", document_name="사업보고서")
    rows = [
        SelectorEntry("att-c", **same, document_name="감사보고서", section_name="감사보고서"),
        SelectorEntry("ch", **body, section_name="V. 감사인의 감사의견 등"),
        SelectorEntry("n1", **body, section_name="1. 외부감사에 관한 사항"),
        SelectorEntry("skip", **body, section_name="2. 감사제도에 관한 사항"),
        SelectorEntry("cov", **body, section_name="사업보고서"),
    ]
    leaves = select_leaves(rows)
    assert leaves.a001_opinion_entry_id == "n1"
    assert leaves.a001_cover_entry_id == "cov"
```

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_selector.py -v`  
Expected: FAIL (`ModuleNotFoundError` 또는 import 오류)

- [ ] **Step 3: 구현**

`text.py`: `re.sub(r"\s+", "", value or "")`.

`selector.py` 규칙 (스펙 §5, 공백 제거 후 비교):

- `is_audit_document`: F001/F002는 True. A001은 `source==attachment`이고 compact 문서명이 `감사보고서` 또는 `연결감사보고서`. compact에 `내부회계`, `내부감시장치`, `감사의감사보고서`가 있으면 False.
- `fs_scope_for`: F001→`separate`, F002→`consolidated`, A001 연결감사보고서→`consolidated`, A001 감사보고서→`separate`, 그 외 `unknown`.
- cover: 같은 `dcm_no`에서 compact `section_name==감사보고서`이고 `독립된감사인의감사보고서`가 아님.
- opinion: compact가 `독립된감사인의감사보고서` 또는 `외부감사인의감사보고서`.
- activity: compact `외부감사실시내용`.
- a001 opinion: `source==body`이고 compact가 `1.외부감사에관한사항`이면 최우선. 없으면 `감사인의감사의견등` 또는 `회계감사인의감사의견등`을 포함. `2.감사제도에관한사항` 제외.
- a001 cover: `source==body`, compact 문서명·섹션명 모두 `사업보고서`.

`select_leaves`는 같은 `rcept_no` 목록을 받아 첫 감사 `dcm_no`의 cover/opinion/activity와, 접수 전체에서 a001 body leaf를 채운다. 여러 감사 문서(별도+연결 첨부)는 **호출자가 dcm_no로 나눠** `select_leaves`에 넘긴다. 헬퍼 `group_by_dcm(entries) -> dict[str, list[SelectorEntry]]`를 같은 파일에 둔다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extracting_selector.py -v`  
Expected: PASS

- [ ] **Step 5: Commit (사용자 요청 시에만)**

```text
feat(web-api): 감사보고서 추출 selector 추가
```

---

### Task 2: 의견·GAAP 분류 (D-3-2, D-3-4)

**Files:**
- Create: `app/extracting/opinion.py`, `app/extracting/gaap.py`
- Test: `tests/test_extracting_opinion_gaap.py`

**Interfaces:**
- Consumes: `compact`
- Produces:
  - `class FieldResult`: `raw: str | None`, `code: str | None`, `status: str`
  - `classify_opinion(text: str, *, looks_like_letter: bool) -> FieldResult`
  - `classify_gaap(text: str) -> FieldResult`

키워드는 [D-3-2](https://github.com/ypspy/dart-scraping/blob/master/(D-3-2)%20auditReportOpinion)·[D-3-4](https://github.com/ypspy/dart-scraping/blob/master/(D-3-4)%20auditReportGAAP)를 연 뒤 목록을 그대로 상수로 옮긴다. 본문은 `compact` 후 매칭. D-3-4의 `"'일반기업회계기준'에 따라"`처럼 공백이 있는 항목은 compact한 패턴도 함께 둔다.

- [ ] **Step 1: 실패하는 테스트**

```python
from app.extracting.opinion import classify_opinion
from app.extracting.gaap import classify_gaap

def test_boilerplate_unqualified_when_letter_and_no_exception() -> None:
    text = "감사의견 " + ("본문" * 80)
    result = classify_opinion(text, looks_like_letter=True)
    assert result.status == "ok"
    assert result.code == "unqualified"
    assert result.raw == "boilerplate_unqualified"

def test_disclaimer_keyword() -> None:
    result = classify_opinion("의견을표명하지아니합니다" + ("가" * 200), looks_like_letter=True)
    assert result.code == "disclaimer"

def test_not_found_when_not_a_letter() -> None:
    result = classify_opinion("짧음", looks_like_letter=False)
    assert result.status == "not_found"
    assert result.code is None

def test_gaap_k_ifrs_and_other() -> None:
    assert classify_gaap("한국채택국제회계기준에따라작성").code == "k-ifrs"
    assert classify_gaap("일반기업회계기준에따라작성").code == "k-gaap"
    assert classify_gaap("관련 문구 없음").code == "other"
    assert classify_gaap("관련 문구 없음").status == "ok"
```

`looks_like_letter`: 호출자가 `compact(text)` 길이 ≥ 200 또는 `'감사의견' in compact(text)`로 계산한다. `classify_opinion` 내부에서 `looks_like_letter is False`이면 즉시 `not_found`. True이면 D-3-2 순서로 거절→한정→부적정 매칭, 없으면 unqualified.

GAAP는 매칭 없어도 `code=other`, `status=ok`, `raw=예외` (옛 D-3-4 기본값). 매칭되면 `raw`는 태그 한글명(`일반기업회계기준` / `한국채택국제회계기준` / `기타기준`).

- [ ] **Step 2:** pytest `tests/test_extracting_opinion_gaap.py -v` → FAIL
- [ ] **Step 3:** 구현
- [ ] **Step 4:** pytest PASS
- [ ] **Step 5: Commit 초안** `feat(web-api): 감사의견·GAAP 분류기 추가`

---

### Task 3: 날짜 후보와 창 선택 (D-3-3)

**Files:**
- Create: `app/extracting/dates.py`
- Test: `tests/test_extracting_dates.py`

**Interfaces:**
- Produces:
  - `DateCandidate`: `date_raw: str`, `iso: str`, `snippet: str`, `index: int`
  - `extract_date_candidates(text: str) -> list[DateCandidate]`
  - `pick_audit_report_date(candidates, *, period_end: date | None, rcept_dt: date | None) -> tuple[str | None, str, list[DateCandidate]]`  
    반환: `(iso_or_none, status, passing)`  
    status ∈ {`ok`, `not_found`, `ambiguous`}

전처리: D-3-3처럼 `compact(text)`를 `의견근거` 앞 + 마지막 `재무제표에대한경` 이후와 이어 붙인 뒤 정규식 `[0-9]{4}년[0-9]{1,2}월[0-9]{1,2}일`. snippet은 원문에서 해당 매칭 전후 40자(없으면 compact 기준). ISO는 zero-pad.

창: `period_end < iso <= rcept_dt` (당일 허용이므로 `iso <= rcept_dt`). `period_end`/`rcept_dt`가 None이면 그 쪽 비교는 생략. 통과 1개→`ok`+그 ISO, 0→`not_found`, 2+→`ambiguous`이고 ISO는 None. **후반 우선**은 통과분이 2개 이상일 때 적용하지 않는다(스펙: 2개면 고르지 않음). 창 통과가 1개일 때만 ok.

`year_end` 문자열 `(2019.12)` → `period_end=date(2019,12,31)` 헬퍼 `parse_year_end(year_end: str | None) -> date | None`. `rcept_dt` `2019.03.31` 또는 `2019-03-31` 파싱 헬퍼 `parse_rcept_dt`.

- [ ] **Step 1: 테스트** — 후보 2개 중 창 1개만 통과 / 둘 다 통과면 ambiguous / 날짜 없음
- [ ] **Step 2–4:** TDD
- [ ] **Step 5: Commit 초안** `feat(web-api): 감사보고서일 후보·창 선택 추가`

---

### Task 4: 표지·실시내용 헤더·A001 표·본문 감사인

**Files:**
- Create: `cover.py`, `activity_header.py`, `a001_section.py`, `auditor_body.py`
- Create: `app/extracting/data/auditor_names.txt` — GitHub `(D-2-2) data01.auditor.txt`를 복사. 테스트는 파일 앞 몇 줄 + fixture 문자열로 충분
- Test: `tests/test_extracting_cover_a001.py`

**Interfaces:**
- `extract_cover_period(html_or_text: str) -> FieldResult` — `기`/`期` 뒤 구간 (D-2-1)
- `extract_cover_auditor(html: str) -> FieldResult` — `p`/`td`에 `회계법인` 또는 `감사반` (D-2-2). BeautifulSoup `lxml`
- `extract_activity_header(html: str) -> tuple[str | None, str | None]` — 회사명, 결산월 헤더. `회사명`/`결산`/`사업연도` 라벨 행
- `extract_a001_current_audit(html: str) -> tuple[FieldResult, FieldResult]` — (의견칸, 감사인칸). 표 헤더에 당기/제N기. boilerplate 기본값 없음
- `extract_body_auditor(text: str, names: Sequence[str]) -> FieldResult` — D-3-1: compact 본문에서 이름 compact 매칭, **가장 뒤 위치**의 이름

- [ ] **Step 1:** HTML fixture 3종(표지 회계법인 td, 실시내용 회사명 행, A001 당기 적정/삼일 표)으로 테스트
- [ ] **Step 2–4:** TDD
- [ ] **Step 5: Commit 초안** `feat(web-api): 표지·A001표·실시내용 헤더 파서 추가`

---

### Task 5: 값 해소

**Files:**
- Create: `app/extracting/resolve.py`
- Test: `tests/test_extracting_resolve.py`

**Interfaces:**
- `normalize_firm_name(value: str | None) -> str` — 공백 제거, `주식회사`/`(주)` 제거
- `Conflict`: `TypedDict` with `field: str`, `left: str`, `right: str`, `left_source: str`, `right_source: str`
- `ResolvedAuditor`: `value`, `source`, `conflicts: list[Conflict]`
- `resolve_auditor(*, cover, a001, body, listing, report_type: str) -> ResolvedAuditor`  
  순위: cover → (A001만 a001) → body. listing은 `report_type in {F001,F002}`일 때만 호출자가 `auditor_listing`에 넣고, 이 함수의 conflicts에 넣지 않음. A001 listing 인자는 무시.
- `resolve_opinion(*, letter: FieldResult, a001: FieldResult | None) -> ...` — letter ok면 letter. 아니면 a001. 둘 다 ok이고 compact 코드가 다르면 conflict, 값은 letter.
- `corp_name_conflicts(listing: str | None, activity: str | None, a001_cover: str | None) -> list[Conflict]` — 같은 접수만 비교. listing을 유지.
- `year_end_conflicts(listing: str | None, activity: str | None, a001_cover: str | None, cover_period: str | None) -> list[Conflict]` — listing `year_end`를 바꾸지 않음.

- [ ] **Step 1:** F001 listing≠cover여도 conflict 없음, resolved는 cover. A001 cover≠a001 표면 conflict. 다른 연도 회사명 비교 함수를 호출하지 않음(같은 접수 인자만).
- [ ] **Step 2–4:** TDD
- [ ] **Step 5: Commit 초안** `feat(web-api): 감사 추출 필드 해소 규칙 추가`

---

### Task 6: 모델·리포지토리

**Files:**
- Create: `app/models/audit_report_fact.py`, `app/models/extraction_job.py`
- Create: `app/repositories/fact_repository.py`, `app/repositories/extraction_job_repository.py`
- Modify: `app/models/__init__.py` — export 추가해 `create_all`이 새 테이블을 만들게 함
- Test: `tests/test_audit_report_fact_repository.py`

**Interfaces:**
- `AuditReportFact` PK: `rcept_no` + `dcm_no` (복합). 스펙 컬럼 전부. JSON 컬럼: `audit_report_date_candidates`, `conflicts`
- `EXTRACTOR_VERSION = "audit_opinion.v1"` (`app/extracting/constants.py`)
- `ExtractionJob`: `job_id`, `status`, `extractor_id` (`audit_opinion`|`resolve_dates`), `mode` (`extract`|`resume`|`reparse`), `params` JSON, `error_message`, 시각
- `ExtractionJobLog`: catalog_job_logs와 동일 형태
- `FactRepository.upsert(fact: AuditReportFact) -> None`
- `FactRepository.get(rcept_no, dcm_no) -> AuditReportFact | None`
- `FactRepository.list_by_rcept_no(rcept_no) -> list[AuditReportFact]`
- `FactRepository.list_ambiguous_dates() -> list[AuditReportFact]`
- `ExtractionJobRepository` — `create`, `find_any_active`, `add_log`, `set_status` (catalog `JobRepository`와 같은 활성 정의 `pending`/`running`)

- [ ] **Step 1:** 메모리 SQLite `create_all` 후 upsert·조회 테스트
- [ ] **Step 2–4:** TDD
- [ ] **Step 5: Commit 초안** `feat(web-api): audit_report_facts·extraction_jobs 테이블 추가`

---

### Task 7: DART 잡 잠금 + 추출 서비스

**Files:**
- Create: `app/services/dart_job_lock.py`, `app/services/extraction_service.py`
- Modify: `app/services/catalog_service.py` — `_start_job`에서 `assert_dart_idle` 호출 (추출 running이면 409)
- Test: `tests/test_extraction_service.py`, `tests/test_catalog_service.py`에 추출 활성 시 수집 거절 케이스 1개

**Interfaces:**
- `async def assert_dart_idle(session) -> None` — catalog `find_any_active` 또는 extraction `extractor_id==audit_opinion` 활성이면 `CatalogConflict`
- `ExtractionService.start(start_date, end_date, report_types, mode) -> job_id` — DART 잠금, 잡 생성, BackgroundTasks/기존 catalog와 같이 세션메이커로 백그라운드
- `async def run_job(job_id)`:  
  1. entries를 `rcept_dt`가 기간 안이고 `is_audit_document`인 행만 로드 (EntryRepository에 `list_for_extraction(start, end, report_types)` 추가)  
  2. `group_by_dcm`  
  3. resume: facts가 있고 `fetch_status==ok`이고 mode≠reparse면 skip. reparse는 `not_found` 필드가 있는 행만 다시 fetch  
  4. leaf `viewer_url`을 `DartHttp.fetch` (테스트는 MockTransport)  
  5. `extract_blocks` 필요 시 html 문자열 파서에 직접 전달  
  6. resolve 후 upsert. `section_missing`은 의견·표지 leaf가 둘 다 없을 때  
  7. 형제 행(같은 corp_code+year_end+fs_scope, 다른 rcept_no): F001/F002 의견이 A001과 다르면 양쪽 `conflicts`에 `sibling_opinion` 추가

fetch 실패: `fetch_status=fetch_failed`. DartHttp가 차단으로 보이는 응답을 주면 `blocked` (기존 dart_http 판별 재사용 가능하면 그대로).

한 번에 문서 하나씩 커밋해 중단에도 성공분이 남게 한다.

- [ ] **Step 1:** Mock HTTP로 F001 한 문서 표지+의견 HTML → facts 1행, opinion_code unqualified. 두 번째 테스트: catalog running 중 start → CatalogConflict
- [ ] **Step 2–4:** TDD. `list_for_extraction`은 `rcept_dt`를 `YYYY.MM.DD`로 저장하는 기존 엔트리 형식에 맞춤 (`start_date`/`end_date`는 `YYYYMMDD`)
- [ ] **Step 5: Commit 초안** `feat(web-api): 감사 추출 잡과 카탈로그 DART 잠금`

---

### Task 8: Admin 추출 API · 완전성

**Files:**
- Create: `app/schemas/extract.py`, `app/api/admin/extract.py`, `app/services/completeness_service.py`
- Modify: `app/main.py` 라우터, `app/api/deps.py`
- Test: `tests/test_extract_admin_api.py`

**Interfaces:**
- `POST /admin/extract/audit-opinion` body: `start_date`, `end_date`, `report_types: list[str]`, `mode: extract|resume|reparse` (기본 extract). 202 + `job_id`. `X-Admin-Token` 필수
- `GET /admin/extract/status?job_id=`
- `GET /admin/extract/audit-opinion/completeness?start_date=&end_date=&report_type=`  
  응답: `target`, `ok`, `fetch_failed`, `blocked`, `section_missing`, `unextracted`, `ambiguous_dates`, `field_partial`  
  `field_partial`: fetch ok이지만 auditor_status/opinion_status/gaap_status/audit_report_date_status/current_period_status 중 하나라도 `ok`가 아님 (`skipped`는 부분실패에 포함)
- 같은 GET에 `status`+`cursor`+`limit`(기본 50, 최대 200)이면 `items: [{rcept_no, dcm_no}]`, `next_cursor`
- `PATCH /admin/extract/audit-opinion/{rcept_no}/{dcm_no}/date` body `{iso: str}` → `audit_report_date_override` 및 `audit_report_date`·status=`ok`·source=`override`

- [ ] **Step 1:** 토큰 없이 401. completeness fixture: entries 2문서, facts 1 ok → unextracted 1. status=unextracted 목록에 나머지
- [ ] **Step 2–4:** TDD
- [ ] **Step 5: Commit 초안** `feat(web-api): 감사 추출 Admin API와 완전성 집계`

---

### Task 9: Public GET facts

**Files:**
- Create: `app/schemas/facts.py`, `app/api/v1/facts.py`
- Modify: `app/main.py`
- Test: `tests/test_facts_api.py`

**Interfaces:**
- `GET /api/v1/disclosures/{rcp_no}/audit-facts` — 인증 없음. 행 없으면 `[]` (404 아님; 카탈로그에 공시는 있으나 미추출일 수 있음). 스키마에 resolved 필드·source·conflicts·fetch_status

- [ ] **Step 1–4:** TDD
- [ ] **Step 5: Commit 초안** `feat(web-api): 공시별 감사 추출 결과 조회 API`

---

### Task 10: 날짜 LLM 해소 잡

**Files:**
- Create: `app/ports/date_resolver.py`, `app/adapters/llm_date_resolver.py`, `app/services/date_resolver_service.py`
- Modify: `app/config.py` (`date_resolver_api_key: str = ""`, `date_resolver_model: str = "gpt-4o-mini"`, `date_resolver_prompt_version: str = "v1"`), `.env.example`
- Modify: `app/api/admin/extract.py` — `POST /admin/extract/resolve-dates`
- Test: `tests/test_date_resolver.py`

**Interfaces:**
- `class DateResolver(Protocol): async def pick_index(self, *, candidates: list[dict], period_end: str, rcept_dt: str) -> int | None`
- Mock 구현은 테스트용. LLM 어댑터는 JSON만 파싱해 `{"index": n}` 또는 `{"index": null}`. 범위 밖·파싱 실패는 None
- `DateResolverService.run(job_id)`: `list_ambiguous_dates()`, DART 잠금 **없음**, 후보 dict는 `date_raw`+`snippet`. 성공 시 `audit_report_date`, status=`ok`, source=`llm`, 모델·프롬프트·raw_response 저장. None이면 ambiguous 유지
- API 키 없으면 400 친절 한국어

- [ ] **Step 1:** mock이 1을 주면 두 후보 중 두 번째 ISO가 채워짐. -1이면 그대로 ambiguous
- [ ] **Step 2–4:** TDD
- [ ] **Step 5: Commit 초안** `feat(web-api): ambiguous 감사보고서일 LLM 해소 잡`

---

### Task 11: export 스크립트와 README

**Files:**
- Create: `scripts/export_audit_report_facts.py`
- Modify: `packages/web-api/README.md` — Admin 추출·완전성·facts GET·DATE_RESOLVER·CSV

스크립트: argparse `--database-url` 기본 설정, TSV stdout 또는 `--out`. `entries`/`disclosures`와 조인해 corp_name, year_end, rcept_dt, correction_type 포함. 최종 접수 필터 플래그는 두지 않음(스펙).

- [ ] **Step 1:** 메모리 DB fixture로 스크립트 함수 `iter_rows(session) -> Iterable[dict]` 단위 테스트 `tests/test_export_audit_report_facts.py`
- [ ] **Step 2–4:** TDD + README
- [ ] **Step 5: Commit 초안** `docs(web-api): 감사 추출 사용법과 CSV export 추가`

---

## 스펙 커버리지 (자가 검토)

| 스펙 | 작업 |
|------|------|
| selector 3유형·제외 목록 | Task 1 |
| 의견 boilerplate / GAAP other | Task 2 |
| 날짜 후보·ambiguous·창 | Task 3 |
| D-2 표지, D-4 헤더만, A001 표, D-3-1 | Task 4 |
| 해소·listing 현재명·회사명 같은 접수 | Task 5 |
| facts/jobs 스키마 | Task 6 |
| 별도 잡, DART 상호배타, resume/reparse | Task 7 |
| 완전성 API·PATCH override | Task 8 |
| Public GET | Task 9 |
| LLM 날짜 잡 | Task 10 |
| CSV export, HTML 미저장, 히트맵 없음 | Task 11·제약 |
| D-4 시간·D-5~7 | 범위 밖, 작업 없음 |
