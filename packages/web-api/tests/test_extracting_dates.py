"""감사보고서일 후보 추출·창 선택 테스트."""

from datetime import date

from app.extracting.dates import (
    extract_date_candidates,
    parse_rcept_dt,
    parse_year_end,
    pick_audit_report_date,
)


def test_picks_single_candidate_inside_window() -> None:
    """후보 2개 중 창을 통과하는 1개만 고른다."""
    text = (
        "우리는 2018년12월31일로 종료되는 회계연도를 감사하였습니다. "
        "감사의견 적정. 의견근거 중간설명 "
        "재무제표에대한경영진의책임. 2019년3월15일"
    )
    candidates = extract_date_candidates(text)
    assert [c.iso for c in candidates] == ["2018-12-31", "2019-03-15"]
    assert candidates[0].date_raw == "2018년12월31일"
    assert candidates[1].date_raw == "2019년3월15일"
    assert candidates[0].index == 0
    assert candidates[1].index == 1

    iso, status, passing = pick_audit_report_date(
        candidates,
        period_end=date(2018, 12, 31),
        rcept_dt=date(2019, 3, 31),
    )
    assert status == "ok"
    assert iso == "2019-03-15"
    assert len(passing) == 1
    assert passing[0].iso == "2019-03-15"


def test_ambiguous_when_two_candidates_pass_window() -> None:
    """창을 둘 다 통과하면 후반 우선 없이 ambiguous이고 ISO는 None이다."""
    text = (
        "머리 2019년2월1일 의견근거 중간 "
        "재무제표에대한경 서명 2019년3월15일"
    )
    candidates = extract_date_candidates(text)
    assert [c.iso for c in candidates] == ["2019-02-01", "2019-03-15"]

    iso, status, passing = pick_audit_report_date(
        candidates,
        period_end=date(2018, 12, 31),
        rcept_dt=date(2019, 3, 31),
    )
    assert status == "ambiguous"
    assert iso is None
    assert [c.iso for c in passing] == ["2019-02-01", "2019-03-15"]


def test_not_found_when_no_dates() -> None:
    """날짜 패턴이 없으면 not_found이다."""
    candidates = extract_date_candidates("의견근거 본문 재무제표에대한경영진의책임")
    assert candidates == []

    iso, status, passing = pick_audit_report_date(
        candidates,
        period_end=date(2018, 12, 31),
        rcept_dt=date(2019, 3, 31),
    )
    assert status == "not_found"
    assert iso is None
    assert passing == []


def test_drops_dates_between_opinion_grounds_and_fs_section() -> None:
    """의견근거와 재무제표에대한경 사이 날짜는 후보에서 뺀다."""
    text = (
        "머리 2018년12월31일 의견근거 중간날짜 2019년1월10일 "
        "재무제표에대한경 서명 2019년3월15일"
    )
    candidates = extract_date_candidates(text)
    assert [c.iso for c in candidates] == ["2018-12-31", "2019-03-15"]


def test_zero_pads_iso_and_reads_compact_dates() -> None:
    """공백을 제거한 뒤 매칭하고 ISO는 zero-pad한다."""
    text = "머리 2019년 3월 5일 의견근거 중간 재무제표에대한경"
    candidates = extract_date_candidates(text)
    assert len(candidates) == 1
    assert candidates[0].date_raw == "2019년3월5일"
    assert candidates[0].iso == "2019-03-05"


def test_snippet_uses_original_text_around_match() -> None:
    """snippet은 원문 매칭 전후 40자를 쓴다."""
    prefix = "가" * 10
    suffix = "나" * 10
    text = f"{prefix}2019년3월15일{suffix} 의견근거 중간 재무제표에대한경"
    candidates = extract_date_candidates(text)
    assert len(candidates) == 1
    assert candidates[0].snippet == f"{prefix}2019년3월15일{suffix} 의견근거 중간 재무제표에대한경"


def test_same_day_rcept_dt_is_allowed() -> None:
    """접수 당일 날짜는 창을 통과한다."""
    text = "서명 2019년3월31일 의견근거 중간 재무제표에대한경"
    candidates = extract_date_candidates(text)
    iso, status, passing = pick_audit_report_date(
        candidates,
        period_end=date(2018, 12, 31),
        rcept_dt=date(2019, 3, 31),
    )
    assert status == "ok"
    assert iso == "2019-03-31"
    assert len(passing) == 1


def test_omits_missing_window_bounds() -> None:
    """period_end·rcept_dt가 None이면 그 쪽 비교를 생략한다."""
    text = "머리 2017년1월1일 의견근거 중간 재무제표에대한경"
    candidates = extract_date_candidates(text)
    iso, status, _passing = pick_audit_report_date(
        candidates,
        period_end=None,
        rcept_dt=None,
    )
    assert status == "ok"
    assert iso == "2017-01-01"


def test_parse_year_end_and_rcept_dt() -> None:
    """year_end·접수일 문자열을 date로 파싱한다."""
    assert parse_year_end("(2019.12)") == date(2019, 12, 31)
    assert parse_year_end(None) is None
    assert parse_rcept_dt("2019.03.31") == date(2019, 3, 31)
    assert parse_rcept_dt("2019-03-31") == date(2019, 3, 31)
    assert parse_rcept_dt(None) is None
