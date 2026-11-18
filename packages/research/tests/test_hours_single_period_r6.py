"""r6 새 테스트(안 G 기대값). 지시서 §R22 참고 구현. e2e 도우미를 그대로 쓴다."""

from __future__ import annotations

import re

from hours_period_samples import single_period_hours
from research.extracting.activity_hours import extract_hours
from research.extracting.hours_period import _plain, is_single_period_hours
from research.extracting.text import compact
from test_hours_single_period_e2e import _assert_accepted, _assert_missing, _read, _three

_HC = ("투입 인원수", ["1", "4", "5"])
_AU = ("감사", ["40", "50", "90"])


def _table(rows: list[str]) -> str:
    return "<table>" + "".join(f"<tr>{row}</tr>" for row in rows) + "</table>"


def _page(*tables: str) -> str:
    return "<html><body>" + "".join(tables) + "</body></html>"


_HC_ROW = "<td>투입 인원수</td><td>1</td><td>4</td><td>5</td>"
_AU_ROW = "<td>감사</td><td>40</td><td>50</td><td>90</td>"

_COMPARATIVE = _table(
    [
        "<td rowspan='2'>구분</td><td colspan='2'>담당이사</td>"
        "<td colspan='2'>등록공인회계사</td><td colspan='2'>합계</td>",
        "<td>당기</td><td>전기</td>" * 3,
        "<td>투입 인원수</td><td>2</td><td>1</td><td>5</td><td>4</td><td>7</td><td>5</td>",
        "<td>감사</td><td>40</td><td>30</td><td>60</td><td>50</td><td>100</td><td>80</td>",
    ]
)


def _first_80(corner: str) -> str:
    return _table(
        [
            f"<td>{corner}</td><td>담당이사</td><td>등록공인회계사</td><td>합계</td>",
            _HC_ROW,
            "<td>감사</td><td>30</td><td>50</td><td>80</td>",
        ]
    )


_NESTED = _table(
    [
        "<td rowspan='2'>감사참여자 ＼ 인원수 및 시간</td>"
        "<td rowspan='2'>품질관리검토자(심리실 등)</td>"
        "<td colspan='3'>감사업무 담당 회계사</td>"
        "<td rowspan='2'>전산감사ㆍ세무ㆍ가치평가 등 전문가</td><td rowspan='2'>합계</td>",
        "<td>담당이사(업무수행이사)</td><td>등록공인회계사</td><td>수습공인회계사</td>",
        "<td>투입 인원수</td><td>1</td><td>1</td><td>4</td><td>3</td><td>1</td><td>10</td>",
        "<td>분ㆍ반기검토</td><td>0</td><td>2</td><td>8</td><td>6</td><td>0</td><td>16</td>",
        "<td>감사</td><td>2</td><td>6</td><td>30</td><td>24</td><td>2</td><td>64</td>",
        "<td>합계</td><td>2</td><td>8</td><td>38</td><td>30</td><td>2</td><td>80</td>",
    ]
)

_NESTED_PERIOD = _table(
    [
        "<td rowspan='3'>감사참여자 ＼ 인원수 및 시간</td>"
        "<td colspan='2' rowspan='2'>품질관리검토자(심리실 등)</td>"
        "<td colspan='6'>감사업무 담당 회계사</td><td colspan='2' rowspan='2'>합계</td>",
        "<td colspan='2'>담당이사(업무수행이사)</td><td colspan='2'>등록공인회계사</td>"
        "<td colspan='2'>수습공인회계사</td>",
        "<td>당기</td><td>전기</td>" * 5,
        "<td>투입 인원수</td>" + "".join(f"<td>{v}</td>" for v in [1, 1, 1, 1, 4, 3, 4, 3, 10, 8]),
        "<td>감사</td>" + "".join(f"<td>{v}</td>" for v in [2, 2, 6, 5, 30, 24, 26, 20, 64, 51]),
    ]
)

_HIDDEN = ("\u200b", "\u00ad", "\u2060", "\ufeff", "\u200e")


