"""추출 필드 우선순위 해소와 교차검증 conflict."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TypeGuard, TypedDict

from app.extracting.dates import parse_year_end
from app.extracting.result import FieldResult
from app.extracting.text import compact

_FULL_DATE = re.compile(r"(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})")
_YEAR_MONTH = re.compile(r"(\d{4})[.\-](\d{1,2})")
_MONTH_ONLY = re.compile(r"^(\d{1,2})월$")


class Conflict(TypedDict):
    """두 출처 값이 정규화 후 다를 때 남기는 기록."""

    field: str
    left: str
    right: str
    left_source: str
    right_source: str


class ResolvedAuditor(TypedDict):
    """감사인 해소 결과."""

    value: str | None
    source: str | None
    conflicts: list[Conflict]


class ResolvedOpinion(TypedDict):
    """감사의견 해소 결과."""

    value: str | None
    source: str | None
    conflicts: list[Conflict]


def normalize_firm_name(value: str | None) -> str:
    """공백과 주식회사·(주)를 제거한 상호를 반환한다."""
    text = compact(value)
    return text.replace("주식회사", "").replace("(주)", "")


def resolve_auditor(
    *,
    cover: FieldResult | None,
    a001: FieldResult | None,
    body: FieldResult | None,
    listing: str | None,
    report_type: str,
) -> ResolvedAuditor:
    """문서 출처 순위로 감사인을 고르고, listing은 conflict에 넣지 않는다.

    순위는 표지 → (A001만 당기 칸) → 본문. F001·F002 listing(현재명)과
    A001 listing(회사명)은 호출자가 넘기더라도 이 함수에서 무시한다.
    """
    _ = listing
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
    if not ranked:
        return ResolvedAuditor(value=None, source=None, conflicts=conflicts)
    source, winner = ranked[0]
    return ResolvedAuditor(value=winner.raw, source=source, conflicts=conflicts)


def resolve_opinion(
    *,
    letter: FieldResult,
    a001: FieldResult | None,
) -> ResolvedOpinion:
    """의견 본문(letter)이 ok이면 그것을, 아니면 a001을 쓴다.

    둘 다 ok이고 compact 코드가 다르면 conflict를 남기되 값은 letter다.
    """
    conflicts: list[Conflict] = []
    if _is_ok(letter) and _is_ok(a001):
        left_code = compact(letter.code)
        right_code = compact(a001.code)
        if left_code != right_code:
            conflicts.append(
                Conflict(
                    field="opinion",
                    left=letter.code or "",
                    right=a001.code or "",
                    left_source="letter",
                    right_source="a001",
                )
            )
    if _is_ok(letter):
        return ResolvedOpinion(
            value=letter.code, source="letter", conflicts=conflicts
        )
    if _is_ok(a001):
        return ResolvedOpinion(value=a001.code, source="a001", conflicts=[])
    return ResolvedOpinion(value=None, source=None, conflicts=[])


def corp_name_conflicts(
    listing: str | None,
    activity: str | None,
    a001_cover: str | None,
) -> list[Conflict]:
    """같은 접수의 목록명·실시내용·사업표지 회사명만 비교한다. listing은 유지."""
    return _pairwise_conflicts(
        "corp_name",
        [
            ("listing", listing),
            ("activity", activity),
            ("a001_cover", a001_cover),
        ],
        key=normalize_firm_name,
    )


def year_end_conflicts(
    listing: str | None,
    activity: str | None,
    a001_cover: str | None,
    cover_period: str | None,
) -> list[Conflict]:
    """결산월·당기를 정규화해 비교한다. listing year_end는 바꾸지 않는다."""
    return _pairwise_conflicts(
        "year_end",
        [
            ("listing", listing),
            ("activity", activity),
            ("a001_cover", a001_cover),
            ("cover_period", cover_period),
        ],
        equal=_year_ends_match,
    )


def _is_ok(result: FieldResult | None) -> TypeGuard[FieldResult]:
    return result is not None and result.status == "ok"


def _pairwise_conflicts(
    field: str,
    sources: list[tuple[str, str | None]],
    *,
    key: Callable[[str | None], str] | None = None,
    equal: Callable[[str | None, str | None], bool] | None = None,
) -> list[Conflict]:
    present = [(source, value) for source, value in sources if value]
    if equal is not None:
        matches = equal
    else:
        if key is None:
            raise TypeError("key 또는 equal이 필요합니다.")

        def matches(left: str | None, right: str | None) -> bool:
            return key(left) == key(right)

    conflicts: list[Conflict] = []
    for index, (left_source, left) in enumerate(present):
        for right_source, right in present[index + 1 :]:
            if not matches(left, right):
                conflicts.append(
                    Conflict(
                        field=field,
                        left=left,
                        right=right,
                        left_source=left_source,
                        right_source=right_source,
                    )
                )
    return conflicts


def _year_end_parts(value: str | None) -> tuple[int | None, int | None, str]:
    """결산월을 (연, 월, compact 원문)으로 나눈다. 월만 있으면 연은 None."""
    compacted = compact(value)
    full_dates = list(_FULL_DATE.finditer(compacted))
    if full_dates:
        year_s, month_s, _day_s = full_dates[-1].groups()
        return int(year_s), int(month_s), compacted
    parsed = parse_year_end(value)
    if parsed is not None:
        return parsed.year, parsed.month, compacted
    year_month = _YEAR_MONTH.search(compacted)
    if year_month is not None:
        return int(year_month.group(1)), int(year_month.group(2)), compacted
    month_only = _MONTH_ONLY.fullmatch(compacted)
    if month_only is not None:
        month = int(month_only.group(1))
        if 1 <= month <= 12:
            return None, month, compacted
    return None, None, compacted


def _year_end_key(value: str | None) -> str:
    """비교용 결산월 키. 연·월이면 YYYY-MM, 월만이면 MM, 실패 시 compact 원문.

    당기 구간(시작~종료)은 마지막 전체 날짜를 기말로 쓴다. listing의
    `(2019.12)`처럼 연·월만 있으면 parse_year_end를 쓴다. 실시내용
    `12월`처럼 월만 있으면 월 성분만 키로 둔다.
    """
    year, month, fallback = _year_end_parts(value)
    if year is not None and month is not None:
        return f"{year:04d}-{month:02d}"
    if month is not None:
        return f"{month:02d}"
    return fallback


def _year_ends_match(left: str | None, right: str | None) -> bool:
    """한쪽이 월만이면 월만, 둘 다 연·월이면 YYYY-MM을 비교한다."""
    left_year, left_month, _left_fallback = _year_end_parts(left)
    right_year, right_month, _right_fallback = _year_end_parts(right)
    if left_month is not None and right_month is not None:
        if left_year is None or right_year is None:
            return left_month == right_month
    return _year_end_key(left) == _year_end_key(right)
