# 추출 12묶음 진단 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현재 추출기 `fetch_status=ok` 행에서 12묶음 이상치·희귀 코드·실패 대표를 계산하고, 사람 판정을 `extraction_reviews`와 TSV로 남긴다.

**Architecture:** `app/reviewing/candidates.py`가 DB 없이 후보와 요약을 만든다. `extraction_review_service`가 facts·카탈로그를 읽어 upsert·TSV 입출력을 한다. `scripts/extraction_reviews.py`는 그 서비스의 CLI다. facts 측정 열은 쓰지 않는다.

**Tech Stack:** Python 3.11, SQLAlchemy 2, SQLite, pytest, `statistics.quantiles(..., method="inclusive")`.

## Global Constraints

- 패키지: `packages/web-api`만. 작업 디렉터리는 `packages/web-api`.
- 테스트: `.\.venv\Scripts\python.exe -m pytest <파일> -q --tb=short`. Windows에서 pytest가 통과 후 hang하면 해당 파일 테스트가 모두 통과한 뒤 hang으로 본다.
- 주석·Docstring·로그·사용자 메시지는 한국어.
- 파서·`EXTRACTOR_VERSION`·Admin 화면·원문 HTML 저장은 하지 않는다.
- `audit_report_facts`, `disclosures`, `entries`, `corps`는 읽기만 한다.
- 사분위는 `statistics.quantiles(values, n=4, method="inclusive")`. 비교 값이 30개 미만이거나 IQR이 0이면 IQR 후보를 만들지 않는다.
- 금액·시간·종속기업 수의 울타리는 0 초과 값의 `log1p`. 보고일 간격은 일수. 울타리 밖은 엄격한 `<` / `>`다.
- 접수일 창은 문자열 `20160101` 이상 `20260909` 이하(8자리 숫자만). 결산월 창은 `parse_year_end` 결과가 2016-01-31 이상 2025-12-31 이하.
- 기업–연도 그룹 키는 `corp_code`와 파싱된 결산일의 `isoformat()`이다.
- 태그 허용값: `as_written`, `real_magnitude`, `rare_but_valid`, `other`.
- 스펙: `docs/superpowers/specs/2026-09-28-extraction-review-diagnosis-design.md`.

## File map

| 파일 | 책임 |
|------|------|
| `app/models/extraction_review.py` | `extraction_reviews` 테이블 |
| `app/models/__init__.py` | 모델 등록 (`create_all`이 테이블을 보게) |
| `app/reviewing/__init__.py` | 패키지 |
| `app/reviewing/candidates.py` | 패널, 숫자, 범주, 실패, `build_candidates` |
| `app/services/extraction_review_service.py` | 적재, export, import, 잡 잠금 |
| `scripts/extraction_reviews.py` | `diagnose` / `export-tsv` / `import-tsv` |
| `scripts/export_audit_report_facts.py` | `--with-reviews` |
| `tests/test_extraction_review_model.py` | 테이블 왕복 |
| `tests/test_reviewing_candidates.py` | 순수 계산 |
| `tests/test_extraction_review_service.py` | upsert·TSV |
| `tests/test_export_audit_report_facts.py` | 소스 태그 열 |

---

### Task 1: 검토 테이블

**Files:**
- Create: `packages/web-api/app/models/extraction_review.py`
- Modify: `packages/web-api/app/models/__init__.py`
- Test: `packages/web-api/tests/test_extraction_review_model.py`

**Interfaces:**
- Consumes: `app.models.base.Base`
- Produces: `ExtractionReview` (`__tablename__ = "extraction_reviews"`). 복합 PK `rcept_no`, `dcm_no`, `bundle`, `signal`, `subject`. 나머지 열은 `extractor_version: str`, `in_research_panel: bool`, `stratum: str`, `tail: str`, `queue_order: int | None`, `raw_value: str`, `active: bool`, `verdict: str`, `tag: str`, `note: str`.

- [ ] **Step 1: Write the failing test**

`packages/web-api/tests/test_extraction_review_model.py`

```python
"""extraction_reviews 테이블 왕복."""

from __future__ import annotations

from sqlalchemy import select

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.models.extraction_review import ExtractionReview


async def test_extraction_review_roundtrip() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        session.add(
            ExtractionReview(
                rcept_no="20200331000001",
                dcm_no="11111",
                bundle="accounts",
                signal="iqr_high",
                subject="total_asset",
                extractor_version="audit_opinion.v19",
                in_research_panel=True,
                stratum="F001|separate|total_asset",
                tail="high",
                queue_order=1,
                raw_value="1000",
                active=True,
                verdict="hold",
                tag="",
                note="",
            )
        )
        await session.commit()
    async with sessionmaker() as session:
        stored = (await session.execute(select(ExtractionReview))).scalar_one()
    assert stored.verdict == "hold"
    assert stored.queue_order == 1
    await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_review_model.py -q --tb=short`

Expected: FAIL (`extraction_review` 모듈 없음)

- [ ] **Step 3: Write minimal implementation**

`packages/web-api/app/models/extraction_review.py`

```python
"""추출 진단 검토 행. 측정 facts와 분리한다."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExtractionReview(Base):
    """문서×묶음×신호×대상 하나의 판정."""

    __tablename__ = "extraction_reviews"

    rcept_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    dcm_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    bundle: Mapped[str] = mapped_column(String(32), primary_key=True)
    signal: Mapped[str] = mapped_column(String(32), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True, default="")
    extractor_version: Mapped[str] = mapped_column(String(32), nullable=False)
    in_research_panel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stratum: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    tail: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    queue_order: Mapped[int | None] = mapped_column(Integer)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False, default="hold")
    tag: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
```

`app/models/__init__.py`에 import와 `__all__` 항목 `ExtractionReview`를 추가한다.

```python
from app.models.extraction_review import ExtractionReview
```