def test_n36_hidden_period_word_in_role_raw_is_missing() -> None:
    """「담당이사(전?기)」처럼 당기/전기 사이에 서식 문자(Cf)가 끼면 missing이다.

    저장된 v19 칸(period_raw 빈 값) 형태의 dict에서도 가드가 거짓이다.
    """
    for index, char in enumerate(_HIDDEN):
        for word in (f"전{char}기", f"당{char}기"):
            header = f"담당이사({word})"
            cells = _assert_missing(_three(headers=[header, "등록공인회계사", "합계"]), 40 + index)
            assert {cell["period"] for cell in cells} == {"unknown"}
            assert any(cell["role_raw"] == header for cell in cells)
            stored = single_period_hours(audit_total=100, headcount_total=15)
            for cell in stored:
                if cell["role"] == "engagement_partner":
                    cell["role_raw"] = header
            assert is_single_period_hours(stored) is False


def test_n37_hidden_period_word_in_cell_raw_is_missing() -> None:
    """투입 인원수 칸 원문 「1(전\\u00ad기)」은 missing이다."""
    html = _three(rows=[("투입 인원수", ["1(전\u00ad기)", "4", "5"]), _AU])
    cells = _assert_missing(html, 50)
    assert any(cell["raw"] == "1(전\u00ad기)" for cell in cells)
    stored = single_period_hours(audit_total=100, headcount_total=15)
    stored[0]["raw"] = "1(전\u00ad기)"
    assert is_single_period_hours(stored) is False


def test_n38_plain_strips_compact_whitespace_and_format_chars() -> None:
    """_plain은 compact가 지우는 공백을 모두 지우고, 서식 문자(Cf)도 지운다."""
    samples = ["전\t기", "전\n기", "전\u00a0기", "전\u3000기", "전 기", "제 4 7 기"]
    for text in samples:
        assert _plain(text) == compact(text)
    for char in ("\u00ad", "\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u2060", "\ufeff"):
        assert _plain(f"전{char}기") == "전기"
    assert [_plain(value) for value in (None, 0, False, [], 47)] == ["", "", "", "", ""]


def test_n39_soft_hyphen_inside_fiscal_mark_is_missing() -> None:
    """「담당이사 제47\\u00ad기」는 missing이다."""
    html = _three(headers=["담당이사 제47\u00ad기", "등록공인회계사", "합계"])
    _assert_missing(html, 51)


def test_n40_fiscal_row_added_below_audit_is_missing() -> None:
    """감사 행(90)은 그대로 두고 행 라벨 「제47기」 행을 덧붙인 표는 missing이다(r5 J7 모양)."""
    html = _three(rows=[_HC, _AU, ("제47기", ["30", "50", "80"])])
    cells = _assert_missing(html, 52)
    assert any(cell["metric"] == "audit" and cell["value"] == 90 for cell in cells)
    assert any(cell["metric_raw"] == "제47기" for cell in cells)


def test_n41_unknown_row_with_fiscal_count_is_missing() -> None:
    """모르는 지표 행 「기타(2기 이월)」은 안 B 보수 판정으로 missing이다(r5 J13)."""
    html = _three(rows=[_HC, _AU, ("기타(2기 이월)", ["1", "1", "2"])])
    _assert_missing(html, 53)


def test_n42_period_like_row_labels_are_conservatively_missing() -> None:
    """「※ 제47기 기준」「12기간 누적」「전기간」「해당 기간」 행은 보수적으로 missing이다(한계 9)."""
    rows = [
        ("※ 제47기 기준", ["", "", ""]),
        ("12기간 누적", ["1", "1", "2"]),
        ("전기간", ["1", "1", "2"]),
        ("해당 기간", ["1", "1", "2"]),
    ]
    for index, row in enumerate(rows):
        _assert_missing(_three(rows=[_HC, _AU, row]), 54 + index)


def test_n43_first_header_fiscal_only_is_missing_like_master() -> None:
    """첫 헤더 행이 「제47기」(colspan)뿐이면 역할이 other가 되어 missing이다(master와 같음)."""
    html = _page(
        _table(
            [
                "<td rowspan='2'>구분</td><td colspan='3'>제47기</td>",
                "<td>담당이사</td><td>등록공인회계사</td><td>합계</td>",
                _HC_ROW,
                _AU_ROW,
            ]
        )
    )
    cells = _assert_missing(html, 58)
    assert {cell["role"] for cell in cells} == {"other"}


