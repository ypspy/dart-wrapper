"""감사 추출 필드 해소(우선순위·교차검증) 테스트."""

from app.extracting.resolve import (
    corp_name_conflicts,
    normalize_firm_name,
    resolve_auditor,
    resolve_opinion,
    year_end_conflicts,
)
from app.extracting.result import FieldResult


def _ok(raw: str | None, code: str | None = None) -> FieldResult:
    return FieldResult(raw=raw, code=code, status="ok")


def _missing() -> FieldResult:
    return FieldResult(raw=None, code=None, status="not_found")


def test_normalize_firm_name_strips_spaces_and_legal_forms() -> None:
    """공백과 주식회사·(주)를 제거한다."""
    assert normalize_firm_name("삼 일 회계법인") == "삼일회계법인"
    assert normalize_firm_name("삼성전자주식회사") == "삼성전자"
    assert normalize_firm_name("(주)삼성전자") == "삼성전자"
    assert normalize_firm_name(None) == ""


def test_f001_listing_differs_from_cover_no_conflict_cover_wins() -> None:
    """F001에서 listing(현재명)이 표지와 달라도 conflict 없이 표지를 고른다."""
    resolved = resolve_auditor(
        cover=_ok("삼일회계법인"),
        a001=None,
        body=_missing(),
        listing="삼정회계법인",
        report_type="F001",
    )
    assert resolved["value"] == "삼일회계법인"
    assert resolved["source"] == "cover"
    assert resolved["conflicts"] == []


def test_a001_cover_differs_from_a001_surfaces_conflict() -> None:
    """A001에서 표지와 당기 칸 감사인이 다르면 conflict를 남기고 표지를 고른다."""
    resolved = resolve_auditor(
        cover=_ok("삼일회계법인"),
        a001=_ok("안진회계법인"),
        body=_missing(),
        listing="삼성전자",
        report_type="A001",
    )
    assert resolved["value"] == "삼일회계법인"
    assert resolved["source"] == "cover"
    assert len(resolved["conflicts"]) == 1
    conflict = resolved["conflicts"][0]
    assert conflict["field"] == "auditor"
    assert conflict["left"] == "삼일회계법인"
    assert conflict["right"] == "안진회계법인"
    assert conflict["left_source"] == "cover"
    assert conflict["right_source"] == "a001"


def test_f001_does_not_conflict_or_rank_a001() -> None:
    """F001에서는 a001 인자를 순위·conflict에 쓰지 않는다."""
    resolved = resolve_auditor(
        cover=_ok("삼일회계법인"),
        a001=_ok("안진회계법인"),
        body=_missing(),
        listing=None,
        report_type="F001",
    )
    assert resolved["value"] == "삼일회계법인"
    assert resolved["source"] == "cover"
    assert resolved["conflicts"] == []


def test_f001_cover_versus_body_conflict() -> None:
    """F001 문서 출처(표지·본문)끼리만 비교해 conflict를 남긴다."""
    resolved = resolve_auditor(
        cover=_ok("삼일회계법인"),
        a001=None,
        body=_ok("한영회계법인"),
        listing="삼일회계법인",
        report_type="F001",
    )
    assert resolved["value"] == "삼일회계법인"
    assert resolved["source"] == "cover"
    assert [c["right_source"] for c in resolved["conflicts"]] == ["body"]
    assert resolved["conflicts"][0]["right"] == "한영회계법인"


def test_resolve_auditor_stores_normalized_firm_name() -> None:
    """해소 값은 주식회사·공백을 뺀 상호다."""
    resolved = resolve_auditor(
        cover=_ok("삼일회계법인주식회사"),
        a001=None,
        body=_missing(),
        listing=None,
        report_type="F001",
    )
    assert resolved["value"] == "삼일회계법인"
    assert resolved["source"] == "cover"


def test_a001_falls_back_cover_then_a001_then_body() -> None:
    """A001 순위는 표지 → 당기 칸 → 본문이다."""
    no_cover = resolve_auditor(
        cover=_missing(),
        a001=_ok("삼일회계법인"),
        body=_ok("한영회계법인"),
        listing=None,
        report_type="A001",
    )
    assert no_cover["value"] == "삼일회계법인"
    assert no_cover["source"] == "a001"
    assert no_cover["conflicts"][0]["left_source"] == "a001"
    assert no_cover["conflicts"][0]["right_source"] == "body"

    body_only = resolve_auditor(
        cover=_missing(),
        a001=_missing(),
        body=_ok("한영회계법인"),
        listing="무시됨",
        report_type="A001",
    )
    assert body_only["value"] == "한영회계법인"
    assert body_only["source"] == "body"
    assert body_only["conflicts"] == []