`__all__` 리스트에 `"ExtractionReview"`를 알파벳 순서로 `ExtractionJobLog` 다음에 넣는다.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_review_model.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/models/extraction_review.py packages/web-api/app/models/__init__.py packages/web-api/tests/test_extraction_review_model.py
git commit -m "feat(web-api): 추출 진단 판정을 담는 extraction_reviews 테이블을 둔다."
```

---

### Task 2: 숫자 후보

**Files:**
- Create: `packages/web-api/app/reviewing/__init__.py`
- Create: `packages/web-api/app/reviewing/candidates.py`
- Test: `packages/web-api/tests/test_reviewing_candidates.py`

**Interfaces:**
- Consumes: `statistics.quantiles`, `math.log1p`, `parse_year_end`
- Produces:
  - `FactView` — 아래 필드. 나열되지 않은 상태는 `str | None = None`, entry는 `str | None = None`, JSON은 `object = None`.
    `rcept_no: str`, `dcm_no: str`, `source_report_type: str`, `fs_scope: str`, `fetch_status: str = "ok"`, `rcept_dt: str = ""`, `corp_code: str | None = None`, `year_end: str | None = None`, `corp_cls: str | None = None`, `hours`, `accounts`, `conflicts`, `subsidiary_count: int | None = None`, `subsidiary_status`, `audit_report_date`, `audit_report_date_status`, `hours_status`, `accounts_status`, 그리고 묶음 status·코드·entry 필드는 Task 4·5에서 같은 dataclass에 이미 있어야 하므로 이 태스크에서 한 번에 선언한다.
  - `ReviewCandidate` — `rcept_no`, `dcm_no`, `bundle`, `signal`, `subject`, `stratum`, `tail`, `queue_order: int | None`, `raw_value`, `in_research_panel: bool`. 모두 키워드 전용 frozen dataclass.
  - `SummaryRow` — `section: str`, `key: str`, `n: int`, `detail: str`
  - `quartile_bounds(scale_values: list[float]) -> tuple[float, float, float, float] | None` — `(q1, q3, low, high)`. `len < 30` 또는 `q3 - q1 <= 0`이면 `None`.
  - `numeric_candidates(facts: Sequence[FactView], panel_ids: set[tuple[str, str]]) -> tuple[list[ReviewCandidate], list[SummaryRow]]`

`FactView` 필드는 이 태스크에서 확정한다. 이후 태스크는 필드를 추가하지 말고 이 목록을 쓴다.

```python
@dataclass(frozen=True)
class FactView:
    rcept_no: str
    dcm_no: str
    source_report_type: str
    fs_scope: str
    fetch_status: str = "ok"
    rcept_dt: str = ""
    corp_code: str | None = None
    year_end: str | None = None
    corp_cls: str | None = None
    auditor_status: str | None = None
    opinion_status: str | None = None
    gaap_status: str | None = None
    audit_report_date_status: str | None = None
    current_period_status: str | None = None
    hours_status: str | None = None
    activities_status: str | None = None
    communications_status: str | None = None
    accounts_status: str | None = None
    icfr_status: str | None = None
    going_concern_status: str | None = None
    subsidiary_status: str | None = None
    opinion_code: str | None = None
    gaap_code: str | None = None
    icfr_engagement: str | None = None
    icfr_opinion_code: str | None = None
    auditor_resolved: str | None = None
    going_concern: int | None = None
    subsidiary_count: int | None = None
    audit_report_date: str | None = None
    hours: object = None
    accounts: object = None
    conflicts: object = None
    cover_entry_id: str | None = None
    opinion_entry_id: str | None = None
    a001_opinion_entry_id: str | None = None
    a001_cover_entry_id: str | None = None
    activity_entry_id: str | None = None
    bs_entry_id: str | None = None
    is_entry_id: str | None = None
    icfr_entry_id: str | None = None
    notes_entry_id: str | None = None
    a001_affiliate_entry_id: str | None = None
```

- [ ] **Step 1: Write the failing test**

`tests/test_reviewing_candidates.py`에 아래를 넣는다. 헬퍼 `view`는 같은 파일 상단.

```python
"""진단 후보 순수 계산."""

from __future__ import annotations

import math

from app.reviewing.candidates import (
    FactView,
    numeric_candidates,
    quartile_bounds,
)


def view(index: int, **overrides: object) -> FactView:
    """번호만 다른 최소 행."""
    values: dict[str, object] = {
        "rcept_no": f"202003{index:08d}",
        "dcm_no": "1",
        "source_report_type": "F001",
        "fs_scope": "separate",
    }
    values.update(overrides)
    return FactView(**values)  # type: ignore[arg-type]


def test_quartile_bounds_none_when_short_or_flat() -> None:
    assert quartile_bounds([1.0] * 29) is None
    assert quartile_bounds([math.log1p(10.0)] * 30) is None


def test_numeric_flags_hours_forbidden_and_asset_tail() -> None:
    mass = [
        view(
            index,
            hours=[{"role": "total", "metric": "audit", "period": "current", "value": 100}],
            hours_status="ok",
            accounts=[
                {"account": "total_asset", "period": "current", "status": "ok", "value_won": 1_000},
                {"account": "net_income", "period": "current", "status": "ok", "value_won": -5},
                {"account": "total_equity", "period": "current", "status": "ok", "value_won": -5},
            ],
            accounts_status="ok",
        )
        for index in range(30)
    ]
    huge = view(
        30,
        hours=[{"role": "total", "metric": "audit", "period": "current", "value": 0}],
        hours_status="ok",
        accounts=[
            {"account": "total_asset", "period": "current", "status": "ok", "value_won": -1},
            {"account": "current_liability", "period": "current", "status": "ok", "value_won": 0},
        ],
        accounts_status="ok",
    )
    missing = view(31, hours=[], hours_status="ok")
    duplicate = view(
        32,
        hours=[
            {"role": "total", "metric": "audit", "period": "current", "value": 1},
            {"role": "total", "metric": "audit", "period": "current", "value": 2},
        ],
        hours_status="ok",
    )
    panel = {("20200300000030", "1")}
    candidates, summary = numeric_candidates([*mass, huge, missing, duplicate], panel)
    signals = {(item.rcept_no, item.signal, item.subject) for item in candidates}
    assert ("20200300000030", "hours_nonpositive", "audit_current_total") in signals
    assert ("20200300000030", "account_negative", "total_asset") in signals
    assert not any(item.subject == "net_income" and item.signal == "account_negative" for item in candidates)
    assert not any(item.subject == "total_equity" and item.signal == "account_negative" for item in candidates)
    assert not any(item.subject == "current_liability" and item.signal == "account_negative" for item in candidates)
    assert ("20200300000031", "hours_total_missing", "audit_current_total") in signals
    assert not any(item.rcept_no == "20200300000032" for item in candidates)
    assert any(row.section == "skip" and row.key == "hours_total_duplicate" and row.n == 1 for row in summary)
    assert not any(
        item.signal == "iqr_high" and item.subject == "total_asset" and item.rcept_no == "20200300000030"
        for item in candidates
    )
```

`rcept_no` 자릿수: `f"202003{index:08d}"`는 index 30이면 `20200300000030`이다. 패널 집합의 키와 같아야 한다. index 0은 `20200300000000`.

추가 테스트 두 개를 같은 파일에 넣는다.

```python
def test_unit_missing_and_subsidiary_and_date() -> None:
    rows = [
        view(
            index,
            source_report_type="F002",
            fs_scope="consolidated",
            subsidiary_status="ok",
            subsidiary_count=3,
            audit_report_date_status="ok",
            audit_report_date="2020-03-15",
            year_end="2020.02",
            accounts=[
                {
                    "account": "total_asset",
                    "period": "current",
                    "status": "ok",
                    "value_won": None,
                }
            ],
            accounts_status="ok",
        )
        for index in range(1, 31)
    ]
    zero_sub = view(
        40,
        source_report_type="F002",
        fs_scope="consolidated",
        subsidiary_status="ok",
        subsidiary_count=0,
    )
    negative_sub = view(
        41,
        source_report_type="F002",
        fs_scope="consolidated",
        subsidiary_status="ok",
        subsidiary_count=-1,
    )
    early = view(
        42,
        audit_report_date_status="ok",
        audit_report_date="2020-01-31",
        year_end="2020.01",
        fs_scope="separate",
    )
    candidates, _summary = numeric_candidates([*rows, zero_sub, negative_sub, early], set())
    signals = {(item.signal, item.subject, item.rcept_no) for item in candidates}
    assert ("unit_missing", "total_asset", "20200300000001") in signals
    assert ("subsidiary_negative", "subsidiary_count", "20200300000041") in signals
    assert not any(item.signal == "subsidiary_negative" and item.rcept_no.endswith("40") for item in candidates)
    assert ("date_nonpositive", "lag_days", "20200300000042") in signals


