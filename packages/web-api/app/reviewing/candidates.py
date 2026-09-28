"""감사시간·계정·종속기업·보고일 간격의 숫자 진단 후보."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import TypeGuard

from app.extracting.dates import parse_year_end

_NEGATIVE_ACCOUNTS = frozenset(
    {
        "total_asset",
        "current_asset",
        "total_liability",
        "current_liability",
    }
)
_SKIP_KEYS = (
    "hours_not_list",
    "hours_total_duplicate",
    "accounts_not_list",
    "lag_skipped",
)
_PANEL_YEAR_MIN = date(2016, 1, 31)
_PANEL_YEAR_MAX = date(2025, 12, 31)
_RCEPT_MIN = "20160101"
_RCEPT_MAX = "20260909"
_FINANCIAL_REPORTS = frozenset({"F001", "F002"})


@dataclass(frozen=True)
class FactView:
    """진단에 쓰는 fact 한 행."""

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


@dataclass(frozen=True, kw_only=True)
class ReviewCandidate:
    """자연키와 층·꼬리·순번을 가진 진단 후보."""

    rcept_no: str
    dcm_no: str
    bundle: str
    signal: str
    subject: str
    stratum: str
    tail: str
    queue_order: int | None
    raw_value: str
    in_research_panel: bool


@dataclass(frozen=True)
class SummaryRow:
    """진단 요약 한 줄."""

    section: str
    key: str
    n: int
    detail: str


@dataclass(frozen=True)
class _Draft:
    """아직 순번이 붙지 않은 후보."""

    seq: int
    rcept_no: str
    dcm_no: str
    bundle: str
    signal: str
    subject: str
    stratum: str
    tail: str
    raw_value: str
    in_panel: bool
    scale: float | None


@dataclass(frozen=True)
class _ScalePoint:
    """분포에 넣는 눈금 하나."""

    seq: int
    rcept_no: str
    dcm_no: str
    bundle: str
    subject: str
    stratum: str
    raw_value: str
    scale: float
    in_panel: bool


def select_panel_ids(facts: Sequence[FactView]) -> set[tuple[str, str]]:
    """기업–연도마다 연구 패널 문서 하나를 고른다."""
    grouped: dict[tuple[str, str], list[FactView]] = {}
    for fact in facts:
        year_end = _panel_year_end(fact)
        if year_end is None or not fact.corp_code:
            continue
        grouped.setdefault((fact.corp_code, year_end.isoformat()), []).append(fact)

    chosen: set[tuple[str, str]] = set()
    for rows in grouped.values():
        picked = _pick_panel_row(rows)
        if picked is not None:
            chosen.add((picked.rcept_no, picked.dcm_no))
    return chosen


def _panel_year_end(fact: FactView) -> date | None:
    """패널 창에 드는 결산일이면 그 날짜를 돌려준다."""
    if fact.fetch_status != "ok" or not fact.corp_code:
        return None
    if fact.fs_scope not in {"consolidated", "separate"}:
        return None
    if not _rcept_in_panel_window(fact.rcept_dt):
        return None
    year_end = parse_year_end(fact.year_end)
    if year_end is None or year_end < _PANEL_YEAR_MIN or year_end > _PANEL_YEAR_MAX:
        return None
    return year_end


def _rcept_in_panel_window(rcept_dt: str) -> bool:
    """접수일이 8자리 숫자이고 20160101 이상 20260909 이하인지 본다."""
    if len(rcept_dt) != 8 or not rcept_dt.isdigit():
        return False
    return _RCEPT_MIN <= rcept_dt <= _RCEPT_MAX


def _pick_panel_row(rows: list[FactView]) -> FactView | None:
    """연결을 우선하고, F001·F002가 있으면 A001을 뺀 뒤 가장 늦은 접수를 고른다."""
    consolidated = [row for row in rows if row.fs_scope == "consolidated"]
    if consolidated:
        pool = consolidated
    else:
        pool = [row for row in rows if row.fs_scope == "separate"]
    if not pool:
        return None
    if any(row.source_report_type in _FINANCIAL_REPORTS for row in pool):
        pool = [row for row in pool if row.source_report_type != "A001"]
    return max(pool, key=lambda row: (row.rcept_dt, row.rcept_no, row.dcm_no))


def quartile_bounds(
    scale_values: list[float],
) -> tuple[float, float, float, float] | None:
    """(q1, q3, low, high). 30개 미만이거나 IQR이 0이면 None."""
    parsed = _quartiles(scale_values)
    if parsed is None:
        return None
    q1, q3, iqr = parsed
    if iqr <= 0:
        return None
    fence = 1.5 * iqr
    return (q1, q3, q1 - fence, q3 + fence)


class _Bag:
    """한 번 계산에서 후보·눈금·건너뜀을 모은다."""

    def __init__(self, panel_ids: set[tuple[str, str]]) -> None:
        self.panel_ids = panel_ids
        self.drafts: list[_Draft] = []
        self.points: list[_ScalePoint] = []
        self.seen: set[tuple[str, str, str, str, str]] = set()
        self.scale_seen: set[tuple[str, str, str, str]] = set()
        self.skips: dict[str, int] = {key: 0 for key in _SKIP_KEYS}
        self.seq = 0

    def skip(self, key: str) -> None:
        """요약용 건너뜀 건수를 하나 올린다."""
        self.skips[key] += 1

    def _panel(self, fact: FactView) -> bool:
        return (fact.rcept_no, fact.dcm_no) in self.panel_ids

    def add_draft(
        self,
        fact: FactView,
        *,
        bundle: str,
        signal: str,
        subject: str,
        stratum: str,
        tail: str,
        raw_value: str,
        scale: float | None,
    ) -> None:
        """같은 자연키는 처음 한 번만 남긴다."""
        key = (fact.rcept_no, fact.dcm_no, bundle, signal, subject)
        if key in self.seen:
            return
        self.seen.add(key)
        self.drafts.append(
            _Draft(
                seq=self.seq,
                rcept_no=fact.rcept_no,
                dcm_no=fact.dcm_no,
                bundle=bundle,
                signal=signal,
                subject=subject,
                stratum=stratum,
                tail=tail,
                raw_value=raw_value,
                in_panel=self._panel(fact),
                scale=scale,
            )
        )
        self.seq += 1

    def add_point(
        self,
        fact: FactView,
        *,
        bundle: str,
        subject: str,
        stratum: str,
        raw_value: str,
        scale: float,
    ) -> None:
        """같은 문서·묶음·대상의 눈금은 처음 값만 분포에 넣는다."""
        key = (fact.rcept_no, fact.dcm_no, bundle, subject)
        if key in self.scale_seen:
            return
        self.scale_seen.add(key)
        self.points.append(
            _ScalePoint(
                seq=self.seq,
                rcept_no=fact.rcept_no,
                dcm_no=fact.dcm_no,
                bundle=bundle,
                subject=subject,
                stratum=stratum,
                raw_value=raw_value,
                scale=scale,
                in_panel=self._panel(fact),
            )
        )
        self.seq += 1


def numeric_candidates(
    facts: Sequence[FactView],
    panel_ids: set[tuple[str, str]],
) -> tuple[list[ReviewCandidate], list[SummaryRow]]:
    """금지 값과 층화 1.5 IQR 꼬리를 후보로 만든다."""
    bag = _Bag(panel_ids)
    for fact in facts:
        if fact.fetch_status != "ok":
            continue
        _collect_hours(fact, bag)
        _collect_accounts(fact, bag)
        _collect_subsidiary(fact, bag)
        _collect_lag(fact, bag)

    iqr_drafts, stratum_rows = _iqr_from_points(bag.points, bag.seen)
    bag.drafts.extend(iqr_drafts)
    bag.drafts.sort(key=lambda item: item.seq)
    return _with_queue(bag.drafts), _summary(bag.skips, stratum_rows)


def _is_number(value: object) -> TypeGuard[int | float]:
    """bool을 뺀 실수인지 본다."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _raw(value: int | float) -> str:
    """비교에 쓴 숫자를 문자열로 남긴다."""
    return str(value)