def test_n44_other_and_parent_only_columns_are_missing_like_master() -> None:
    """「기타」 열과 잎 없는 「감사업무 담당 회계사」 열은 role other라 missing이다(한계 3)."""
    for index, header in enumerate(("기타", "감사업무 담당 회계사")):
        html = _page(
            _table(
                [
                    (
                        f"<td>구분</td><td>담당이사</td><td>{header}</td><td>합계</td>"
                        if header == "기타"
                        else f"<td>구분</td><td>{header}</td><td>등록공인회계사</td><td>합계</td>"
                    ),
                    _HC_ROW,
                    _AU_ROW,
                ]
            )
        )
        cells = _assert_missing(html, 59 + index)
        assert any(cell["role"] == "other" for cell in cells)


def test_n45_audit_hours_row_label_is_not_audit_metric() -> None:
    """행 라벨 「감사시간」은 metric other다. 가드는 참이어도 감사 키가 없어 missing이다."""
    cells, guard, keys, signals, duplicate = _read(
        _three(rows=[_HC, ("감사시간", ["40", "50", "90"])]), 61
    )
    assert guard is True
    assert keys == (None, 5)
    assert signals == ["hours_total_missing"]
    assert duplicate is False
    assert not any(cell["metric"] == "audit" for cell in cells)


def test_n46_nested_parent_header_legacy_is_accepted() -> None:
    """중첩 부모 헤더 옛 서식은 가드 참 (64, 10)이고, 같은 골격의 당기/전기 표는 거짓 (64, 10)이다."""
    cells = _assert_accepted(_page(_NESTED), 62, (64, 10))
    assert len(cells) == 24
    assert {cell["period"] for cell in cells} == {"unknown"}
    assert any(cell["role"] == "junior_cpa" for cell in cells)
    cells, guard, keys, signals, duplicate = _read(_page(_NESTED_PERIOD), 63)
    assert guard is False
    assert keys == (64, 10)
    assert signals == []
    assert duplicate is False
    assert {cell["period"] for cell in cells} == {"current", "prior"}


def test_n47_corner_prior_table_before_comparative_is_known_limit() -> None:
    """모서리 「전기」 표(감사 80) 뒤에 비교표(당기 100)가 있으면 첫 표만 읽어 (80, 5)다.

    안 G: 한계 7·8로 현재 동작을 고정한다. 추출기 후속(PR15-EXT) 전까지의 알려진 오판이다.
    """
    cells = _assert_accepted(_page(_first_80("전기"), _COMPARATIVE), 64, (80, 5))
    assert cells == extract_hours(_page(_first_80("전기")))[0]


def test_n48_plain_first_table_before_comparative_is_known_limit() -> None:
    """모서리 「구분」 표(감사 80) 뒤 비교표도 첫 표만 읽어 (80, 5)다(한계 8, 두 안 공통)."""
    _assert_accepted(_page(_first_80("구분"), _COMPARATIVE), 65, (80, 5))


def test_n49_purpose_paths_stay_as_expected() -> None:
    """「당 기」/「전 기」 비교표는 거짓 (100, 7), 각주 행 「단위: 시간」은 참 (90, 5)다."""
    spaced = _COMPARATIVE.replace("<td>당기</td>", "<td>당 기</td>").replace(
        "<td>전기</td>", "<td>전 기</td>"
    )
    cells, guard, keys, signals, duplicate = _read(_page(spaced), 66)
    assert (guard, keys, signals, duplicate) == (False, (100, 7), [], False)
    footnote = _page(
        _table(
            [
                "<td>구분</td><td>담당이사</td><td>등록공인회계사</td><td>합계</td>",
                _HC_ROW,
                _AU_ROW,
                "<td colspan='4'>단위: 시간</td>",
            ]
        )
    )
    _assert_accepted(footnote, 67, (90, 5))


def test_n50_title_row_with_fiscal_mark_is_known_limit() -> None:
    """표 안 제목 행 「제47기 감사참여자 구분별 인원수 및 감사시간」은 칸에 남지 않아 참 (90, 5)다.

    안 G: 한계 5의 한 형태로 고정한다. 추출기 후속(PR15-EXT)에서 바뀐다.
    """
    html = _page(
        _table(
            [
                "<td colspan='4'>제47기 감사참여자 구분별 인원수 및 감사시간</td>",
                "<td>구분</td><td>담당이사</td><td>등록공인회계사</td><td>합계</td>",
                _HC_ROW,
                _AU_ROW,
            ]
        )
    )
    cells = _assert_accepted(html, 68, (90, 5))
    assert not any(re.search(r"\d+기", str(cell["period_raw"])) for cell in cells)
    assert is_single_period_hours(cells) is True