def test_panel_queue_order_is_extreme_five() -> None:
    facts = []
    panel: set[tuple[str, str]] = set()
    for index in range(30):
        if index == 0:
            amount = 1
        elif index == 29:
            amount = 10**9
        else:
            amount = 1_000
        fact = view(
            index,
            accounts=[
                {
                    "account": "total_asset",
                    "period": "current",
                    "status": "ok",
                    "value_won": amount,
                }
            ],
            accounts_status="ok",
            corp_code="C",
        )
        facts.append(fact)
        panel.add((fact.rcept_no, fact.dcm_no))
    facts.append(
        view(
            80,
            accounts=[
                {
                    "account": "total_asset",
                    "period": "current",
                    "status": "ok",
                    "value_won": 10**12,
                }
            ],
            accounts_status="ok",
        )
    )
    candidates, _summary = numeric_candidates(facts, panel)
    highs = [
        item
        for item in candidates
        if item.signal == "iqr_high" and item.subject == "total_asset" and item.queue_order == 1
    ]
    assert len(highs) == 1
    assert highs[0].in_research_panel is True
    assert highs[0].tail == "high"
    lows = [
        item
        for item in candidates
        if item.signal == "iqr_low" and item.subject == "total_asset" and item.queue_order == 1
    ]
    assert len(lows) == 1
    assert lows[0].in_research_panel is True
    outsider = [
        item
        for item in candidates
        if item.rcept_no == "20200300000080" and item.signal == "iqr_high"
    ]
    assert outsider[0].queue_order is None
    assert outsider[0].in_research_panel is False
```

패널 28건은 자산 1000, 한 건은 1, 한 건은 10억이다. 순번 1인 high는 10억 패널 행이고, 순번 1인 low는 1인 패널 행이다. 1조 행은 패널이 아니므로 `queue_order`가 없다.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reviewing_candidates.py -q --tb=short`

Expected: FAIL (모듈 없음)

- [ ] **Step 3: Write minimal implementation**

`app/reviewing/__init__.py`는 빈 docstring `"""추출 진단 후보."""`만 둔다.

`app/reviewing/candidates.py`에 `FactView`, `ReviewCandidate`, `SummaryRow`, `quartile_bounds`, `numeric_candidates`를 둔다. 규칙:

- `fetch_status != "ok"`인 행은 무시한다.
- 시간 칸은 `role=total`, `metric=audit`, `period=current`. 리스트가 아니면 summary `skip/hours_not_list`. 0개면 `hours_total_missing`. 2개 이상이면 후보는 없고 `skip/hours_total_duplicate`. 값이 숫자가 아니면 missing과 같다. `bool`은 숫자가 아니다. `value <= 0`이면 `hours_nonpositive`이고 log1p 분포에 넣지 않는다.
- 계정은 `period=current`이고 `status=ok`인 dict만. `accounts`가 리스트가 아니면 `skip/accounts_not_list`이고 계정 신호는 없다. `value_won is None`이면 `unit_missing`. 0 미만이고 계정이 `total_asset`, `current_asset`, `total_liability`, `current_liability`이면 `account_negative`. 0과 음수는 log1p 분포에 넣지 않는다. `value_won`이 숫자가 아니면 `unit_missing`.
- 종속기업은 `fs_scope=consolidated`이고 `subsidiary_status=ok`이며 `subsidiary_count`가 `bool`이 아닌 `int`일 때만. `< 0`이면 `subsidiary_negative`. `0`은 무시. `> 0`만 분포. 층은 `{source_report_type}|*|subsidiary_count`.
- 간격은 `audit_report_date_status=ok`이고 `date.fromisoformat(audit_report_date)`와 `parse_year_end(year_end)`가 될 때만. 결산일이나 ISO가 없으면 후보 없이 `skip/lag_skipped` 1건. `lag = (report - end).days`. `<= 0`이면 `date_nonpositive`. `> 0`만 일수 IQR. 층은 `{유형}|{fs_scope}|lag_days`.
- 시간 층 `{유형}|{fs_scope}|audit_current_total`. 계정 층 `{유형}|{fs_scope}|{account}`.
- 분포는 층마다 모은 뒤 `quartile_bounds`를 호출한다. 금액·시간·건수는 넣기 전에 `math.log1p`. 간격은 일수 그대로. `None`이면 summary `stratum`에 `건너뜀 n<30` 또는 `건너뜀 iqr_zero`와 비교 개수. 울타리가 있으면 `Q1` `Q3` `IQR` `후보` 건수를 detail에 적는다. 눈금이 `low`보다 작으면 `iqr_low`, `high`보다 크면 `iqr_high`.
- `subject`는 시간 `audit_current_total`, 계정 코드, 종속 `subsidiary_count`, 간격 `lag_days`. `raw_value`는 숫자의 `str`.
- 패널 id에 있는 IQR 행만 `in_research_panel=True`이고, 꼬리별로 눈금이 극단인 순서(low는 작은 눈금, high는 큰 눈금)로 `queue_order` 1부터. 비패널 IQR은 `queue_order=None`, `in_research_panel=False`. 금지 값 행은 패널 여부를 표시하고 `tail=""` , `queue_order=None`.
- 같은 자연키 후보는 한 번만. 순서는 입력 순을 유지한다.

`quartile_bounds`:

```python
def quartile_bounds(scale_values: list[float]) -> tuple[float, float, float, float] | None:
    """(q1, q3, low, high). 30개 미만이거나 IQR이 0이면 None."""
    if len(scale_values) < 30:
        return None
    q1, _q2, q3 = statistics.quantiles(scale_values, n=4, method="inclusive")
    iqr = q3 - q1
    if iqr <= 0:
        return None
    fence = 1.5 * iqr
    return (q1, q3, q1 - fence, q3 + fence)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reviewing_candidates.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/reviewing/__init__.py packages/web-api/app/reviewing/candidates.py packages/web-api/tests/test_reviewing_candidates.py
git commit -m "feat(web-api): 감사시간·계정·종속기업·보고일 간격의 진단 후보를 계산한다."
```

---

### Task 3: 연구 패널

**Files:**
- Modify: `packages/web-api/app/reviewing/candidates.py`
- Test: `packages/web-api/tests/test_reviewing_candidates.py`

**Interfaces:**
- Consumes: `FactView`, `parse_year_end`
- Produces: `select_panel_ids(facts: Sequence[FactView]) -> set[tuple[str, str]]` — `(rcept_no, dcm_no)`

- [ ] **Step 1: Write the failing test**

```python
from app.reviewing.candidates import select_panel_ids


def test_panel_prefers_consolidated_then_f_then_latest() -> None:
    rows = [
        view(1, corp_code="C", year_end="2019.12", rcept_dt="20200301", fs_scope="separate", source_report_type="F001"),
        view(2, corp_code="C", year_end="2019.12", rcept_dt="20200302", fs_scope="consolidated", source_report_type="A001"),
        view(3, corp_code="C", year_end="2019.12", rcept_dt="20200303", fs_scope="consolidated", source_report_type="F002"),
        view(4, corp_code="C", year_end="2019.12", rcept_dt="20200304", fs_scope="consolidated", source_report_type="F002"),
        view(5, corp_code=None, year_end="2019.12", rcept_dt="20200304", fs_scope="separate", source_report_type="F001"),
        view(6, corp_code="D", year_end="2015.12", rcept_dt="20160115", fs_scope="separate", source_report_type="F001"),
        view(7, corp_code="E", year_end="2020.12", rcept_dt="20261001", fs_scope="separate", source_report_type="F001"),
        view(8, corp_code="F", year_end="2020.06", rcept_dt="20200701", fs_scope="unknown", source_report_type="F001"),
    ]
    assert select_panel_ids(rows) == {("20200300000004", "1")}
```

