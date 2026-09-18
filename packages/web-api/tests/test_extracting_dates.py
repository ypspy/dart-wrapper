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