def test_a001_listing_argument_is_ignored() -> None:
    """A001 listing(회사명)은 감사인 해소에 쓰지 않는다."""
    resolved = resolve_auditor(
        cover=_missing(),
        a001=_missing(),
        body=_missing(),
        listing="삼성전자",
        report_type="A001",
    )
    assert resolved["value"] is None
    assert resolved["source"] is None
    assert resolved["conflicts"] == []


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


def test_auditor_names_match_after_normalize() -> None:
    """정규화 후 같으면 conflict가 없다."""
    resolved = resolve_auditor(
        cover=_ok("삼일 회계법인"),
        a001=_ok("삼일회계법인"),
        body=_missing(),
        listing=None,
        report_type="A001",
    )
    assert resolved["conflicts"] == []
    assert resolved["value"] == "삼일회계법인"


def test_resolve_opinion_letter_wins_without_conflict() -> None:
    """의견 본문이 ok이면 letter를 쓰고 a001과 코드가 같으면 conflict가 없다."""
    resolved = resolve_opinion(
        letter=_ok("boilerplate_unqualified", "unqualified"),
        a001=_ok("적정", "unqualified"),
    )
    assert resolved["value"] == "unqualified"
    assert resolved["source"] == "letter"
    assert resolved["conflicts"] == []


def test_resolve_opinion_conflict_when_codes_differ_letter_wins() -> None:
    """둘 다 ok이고 compact 코드가 다르면 conflict, 값은 letter."""
    resolved = resolve_opinion(
        letter=_ok("boilerplate_unqualified", "unqualified"),
        a001=_ok("한정", "qualified"),
    )
    assert resolved["value"] == "unqualified"
    assert resolved["source"] == "letter"
    assert len(resolved["conflicts"]) == 1
    conflict = resolved["conflicts"][0]
    assert conflict["field"] == "opinion"
    assert conflict["left"] == "unqualified"
    assert conflict["right"] == "qualified"
    assert conflict["left_source"] == "letter"
    assert conflict["right_source"] == "a001"


def test_resolve_opinion_falls_back_to_a001() -> None:
    """letter가 ok가 아니면 a001을 쓴다."""
    resolved = resolve_opinion(letter=_missing(), a001=_ok("적정", "unqualified"))
    assert resolved["value"] == "unqualified"
    assert resolved["source"] == "a001"
    assert resolved["conflicts"] == []


def test_corp_name_conflicts_only_same_filing_args() -> None:
    """회사명은 같은 접수의 listing·실시내용·사업표지만 비교한다."""
    conflicts = corp_name_conflicts(
        "삼성전자",
        "삼성전자주식회사",
        "(주)삼성전자",
    )
    assert conflicts == []


def test_corp_name_mismatch_keeps_listing_in_conflict_pair() -> None:
    """불일치해도 listing 원문을 유지하고 conflict만 남긴다."""
    conflicts = corp_name_conflicts("삼성전자", "현대자동차", None)
    assert len(conflicts) == 1
    assert conflicts[0]["field"] == "corp_name"
    assert conflicts[0]["left"] == "삼성전자"
    assert conflicts[0]["right"] == "현대자동차"
    assert conflicts[0]["left_source"] == "listing"
    assert conflicts[0]["right_source"] == "activity"


def test_year_end_no_conflict_when_same_period_different_format() -> None:
    """날짜 형식이 달라도 같은 결산월이면 conflict가 없다."""
    conflicts = year_end_conflicts(
        "(2019.12)",
        "2019.12",
        None,
        "2019.01.01부터2019.12.31까지",
    )
    assert conflicts == []


def test_year_end_conflicts_when_period_differs() -> None:
    """결산월이 다르면 conflict를 남기고 listing 값은 바꾸지 않는다."""
    listing = "(2019.12)"
    conflicts = year_end_conflicts(
        listing,
        None,
        None,
        "2018.01.01부터2018.12.31까지",
    )
    assert listing == "(2019.12)"
    assert len(conflicts) == 1
    assert conflicts[0]["field"] == "year_end"
    assert conflicts[0]["left"] == "(2019.12)"
    assert conflicts[0]["right"] == "2018.01.01부터2018.12.31까지"
    assert conflicts[0]["left_source"] == "listing"
    assert conflicts[0]["right_source"] == "cover_period"


def test_year_end_month_only_activity_compares_month() -> None:
    """실시내용이 월만 있으면 listing (YYYY.MM)과 월만 비교하고 listing 원문은 유지한다."""
    listing = "(2019.12)"
    same = year_end_conflicts(listing, "12월", None, None)
    assert listing == "(2019.12)"
    assert same == []

    different = year_end_conflicts(listing, "3월", None, None)
    assert listing == "(2019.12)"
    assert len(different) == 1
    assert different[0]["field"] == "year_end"
    assert different[0]["left"] == "(2019.12)"
    assert different[0]["right"] == "3월"
    assert different[0]["left_source"] == "listing"
    assert different[0]["right_source"] == "activity"