`view`의 `rcept_no`는 `f"202003{index:08d}"`라 index 4는 `20200300000004`다. 결산 `2019.12`는 2019-12-31로 창 안이다. `20261001`은 접수 창 밖이다. `unknown`만 있으면 패널이 아니다.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reviewing_candidates.py::test_panel_prefers_consolidated_then_f_then_latest -q --tb=short`

Expected: FAIL (`select_panel_ids` 없음)

- [ ] **Step 3: Write minimal implementation**

`select_panel_ids`:

- `fetch_status != "ok"` 제외.
- `corp_code`가 없으면 제외.
- `parse_year_end`가 `None`이거나 2016-01-31 미만 또는 2025-12-31 초과면 제외.
- `rcept_dt`가 8자리 숫자가 아니거나 `20160101` 미만 또는 `20260909` 초과면 제외.
- `fs_scope`가 `consolidated` 또는 `separate`가 아니면 제외.
- 그룹 키 `(corp_code, year_end.isoformat())`.
- 그룹에 연결이 있으면 연결만. 없고 별도가 있으면 별도만. 둘 다 없으면 그 그룹은 패널 없음.
- 남은 행에 `source_report_type`이 `F001` 또는 `F002`인 행이 있으면 A001을 뺀다.
- `max(..., key=lambda row: (row.rcept_dt, row.rcept_no, row.dcm_no))` 한 행의 `(rcept_no, dcm_no)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reviewing_candidates.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/reviewing/candidates.py packages/web-api/tests/test_reviewing_candidates.py
git commit -m "feat(web-api): 진단용 연구 패널 문서를 기업-연도마다 하나 고른다."
```

---

### Task 4: 범주 빈도

**Files:**
- Modify: `packages/web-api/app/reviewing/candidates.py`
- Test: `packages/web-api/tests/test_reviewing_candidates.py`

**Interfaces:**
- Consumes: `FactView`, `ReviewCandidate`, `SummaryRow`, `select_panel_ids`는 호출하지 않는다. 패널 집합을 인자로 받는다.
- Produces: `categorical_candidates(facts: Sequence[FactView], panel_ids: set[tuple[str, str]]) -> tuple[list[ReviewCandidate], list[SummaryRow]]`

- [ ] **Step 1: Write the failing test**

```python
from app.reviewing.candidates import categorical_candidates


def test_rare_code_and_invalid_auditor() -> None:
    rows = [
        view(index, opinion_status="ok", opinion_code="unqualified", auditor_status="ok", auditor_resolved="삼일회계법인")
        for index in range(99)
    ]
    rare = view(100, opinion_status="ok", opinion_code="adverse", auditor_status="ok", auditor_resolved="A")
    blank = view(101, opinion_status="ok", opinion_code="unqualified", auditor_status="ok", auditor_resolved="  ")
    panel = {(rare.rcept_no, rare.dcm_no)}
    candidates, summary = categorical_candidates([*rows, rare, blank], panel)
    rare_rows = [item for item in candidates if item.signal == "rare_code"]
    assert {item.subject for item in rare_rows} == {"adverse"}
    assert rare_rows[0].queue_order == 1
    assert rare_rows[0].in_research_panel is True
    assert rare_rows[0].stratum == "*|*|opinion"
    invalid = [item for item in candidates if item.signal == "auditor_invalid"]
    assert {item.rcept_no for item in invalid} == {rare.rcept_no, blank.rcept_no}
    assert any(row.section == "category" and row.key == "opinion|unqualified" for row in summary)
    assert not any(item.signal == "rare_code" and item.bundle == "auditor" for item in candidates)
```

99 대 1이면 `adverse` 비율은 1/100 = 1%가 아니라 1/101 < 1%다. `unqualified`는 100/101 > 1%라 후보가 아니다.

대표가 5건을 넘지 않는 테스트:

```python
def test_rare_representatives_stop_at_five_panel() -> None:
    rows = [view(index, gaap_status="ok", gaap_code="k-ifrs") for index in range(200)]
    rares = []
    panel: set[tuple[str, str]] = set()
    for index in range(210, 220):
        fact = view(
            index,
            gaap_status="ok",
            gaap_code="other",
            rcept_dt=f"202003{index:02d}",
            corp_code="C",
        )
        rares.append(fact)
        if index >= 215:
            panel.add((fact.rcept_no, fact.dcm_no))
    candidates, _summary = categorical_candidates([*rows, *rares], panel)
    picked = [item for item in candidates if item.signal == "rare_code" and item.subject == "other"]
    assert len(picked) == 5
    assert all(item.in_research_panel for item in picked)
```

패널이 5개(215–219)이므로 5건만. 비패널 5건(210–214)은 저장하지 않는다.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reviewing_candidates.py::test_rare_code_and_invalid_auditor tests/test_reviewing_candidates.py::test_rare_representatives_stop_at_five_panel -q --tb=short`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`categorical_candidates`:

- 의견 `opinion_code` / `opinion_status`, GAAP `gaap_code` / `gaap_status`, 계속기업은 `going_concern`을 `str`로, 상태가 `None`이면 코드 `""`. 상태 필드 `going_concern_status`.
- 내부회계는 `icfr_status=="ok"`일 때 `f"{icfr_engagement or ''}/{icfr_opinion_code or ''}"`.
- 분모는 그 상태 `ok` 행 수. summary `section=category`, `key=f"{bundle}|{code}"`, `n`은 건수, `detail`은 `비율 {n/denom:.6f}`.
- `n / denom < 0.01`인 코드만 `signal=rare_code`, `bundle`은 위 네 개, `subject`는 코드, `stratum=*|*|{bundle}`, `tail=""`.
- 대표: 그 코드를 가진 ok 행 중 `panel_ids`에 있으면 그 집합, 한 건도 없으면 비패널. 정렬 `rcept_dt`, `rcept_no`, `dcm_no` 내림차순 후 5건. `queue_order`는 1부터. 패널에서 뽑으면 `in_research_panel=True`.
- 감사인은 `auditor_status=="ok"`만. summary `section=category`, `key=auditor|{name}` 건수 내림차순을 위해 이름별 건수를 남긴다. `rare_code`로는 넣지 않는다.
- `auditor_invalid`: 공백을 뺀 이름이 없거나 길이 2 미만이거나 `가`–`힣`이 없으면 후보. `subject`는 공백을 뺀 이름(없으면 `""`). `bundle=auditor`, `stratum=*|*|auditor`. 같은 `subject`끼리 위와 같은 5건 대표.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reviewing_candidates.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/reviewing/candidates.py packages/web-api/tests/test_reviewing_candidates.py
git commit -m "feat(web-api): 드문 코드와 형식이 깨진 감사인만 검토 후보로 올린다."
```

---

### Task 5: 실패 대표

**Files:**
- Modify: `packages/web-api/app/reviewing/candidates.py`
- Test: `packages/web-api/tests/test_reviewing_candidates.py`

**Interfaces:**
- Consumes: `classify_outcome`, `icfr_period_year`, `status_attr`, `FactView`
- Produces: `failure_candidates(facts: Sequence[FactView], panel_ids: set[tuple[str, str]]) -> tuple[list[ReviewCandidate], list[SummaryRow]]`

- [ ] **Step 1: Write the failing test**

```python
from app.reviewing.candidates import failure_candidates


