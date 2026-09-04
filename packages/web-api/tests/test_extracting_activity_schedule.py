"""수행시기·투입인원 파서 테스트."""

from app.extracting.activity_schedule import parse_headcount, parse_schedule


def test_parse_schedule_splits_range_and_days() -> None:
    """기간(~)과 일수를 분리 파싱한다."""
    result = parse_schedule("24.06.17~24.07.14 (27일)")
    assert result["raw"] == "24.06.17~24.07.14 (27일)"
    assert result["start_date"] == "24.06.17"
    assert result["end_date"] == "24.07.14"
    assert result["days"] == 27


def test_parse_schedule_single_day_sets_start_equal_end() -> None:
    """단일 일자는 start와 end가 같다."""
    result = parse_schedule("2025.01.02 (1일)")
    assert result["start_date"] == "2025.01.02"
    assert result["end_date"] == "2025.01.02"
    assert result["days"] == 1


def test_parse_schedule_dash_is_null() -> None:
    """'-'는 날짜·일수 모두 None."""
    result = parse_schedule("-")
    assert result["start_date"] is None
    assert result["end_date"] is None
    assert result["days"] is None


def test_parse_schedule_abbreviated_end_day_inherits_year_month() -> None:
    """끝 날짜가 일만 있으면 시작의 연·월을 붙인다."""
    result = parse_schedule("2024.09.25~27 3 일")
    assert result["start_date"] == "2024.09.25"
    assert result["end_date"] == "2024.09.27"
    assert result["days"] == 3


def test_parse_schedule_abbreviated_end_month_day_inherits_year() -> None:
    """끝 날짜가 월.일이면 시작의 연을 붙인다."""
    result = parse_schedule("2024.11.25~11.29 5 일")
    assert result["start_date"] == "2024.11.25"
    assert result["end_date"] == "2024.11.29"
    assert result["days"] == 5


def test_parse_schedule_korean_date_does_not_use_calendar_day_as_days() -> None:
    """한글 날짜의 '4일'은 일수가 아니고, 뒤의 '1 일'이 일수다."""
    result = parse_schedule("2016년 1월 4일 1 일")
    assert result["start_date"] == "2016년 1월 4일"
    assert result["end_date"] == "2016년 1월 4일"
    assert result["days"] == 1


def test_parse_headcount_reads_number_keeps_raw() -> None:
    """숫자와 원문을 함께 반환한다."""
    result = parse_headcount("20명")
    assert result["raw"] == "20명"
    assert result["count"] == 20


def test_parse_headcount_dash_is_null_not_zero() -> None:
    """'-'는 0이 아니라 None."""
    result = parse_headcount("-")
    assert result["count"] is None