def _fmt(value: float) -> str:
    """요약에 적는 짧은 눈금."""
    return format(value, ".6g")


def _iso_date(value: object) -> date | None:
    """ISO 날짜 문자열만 받는다."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _hour_cells(hours: object) -> list[dict[str, object]] | None:
    """당기 감사 합계 칸. 리스트가 아니면 None."""
    if not isinstance(hours, list):
        return None
    cells: list[dict[str, object]] = []
    for item in hours:
        if not isinstance(item, dict):
            continue
        if (
            item.get("role") == "total"
            and item.get("metric") == "audit"
            and item.get("period") == "current"
        ):
            cells.append(item)
    return cells


def _collect_hours(fact: FactView, bag: _Bag) -> None:
    """감사시간 합계의 금지 값과 분포 눈금을 모은다."""
    if fact.hours_status != "ok":
        return
    cells = _hour_cells(fact.hours)
    stratum = f"{fact.source_report_type}|{fact.fs_scope}|audit_current_total"
    if cells is None:
        bag.skip("hours_not_list")
        return
    if len(cells) >= 2:
        bag.skip("hours_total_duplicate")
        return
    value = cells[0].get("value") if cells else None
    if not _is_number(value):
        bag.add_draft(
            fact,
            bundle="hours",
            signal="hours_total_missing",
            subject="audit_current_total",
            stratum=stratum,
            tail="",
            raw_value="",
            scale=None,
        )
        return
    if value <= 0:
        bag.add_draft(
            fact,
            bundle="hours",
            signal="hours_nonpositive",
            subject="audit_current_total",
            stratum=stratum,
            tail="",
            raw_value=_raw(value),
            scale=None,
        )
        return
    bag.add_point(
        fact,
        bundle="hours",
        subject="audit_current_total",
        stratum=stratum,
        raw_value=_raw(value),
        scale=math.log1p(float(value)),
    )


def _collect_accounts(fact: FactView, bag: _Bag) -> None:
    """당기 계정의 단위 결측·음수 금지와 분포 눈금을 모은다."""
    if fact.accounts_status != "ok":
        return
    if not isinstance(fact.accounts, list):
        bag.skip("accounts_not_list")
        return
    for item in fact.accounts:
        if not isinstance(item, dict):
            continue
        if item.get("period") != "current" or item.get("status") != "ok":
            continue
        account = item.get("account")
        if not isinstance(account, str):
            continue
        stratum = f"{fact.source_report_type}|{fact.fs_scope}|{account}"
        value = item.get("value_won")
        if not _is_number(value):
            bag.add_draft(
                fact,
                bundle="accounts",
                signal="unit_missing",
                subject=account,
                stratum=stratum,
                tail="",
                raw_value="",
                scale=None,
            )
            continue
        if value < 0 and account in _NEGATIVE_ACCOUNTS:
            bag.add_draft(
                fact,
                bundle="accounts",
                signal="account_negative",
                subject=account,
                stratum=stratum,
                tail="",
                raw_value=_raw(value),
                scale=None,
            )
            continue
        if value <= 0:
            continue
        bag.add_point(
            fact,
            bundle="accounts",
            subject=account,
            stratum=stratum,
            raw_value=_raw(value),
            scale=math.log1p(float(value)),
        )


def _collect_subsidiary(fact: FactView, bag: _Bag) -> None:
    """연결 종속기업 수의 음수 금지와 분포 눈금을 모은다."""
    if fact.fs_scope != "consolidated" or fact.subsidiary_status != "ok":
        return
    count = fact.subsidiary_count
    if isinstance(count, bool) or not isinstance(count, int):
        return
    stratum = f"{fact.source_report_type}|*|subsidiary_count"
    if count < 0:
        bag.add_draft(
            fact,
            bundle="subsidiary",
            signal="subsidiary_negative",
            subject="subsidiary_count",
            stratum=stratum,
            tail="",
            raw_value=_raw(count),
            scale=None,
        )
        return
    if count == 0:
        return
    bag.add_point(
        fact,
        bundle="subsidiary",
        subject="subsidiary_count",
        stratum=stratum,
        raw_value=_raw(count),
        scale=math.log1p(count),
    )


def _collect_lag(fact: FactView, bag: _Bag) -> None:
    """감사보고서일과 결산일 간격의 금지 값과 일수 눈금을 모은다."""
    if fact.audit_report_date_status != "ok":
        return
    report = _iso_date(fact.audit_report_date)
    end = parse_year_end(fact.year_end)
    if report is None or end is None:
        bag.skip("lag_skipped")
        return
    lag = (report - end).days
    stratum = f"{fact.source_report_type}|{fact.fs_scope}|lag_days"
    if lag <= 0:
        bag.add_draft(
            fact,
            bundle="audit_report_date",
            signal="date_nonpositive",
            subject="lag_days",
            stratum=stratum,
            tail="",
            raw_value=_raw(lag),
            scale=None,
        )
        return
    bag.add_point(
        fact,
        bundle="audit_report_date",
        subject="lag_days",
        stratum=stratum,
        raw_value=_raw(lag),
        scale=float(lag),
    )


def _iqr_from_points(
    points: list[_ScalePoint],
    seen: set[tuple[str, str, str, str, str]],
) -> tuple[list[_Draft], list[SummaryRow]]:
    """층마다 울타리 밖을 고르고 요약 행을 만든다."""
    grouped: dict[str, list[_ScalePoint]] = {}
    for point in points:
        grouped.setdefault(point.stratum, []).append(point)

    drafts: list[_Draft] = []
    rows: list[SummaryRow] = []
    for stratum, group in grouped.items():
        scales = [point.scale for point in group]
        bounds = quartile_bounds(scales)
        if bounds is None:
            detail = "건너뜀 n<30" if len(group) < 30 else "건너뜀 iqr_zero"
            rows.append(SummaryRow(section="stratum", key=stratum, n=len(group), detail=detail))
            continue
        q1, q3, low, high = bounds
        iqr = q3 - q1
        outliers = [point for point in group if point.scale < low or point.scale > high]
        kept = [
            point
            for point in outliers
            if (point.rcept_no, point.dcm_no, point.bundle, _tail_signal(point, low), point.subject)
            not in seen
        ]
        detail = f"Q1 {_fmt(q1)} Q3 {_fmt(q3)} IQR {_fmt(iqr)} 후보 {len(kept)}"
        rows.append(SummaryRow(section="stratum", key=stratum, n=len(group), detail=detail))
        for point in kept:
            signal = _tail_signal(point, low)
            tail = "low" if signal == "iqr_low" else "high"
            seen.add((point.rcept_no, point.dcm_no, point.bundle, signal, point.subject))
            drafts.append(
                _Draft(
                    seq=point.seq,
                    rcept_no=point.rcept_no,
                    dcm_no=point.dcm_no,
                    bundle=point.bundle,
                    signal=signal,
                    subject=point.subject,
                    stratum=point.stratum,
                    tail=tail,
                    raw_value=point.raw_value,
                    in_panel=point.in_panel,
                    scale=point.scale,
                )
            )
    return drafts, rows


def _tail_signal(point: _ScalePoint, low: float) -> str:
    """울타리 아래면 iqr_low, 아니면 iqr_high."""
    if point.scale < low:
        return "iqr_low"
    return "iqr_high"


def _quartiles(scale_values: list[float]) -> tuple[float, float, float] | None:
    """(q1, q3, iqr). 30개 미만이면 None."""
    if len(scale_values) < 30:
        return None
    q1, _q2, q3 = statistics.quantiles(scale_values, n=4, method="inclusive")
    return (q1, q3, q3 - q1)


def _with_queue(drafts: list[_Draft]) -> list[ReviewCandidate]:
    """패널 IQR만 층·꼬리 안에서 극단 순번을 붙인다."""
    groups: dict[tuple[str, str], list[_Draft]] = {}
    for draft in drafts:
        if draft.tail not in {"low", "high"} or not draft.in_panel or draft.scale is None:
            continue
        groups.setdefault((draft.stratum, draft.tail), []).append(draft)
    ranks: dict[int, int] = {}
    for (_stratum, tail), group in groups.items():
        if tail == "high":
            ordered = sorted(group, key=lambda item: (-(item.scale or 0.0), item.seq))
        else:
            ordered = sorted(group, key=lambda item: (item.scale or 0.0, item.seq))
        for rank, item in enumerate(ordered, start=1):
            ranks[item.seq] = rank
    return [
        ReviewCandidate(
            rcept_no=draft.rcept_no,
            dcm_no=draft.dcm_no,
            bundle=draft.bundle,
            signal=draft.signal,
            subject=draft.subject,
            stratum=draft.stratum,
            tail=draft.tail,
            queue_order=ranks.get(draft.seq),
            raw_value=draft.raw_value,
            in_research_panel=draft.in_panel,
        )
        for draft in drafts
    ]


def _summary(skips: dict[str, int], stratum_rows: list[SummaryRow]) -> list[SummaryRow]:
    """건너뜀 건수와 층 요약을 잇는다."""
    rows = [
        SummaryRow(section="skip", key=key, n=skips[key], detail="")
        for key in _SKIP_KEYS
        if skips[key] > 0
    ]
    rows.extend(stratum_rows)
    return rows