def test_failure_groups_skip_expected_missing_and_cap_panel() -> None:
    listed = [
        view(
            index,
            source_report_type="F001",
            fs_scope="separate",
            icfr_status="skipped",
            corp_cls="Y",
            year_end="2024.12",
            rcept_dt=f"202501{index:02d}",
            corp_code="C",
            conflicts=[],
        )
        for index in range(1, 8)
    ]
    unlisted = view(
        20,
        source_report_type="F001",
        fs_scope="separate",
        icfr_status="skipped",
        corp_cls="E",
        year_end="2024.12",
        conflicts=[],
    )
    panel = {(row.rcept_no, row.dcm_no) for row in listed[:5]}
    candidates, summary = failure_candidates([*listed, unlisted], panel)
    assert all(item.bundle == "icfr" and item.signal == "fail" for item in candidates)
    assert len(candidates) == 5
    assert all(item.in_research_panel for item in candidates)
    assert candidates[0].subject == "skipped|missing=1|conflicts=0"
    assert not any(item.rcept_no == unlisted.rcept_no for item in candidates)
    assert any(row.section == "failure" and row.n == 7 for row in summary)


def test_failure_uses_non_panel_when_panel_is_empty() -> None:
    rows = [
        view(
            index,
            source_report_type="F001",
            fs_scope="separate",
            opinion_status="not_found",
            conflicts=[],
        )
        for index in range(6)
    ]
    candidates, _summary = failure_candidates(rows, set())
    opinion = [item for item in candidates if item.bundle == "opinion" and item.signal == "fail"]
    assert len(opinion) == 5
    assert all(item.in_research_panel is False for item in opinion)
```

상장 F001 `skipped`는 실패다. 비상장 F001 `skipped`는 `expected_missing`이라 후보가 아니다. 실패 7건 중 패널 5건만 저장한다. entry가 모두 비어 있으므로 `missing=1`. `conflicts=[]`이면 `conflicts=0`.

`rcept_dt=f"202501{index:02d}"`는 index 1이면 `20250101`로 8자리다.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reviewing_candidates.py::test_failure_groups_skip_expected_missing_and_cap_panel -q --tb=short`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`ENTRY_FIELDS`:

```python
ENTRY_FIELDS: dict[str, tuple[str, ...]] = {
    "auditor": ("cover_entry_id", "opinion_entry_id", "a001_opinion_entry_id"),
    "opinion": ("opinion_entry_id", "a001_opinion_entry_id"),
    "gaap": ("cover_entry_id", "opinion_entry_id"),
    "audit_report_date": ("opinion_entry_id",),
    "current_period": ("cover_entry_id", "a001_cover_entry_id"),
    "hours": ("activity_entry_id",),
    "activities": ("activity_entry_id",),
    "communications": ("activity_entry_id",),
    "accounts": ("bs_entry_id", "is_entry_id"),
    "icfr": ("icfr_entry_id",),
    "going_concern": ("opinion_entry_id",),
    "subsidiary": ("notes_entry_id", "a001_affiliate_entry_id"),
}
```

각 묶음에 `status_attr`로 상태를 읽고 `classify_outcome`에 `fs_scope`, `status`, `hours_status`, `activities_status`, `report_type=source_report_type`, `corp_cls`, `period_year=icfr_period_year(year_end, rcept_dt)`를 넘긴다. 결과가 `fail`일 때만 그룹에 넣는다.

`missing`은 해당 entry가 모두 `None` 또는 `strip()` 후 빈 문자열일 때 1. `conflicts`가 `list`가 아니면 0이고 summary `skip/conflicts_not_list`에 1을 더한다. 비어 있지 않은 list면 1.

`subject = f"{status}|missing={missing}|conflicts={flag}"`. `status is None`이면 `"None"`.

summary `section=failure`, `key=f"{bundle}|{subject}"`, `n`은 그룹 전체, `detail`은 `패널 {n_panel} 대표 {n_rep}`.

대표 선정은 Task 4와 같다. `signal=fail`, `stratum=*|*|{bundle}`, `tail=""`, `raw_value`는 `subject`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reviewing_candidates.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/reviewing/candidates.py packages/web-api/tests/test_reviewing_candidates.py
git commit -m "feat(web-api): 실패 칸을 상태와 섹션 힌트로 묶어 대표만 남긴다."
```

---

### Task 6: 후보 조립

**Files:**
- Modify: `packages/web-api/app/reviewing/candidates.py`
- Test: `packages/web-api/tests/test_reviewing_candidates.py`

**Interfaces:**
- Consumes: `select_panel_ids`, `numeric_candidates`, `categorical_candidates`, `failure_candidates`
- Produces:
  - `build_candidates(facts: Sequence[FactView]) -> tuple[list[ReviewCandidate], list[SummaryRow]]`
  - `format_summary(row: SummaryRow) -> str`

- [ ] **Step 1: Write the failing test**

```python
from app.reviewing.candidates import build_candidates, format_summary


def test_build_candidates_marks_panel_and_formats_korean() -> None:
    fact = view(
        1,
        corp_code="C",
        year_end="2019.12",
        rcept_dt="20200331",
        fs_scope="separate",
        source_report_type="F001",
        hours_status="not_found",
        activity_entry_id=None,
        conflicts=[],
    )
    candidates, summary = build_candidates([fact])
    fails = [item for item in candidates if item.signal == "fail" and item.bundle == "hours"]
    assert len(fails) == 1
    assert fails[0].in_research_panel is True
    text = "\n".join(format_summary(row) for row in summary)
    assert "실패" in text
    assert "hours" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reviewing_candidates.py::test_build_candidates_marks_panel_and_formats_korean -q --tb=short`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`build_candidates`는 `panel = select_panel_ids(facts)`를 구한 뒤 `numeric_candidates`, `categorical_candidates`, `failure_candidates`의 후보와 summary를 그 순서로 이어 붙인다. 각 함수가 `panel_ids`로 `in_research_panel`을 채운다.

`format_summary`:

- `section=="stratum"` → `층 {key} 비교 {n}건 {detail}`
- `section=="failure"` → `실패 {key} 전체 {n}건 {detail}`
- `section=="category"` → `범주 {key} {n}건 {detail}`
- `section=="skip"` → `건너뜀 {key} {n}건`
- 그 외 → `{section} {key} {n} {detail}`

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reviewing_candidates.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/reviewing/candidates.py packages/web-api/tests/test_reviewing_candidates.py
git commit -m "feat(web-api): 패널 표시를 붙인 진단 후보와 한글 요약을 한 번에 만든다."
```

---

### Task 7: diagnose 적재

**Files:**
- Create: `packages/web-api/app/services/extraction_review_service.py`
- Test: `packages/web-api/tests/test_extraction_review_service.py`

**Interfaces:**
- Consumes: `FactView`, `build_candidates`, `format_summary`, `ExtractionReview`, `AuditReportFact`, `Disclosure`, `Corp`, `ExtractionJob`, `EXTRACTOR_VERSION`
- Produces:
  - `class ExtractionReviewError(Exception)`
  - `async def diagnose(session: AsyncSession) -> list[SummaryRow]`
  - `def fact_to_view(fact: AuditReportFact, disclosure: Disclosure | None, corp: Corp | None) -> FactView`

- [ ] **Step 1: Write the failing test**

서비스 테스트는 메모리 SQLite에 fact·disclosure·corp·job을 넣는다. `AuditReportFact` 최소 인자: `rcept_no`, `dcm_no`, `source_report_type`, `fs_scope`, `fetch_status`, `extractor_version`.

```python
"""진단 적재·TSV."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.extracting.constants import EXTRACTOR_VERSION
from app.models.audit_report_fact import AuditReportFact
from app.models.extraction_job import ExtractionJob
from app.models.extraction_review import ExtractionReview
from app.services.extraction_review_service import ExtractionReviewError, diagnose


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def _fact(**overrides: object) -> AuditReportFact:
    values: dict[str, object] = {
        "rcept_no": "20200331000001",
        "dcm_no": "11111",
        "source_report_type": "F001",
        "fs_scope": "separate",
        "fetch_status": "ok",
        "extractor_version": EXTRACTOR_VERSION,
        "hours_status": "not_found",
        "conflicts": [],
    }
    values.update(overrides)
    return AuditReportFact(**values)  # type: ignore[arg-type]


async def test_diagnose_inserts_hold_and_does_not_touch_facts(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        await session.commit()
    async with sessionmaker_fixture() as session:
        await diagnose(session)
        await session.commit()
        fact = (await session.execute(select(AuditReportFact))).scalar_one()
        review = (await session.execute(select(ExtractionReview))).scalars().all()
    assert fact.hours_status == "not_found"
    assert any(row.verdict == "hold" and row.signal == "fail" for row in review)


async def test_diagnose_resets_verdict_when_value_changes(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        await session.commit()
    async with sessionmaker_fixture() as session:
        await diagnose(session)
        await session.commit()
        row = (await session.execute(select(ExtractionReview))).scalars().first()
        assert row is not None
        row.verdict = "source"
        row.tag = "as_written"
        row.note = "원문"
        row.raw_value = "stale"
        await session.commit()
    async with sessionmaker_fixture() as session:
        await diagnose(session)
        await session.commit()
        row = (await session.execute(select(ExtractionReview))).scalars().first()
    assert row is not None
    assert row.verdict == "hold"
    assert row.tag == ""
    assert row.note.startswith("이전 판정=source; 이전 태그=as_written; 이전 값=stale")


async def test_diagnose_keeps_verdict_when_raw_value_matches(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        await session.commit()
    async with sessionmaker_fixture() as session:
        await diagnose(session)
        await session.commit()
        row = (
            await session.execute(
                select(ExtractionReview).where(ExtractionReview.signal == "fail")
            )
        ).scalars().first()
        assert row is not None
        row.verdict = "logic"
        row.note = "파서"
        await session.commit()
    async with sessionmaker_fixture() as session:
        await diagnose(session)
        await session.commit()
        row = (
            await session.execute(
                select(ExtractionReview).where(ExtractionReview.signal == "fail")
            )
        ).scalars().first()
    assert row is not None
    assert row.verdict == "logic"
    assert row.note == "파서"
    assert row.active is True


async def test_diagnose_deactivates_missing_candidate(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(
            ExtractionReview(
                rcept_no="20200331000001",
                dcm_no="11111",
                bundle="hours",
                signal="fail",
                subject="not_found|missing=1|conflicts=0",
                extractor_version=EXTRACTOR_VERSION,
                in_research_panel=False,
                stratum="*|*|hours",
                tail="",
                raw_value="not_found|missing=1|conflicts=0",
                active=True,
                verdict="logic",
                tag="",
                note="",
            )
        )
        session.add(_fact(hours_status="ok", hours=[]))
        await session.commit()
    async with sessionmaker_fixture() as session:
        await diagnose(session)
        await session.commit()
        rows = (await session.execute(select(ExtractionReview))).scalars().all()
    failed = [row for row in rows if row.signal == "fail"]
    missing = [row for row in rows if row.signal == "hours_total_missing"]
    assert len(failed) == 1
    assert failed[0].active is False
    assert failed[0].verdict == "logic"
    assert len(missing) == 1
    assert missing[0].active is True


async def test_diagnose_refuses_empty_population(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(
            ExtractionReview(
                rcept_no="x",
                dcm_no="y",
                bundle="hours",
                signal="fail",
                subject="s",
                extractor_version=EXTRACTOR_VERSION,
                in_research_panel=False,
                stratum="",
                tail="",
                raw_value="",
                active=True,
                verdict="hold",
                tag="",
                note="",
            )
        )
        await session.commit()
    async with sessionmaker_fixture() as session:
        with pytest.raises(ExtractionReviewError, match="현재 추출기"):
            await diagnose(session)
        await session.commit()
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.active is True


async def test_diagnose_blocks_when_extraction_job_is_active(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        session.add(
            ExtractionJob(
                job_id="job-1",
                status="running",
                extractor_id="audit_opinion",
                mode="extract",
                params={},
            )
        )
        await session.commit()
    async with sessionmaker_fixture() as session:
        with pytest.raises(ExtractionReviewError, match="추출"):
            await diagnose(session)
```

`hours_status=ok`이고 `hours=[]`이면 `hours_total_missing` 후보가 생기고, 기존 `fail` 행은 이번 후보에 없으므로 `active=False`다. `ok` + 빈 hours는 missing 후보이므로 fail 행만 꺼진다.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_review_service.py -q --tb=short`

Expected: FAIL (서비스 모듈 없음)

- [ ] **Step 3: Write minimal implementation**

`fact_to_view`는 `FactView` 필드마다 `getattr(fact, name)`을 복사하고, disclosure가 있으면 `corp_code`, `year_end`, `rcept_dt`, corp가 있으면 `corp_cls`를 덮어쓴다. disclosure가 없으면 `rcept_dt=""`.

`diagnose`:

1. `ExtractionJob.status.in_(("pending", "running"))` 행이 있으면 `ExtractionReviewError("추출 잡이 진행 중이라 진단을 시작하지 않습니다.")`.
2. `fetch_status=="ok"`이고 `extractor_version==EXTRACTOR_VERSION`인 fact를 disclosure·corp와 outer join해 `FactView` 목록을 만든다. 0건이면 `ExtractionReviewError("현재 추출기 ok 행이 없습니다.")`를 검토 행을 바꾸기 전에 던진다.
3. `build_candidates` 결과로 자연키 `(rcept_no, dcm_no, bundle, signal, subject)` upsert.
   - 없고 신규: `verdict=hold`, `tag=""`, `note=""`, `active=True`, `extractor_version=EXTRACTOR_VERSION`.
   - 있고 `raw_value`가 같음: 판정·태그·메모 유지, `active=True`, 패널·층·꼬리·순번·버전만 갱신.
   - 있고 `raw_value`가 다름: `verdict=hold`, `tag=""`, 메모 앞에 `이전 판정={old_verdict}; 이전 태그={old_tag or "-"}; 이전 값={old_raw}\n`.
4. 이번 키에 없는 기존 행은 `active=False`. 삭제하지 않는다.
5. `SummaryRow` 목록을 반환한다. 세션 commit은 호출자가 한다.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_review_service.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/services/extraction_review_service.py packages/web-api/tests/test_extraction_review_service.py
git commit -m "feat(web-api): 진단 후보를 검토 테이블에 맞추고 기존 판정은 값이 같을 때만 유지한다."
```

---

### Task 8: TSV export·import

**Files:**
- Modify: `packages/web-api/app/services/extraction_review_service.py`
- Test: `packages/web-api/tests/test_extraction_review_service.py`

**Interfaces:**
- Consumes: `ExtractionReview`, `DART_DOCUMENT_VIEW`
- Produces:
  - `EXPORT_COLUMNS: tuple[str, ...]` — 스펙 §6.2 헤더 순서
  - `async def export_tsv(session, *, next_slice: bool) -> list[dict[str, str]]`
  - `async def import_tsv(session, text: str) -> int` — 반영 행 수. 실패 시 `ExtractionReviewError`이고 호출자가 rollback할 수 있게 세션에 부분 flush하지 않고, 함수 안에서 예외 전에 `session.rollback()`하지 않는다. 검증을 쓰기 전에 끝내고, 쓰기는 호출자 commit에 맡긴다. 검증 실패면 아무 `session.add`도 하지 않은 채로 `ExtractionReviewError`.

- [ ] **Step 1: Write the failing test**

```python
from app.services.extraction_review_service import export_tsv, import_tsv


def _review(**overrides: object) -> ExtractionReview:
    values: dict[str, object] = {
        "rcept_no": "20200331000001",
        "dcm_no": "11111",
        "bundle": "accounts",
        "signal": "iqr_high",
        "subject": "total_asset",
        "extractor_version": EXTRACTOR_VERSION,
        "in_research_panel": True,
        "stratum": "F001|separate|total_asset",
        "tail": "high",
        "queue_order": 1,
        "raw_value": "10",
        "active": True,
        "verdict": "hold",
        "tag": "",
        "note": "",
    }
    values.update(overrides)
    return ExtractionReview(**values)  # type: ignore[arg-type]


async def test_export_default_and_next_slice(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_review(queue_order=1, verdict="source", tag="real_magnitude"))
        session.add(_review(signal="iqr_low", tail="low", queue_order=1, verdict="logic", subject="total_asset"))
        session.add(_review(signal="iqr_high", queue_order=6, raw_value="99", subject="total_equity"))
        session.add(
            _review(
                bundle="hours",
                signal="hours_nonpositive",
                subject="audit_current_total",
                tail="",
                queue_order=None,
                stratum="F001|separate|audit_current_total",
            )
        )
        await session.commit()
        default_rows = await export_tsv(session, next_slice=False)
        next_rows = await export_tsv(session, next_slice=True)
    default_signals = {row["signal"] for row in default_rows}
    assert "hours_nonpositive" in default_signals
    assert "iqr_high" in default_signals
    assert all(row["queue_order"] != "6" for row in default_rows)
    assert {row["subject"] for row in next_rows} == {"total_equity"}
    assert default_rows[0]["viewer_url"].startswith("https://dart.fss.or.kr/")


async def test_import_rejects_bad_file_and_keeps_blanks(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_review(verdict="source", tag="as_written", note="유지"))
        await session.commit()
        header = "rcept_no\tdcm_no\tbundle\tsignal\tsubject\tverdict\ttag\tnote\n"
        good = header + "20200331000001\t11111\taccounts\tiqr_high\ttotal_asset\thold\t-\t\n"
        count = await import_tsv(session, good)
        await session.commit()
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert count == 1
    assert row.verdict == "hold"
    assert row.tag == ""
    assert row.note == "유지"
    async with sessionmaker_fixture() as session:
        bad = header + "20200331000001\t11111\taccounts\tiqr_high\ttotal_asset\tlogic\tas_written\t\n"
        with pytest.raises(ExtractionReviewError):
            await import_tsv(session, bad)
        row = (await session.execute(select(ExtractionReview))).scalar_one()
    assert row.verdict == "hold"
```

`iqr_high` queue 1이 `source`이고 `iqr_low` queue 1이 `logic`이면 같은 stratum에 둘 다 있다. `--next`의 high 꼬리 m은 1(`source` 행). `queue_order` 2–6 중 `hold`인 `total_equity`(6)만 나온다. low 꼬리는 판정된 행의 m이 1이고 2–6에 hold가 없으면 행이 없다.

기본 export는 `queue_order` 1–5인 IQR과 금지 신호를 포함한다. `queue_order` 6은 기본에 없다.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_review_service.py::test_export_default_and_next_slice tests/test_extraction_review_service.py::test_import_rejects_bad_file_and_keeps_blanks -q --tb=short`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`EXPORT_COLUMNS`는 `rcept_no`, `dcm_no`, `bundle`, `signal`, `subject`, `extractor_version`, `in_research_panel`, `stratum`, `tail`, `queue_order`, `raw_value`, `verdict`, `tag`, `note`, `viewer_url`.

금지 신호 집합: `hours_nonpositive`, `hours_total_missing`, `account_negative`, `unit_missing`, `subsidiary_negative`, `date_nonpositive`.

대표 신호 집합: `rare_code`, `auditor_invalid`, `fail`.

`export_tsv`:

- `active.is_(True)`만.
- `next_slice=False`: 금지 신호 전부, IQR(`iqr_low`/`iqr_high`) 중 `queue_order`가 1 이상 5 이하, 대표 신호 전부.
- `next_slice=True`: IQR 행만 본다. stratum에 `verdict=source`와 `verdict=logic`이 둘 다 있는 층만. 꼬리마다 `verdict != hold`이고 `queue_order`가 있는 행의 최대값을 m으로 한다. 그런 행이 없으면 그 꼬리는 건너뛴다. `verdict==hold`이고 `queue_order`가 m+1 이상 m+5 이하인 행을 낸다.
- `in_research_panel`은 `true`/`false`. `queue_order`가 `None`이면 빈 문자열. `viewer_url = DART_DOCUMENT_VIEW.format(rcept_no=..., dcm_no=...)`.
- 정렬: `stratum`, `signal`, `queue_order` null은 뒤, `rcept_no`, `dcm_no`.

`import_tsv`:

- `csv.DictReader(..., delimiter="\t")`.
- 헤더에 자연키 5개와 `verdict`, `tag`, `note`가 없으면 `ExtractionReviewError`.
- 파일 안 자연키 중복이면 오류.
- 각 행의 자연키가 DB에 없으면 오류. 이 검사는 쓰기 전에 `select`로 하고, 하나라도 없으면 예외를 던지고 속성 대입을 하지 않는다.
- `verdict` 칸이 비어 있지 않으면 `hold`/`source`/`logic`만 허용.
- `tag` 칸이 `-`이면 빈 문자열로 정규화한 뒤 검사한다. 빈 칸은 “유지”라 정규화하지 않는다.
- 정규화 후 `tag`가 비어 있지 않으면 허용 네 값만.
- `verdict`가 `logic` 또는 `hold`인데 정규화한 `tag`가 비어 있지 않으면 오류. `verdict` 칸이 비어 있으면 기존 verdict로 이 검사를 한다.
- 통과한 뒤에만 대입한다. 빈 `verdict`/`note`/`tag` 칸은 기존 값을 유지한다. `-`인 tag만 빈 문자열로 지운다.
- 반환값은 파일 데이터 행 수.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_review_service.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/app/services/extraction_review_service.py packages/web-api/tests/test_extraction_review_service.py
git commit -m "feat(web-api): 진단 후보 TSV를 내보내고 판정만 다시 적재한다."
```

---

### Task 9: CLI

**Files:**
- Create: `packages/web-api/scripts/extraction_reviews.py`
- Test: `packages/web-api/tests/test_extraction_review_service.py`

**Interfaces:**
- Consumes: `diagnose`, `export_tsv`, `import_tsv`, `format_summary`, `EXPORT_COLUMNS`, `Settings`, `create_db_engine`, `create_sessionmaker`
- Produces: `build_parser() -> argparse.ArgumentParser`, `main(argv: list[str] | None = None) -> None`

- [ ] **Step 1: Write the failing test**

```python
from scripts.extraction_reviews import build_parser


def test_parser_accepts_three_commands() -> None:
    parser = build_parser()
    diagnose_args = parser.parse_args(["diagnose", "--summary-out", "out.tsv"])
    export_args = parser.parse_args(["export-tsv", "--next", "--out", "out.tsv"])
    import_args = parser.parse_args(["import-tsv", "--in", "in.tsv"])
    assert diagnose_args.command == "diagnose"
    assert export_args.next_slice is True
    assert import_args.path == "in.tsv"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_review_service.py::test_parser_accepts_three_commands -q --tb=short`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

하위 명령 `diagnose`, `export-tsv`, `import-tsv`. 모두 `--database-url`(기본 `Settings().database_url`).

- `diagnose`: `--summary-out` optional. 표준 출력에 `format_summary`를 줄마다 쓴다. `--summary-out`이 있으면 헤더 `section`, `key`, `n`, `detail`인 UTF-8 TSV도 쓴다. `ExtractionReviewError`면 메시지를 표준 오류에 쓰고 `SystemExit(1)`.
- `export-tsv`: `--out` optional, `--next` store_true dest `next_slice`. 행이 없고 `--next`면 표준 오류에 `소스와 로직이 같이 있는 층이 없습니다.`를 쓴다. 헤더는 항상 `EXPORT_COLUMNS`. UTF-8, `lineterminator="\n"`, 탭. 표준 출력은 `reconfigure(encoding="utf-8")`를 export 스크립트와 같이 시도한다.
- `import-tsv`: `--in` dest `path` required. 파일을 UTF-8로 읽어 `import_tsv` 후 commit. 오류면 rollback, 표준 오류, `SystemExit(1)`.
- 성공 시 exit 0. `if __name__ == "__main__": main()`.

`build_parser`:

```python
def build_parser() -> argparse.ArgumentParser:
    """진단 CLI. 하위 명령은 diagnose, export-tsv, import-tsv."""
    parser = argparse.ArgumentParser(description="12묶음 추출 진단")
    parser.add_argument("--database-url", default=Settings().database_url)
    sub = parser.add_subparsers(dest="command", required=True)
    diagnose = sub.add_parser("diagnose")
    diagnose.add_argument("--summary-out", default=None)
    export = sub.add_parser("export-tsv")
    export.add_argument("--out", default=None)
    export.add_argument("--next", dest="next_slice", action="store_true")
    importing = sub.add_parser("import-tsv")
    importing.add_argument("--in", dest="path", required=True)
    return parser
```

`diagnose` 파서에는 `--next`가 없으므로 `next_slice` 기본값을 `main`에서 `getattr(args, "next_slice", False)`로 읽는다.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extraction_review_service.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/scripts/extraction_reviews.py packages/web-api/tests/test_extraction_review_service.py
git commit -m "feat(web-api): 추출 진단 계산과 TSV 왕복 CLI를 둔다."
```

---

### Task 10: facts export의 소스 태그

**Files:**
- Modify: `packages/web-api/scripts/export_audit_report_facts.py`
- Test: `packages/web-api/tests/test_export_audit_report_facts.py`

**Interfaces:**
- Consumes: `ExtractionReview`, 기존 `iter_rows(session)`
- Produces: `iter_rows(session, *, with_reviews: bool = False)`. `with_reviews=True`일 때만 각 dict에 `source_tags: str`. `write_tsv(rows, dest, columns: Sequence[str] | None = None)` — `None`이면 기존 `COLUMN_NAMES`. `build_parser`에 `--with-reviews` store_true.

- [ ] **Step 1: Write the failing test**

`tests/test_export_audit_report_facts.py`의 기존 `_fact` 헬퍼를 쓴다. 기본 `rcept_no`는 `20200331000001`, `dcm_no`는 `11111`이다. `ExtractionReview`를 import한다.

```python
async def test_with_reviews_appends_source_tags_only(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        session.add(
            ExtractionReview(
                rcept_no="20200331000001",
                dcm_no="11111",
                bundle="accounts",
                signal="account_negative",
                subject="total_asset",
                extractor_version=EXTRACTOR_VERSION,
                in_research_panel=True,
                stratum="F001|separate|total_asset",
                tail="",
                raw_value="-1",
                active=True,
                verdict="source",
                tag="as_written",
                note="",
            )
        )
        session.add(
            ExtractionReview(
                rcept_no="20200331000001",
                dcm_no="11111",
                bundle="hours",
                signal="fail",
                subject="not_found|missing=1|conflicts=0",
                extractor_version=EXTRACTOR_VERSION,
                in_research_panel=False,
                stratum="*|*|hours",
                tail="",
                raw_value="",
                active=True,
                verdict="logic",
                tag="",
                note="",
            )
        )
        await session.commit()
        rows = list(await iter_rows(session, with_reviews=True))
        plain = list(await iter_rows(session))
    assert rows[0]["source_tags"] == "accounts:total_asset:as_written"
    assert "source_tags" not in plain[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_export_audit_report_facts.py::test_with_reviews_appends_source_tags_only -q --tb=short`

Expected: FAIL (`with_reviews` 인자 없음)

- [ ] **Step 3: Write minimal implementation**

`iter_rows(session, *, with_reviews: bool = False)`로 서명을 바꾼다. 기본 호출은 지금과 같다.

`with_reviews`이면 행을 만든 뒤 `ExtractionReview`에서 `active.is_(True)`, `verdict=="source"`, `tag != ""`인 행을 읽어 `(rcept_no, dcm_no)`별로 `bundle:subject:tag`를 `bundle`, `subject`, `tag` 순 정렬해 `;`로 잇는다. 없으면 `""`.

`write_tsv`에 `columns` 인자를 추가하고 기본은 `COLUMN_NAMES`다. `_export`가 `with_reviews`면 `(*COLUMN_NAMES, "source_tags")`를 넘긴다.

`build_parser`에 `--with-reviews`를 추가한다. 설명은 `active 소스 태그를 source_tags 열로 붙입니다.`

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_export_audit_report_facts.py tests/test_extraction_review_service.py tests/test_reviewing_candidates.py tests/test_extraction_review_model.py -q --tb=short`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/web-api/scripts/export_audit_report_facts.py packages/web-api/tests/test_export_audit_report_facts.py
git commit -m "feat(web-api): facts TSV에 진단 소스 태그를 붙일 수 있게 한다."
```
