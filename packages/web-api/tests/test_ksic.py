"""KSIC 제10·11차 코드 → 계층 이름 매퍼 테스트."""

from __future__ import annotations

from app.ksic import (
    KsicEntry,
    hierarchy_rows_from_ksic11_link,
    load_ksic_table,
    names_for,
    names_for_preferred,
    strip_division_range,
    table_from_hierarchy_rows,
)


def _table() -> dict[str, KsicEntry]:
    return {
        "C": KsicEntry(name="제조업", parent=None, level="div"),
        "26": KsicEntry(
            name="전자부품, 컴퓨터, 영상, 음향 및 통신장비 제조업",
            parent="C",
            level="group",
        ),
        "264": KsicEntry(name="통신 및 방송 장비 제조업", parent="26", level="class"),
        "2642": KsicEntry(
            name="방송 및 무선 통신장비 제조업", parent="264", level="subclass"
        ),
        "26421": KsicEntry(
            name="방송장비 제조업", parent="2642", level="item"
        ),
    }


def test_names_for_class_code_fills_div_group_class_only() -> None:
    """3자리 소분류는 세·세세를 비운다."""
    names = names_for("264", _table())
    assert names.induty_name_div == "제조업"
    assert names.induty_name_group == "전자부품, 컴퓨터, 영상, 음향 및 통신장비 제조업"
    assert names.induty_name_class == "통신 및 방송 장비 제조업"
    assert names.induty_name_subclass is None
    assert names.induty_name_item is None


def test_names_for_item_code_fills_all_levels() -> None:
    """5자리 세세분류는 다섯 칸을 채운다."""
    names = names_for("26421", _table())
    assert names.induty_name_item == "방송장비 제조업"
    assert names.induty_name_subclass == "방송 및 무선 통신장비 제조업"
    assert names.induty_name_class == "통신 및 방송 장비 제조업"


def test_names_for_unknown_code_returns_all_none() -> None:
    """표에 없으면 이름은 전부 NULL이다. 접두 추정은 하지 않는다."""
    names = names_for("99999", _table())
    assert names.induty_name_div is None
    assert names.induty_name_item is None


def test_names_for_strips_whitespace_and_empty_is_blank() -> None:
    """앞뒤 공백은 제거하고, 빈 코드는 이름을 비운다."""
    assert names_for(" 264 ", _table()).induty_name_class == "통신 및 방송 장비 제조업"
    assert names_for(None, _table()).induty_name_class is None
    assert names_for("", _table()).induty_name_class is None


def test_strip_division_range_removes_trailing_code_span() -> None:
    """대분류 이름 끝의 (10~34)·(35)만 떼고, 범위가 없으면 그대로 둔다."""
    assert strip_division_range("제조업(10~34)") == "제조업"
    assert (
        strip_division_range("전기, 가스, 증기 및 공기 조절 공급업(35)")
        == "전기, 가스, 증기 및 공기 조절 공급업"
    )
    assert strip_division_range("농업, 임업 및 어업") == "농업, 임업 및 어업"


def test_table_from_hierarchy_rows_forward_fills_and_strips_div() -> None:
    """빈 상위 칸은 이전 행 코드를 이어 받고, 대분류 범위 표기는 뺀다."""
    rows = [
        [
            "A",
            "농업, 임업 및 어업(01~03)",
            "01",
            "농업",
            "011",
            "작물 재배업",
            "0111",
            "곡물 및 기타 식량작물 재배업",
            "01110",
            "곡물 및 기타 식량작물 재배업",
        ],
        [None, None, None, None, None, None, "0112", "채소, 화훼작물 및 종묘 재배업", "01121", "채소작물 재배업"],
        [
            "C",
            "제조업(10~34)",
            "26",
            "전자 부품, 컴퓨터, 영상, 음향 및 통신장비 제조업",
            "264",
            "통신 및 방송장비 제조업",
            "2642",
            "방송 및 무선 통신장비 제조업",
            "26421",
            "방송장비 제조업",
        ],
    ]
    table = table_from_hierarchy_rows(rows)
    assert table["A"].name == "농업, 임업 및 어업"
    assert table["A"].parent is None
    assert table["A"].level == "div"
    assert table["0112"].parent == "011"
    assert table["01121"].parent == "0112"
    assert table["C"].name == "제조업"
    names = names_for("26421", table)
    assert names.induty_name_div == "제조업"
    assert names.induty_name_item == "방송장비 제조업"


def test_load_ksic_table_includes_sample_264() -> None:
    """저장소 코드표에 설계 예시 264가 있다."""
    table = load_ksic_table()
    names = names_for("264", table)
    assert names.induty_name_class is not None
    assert names.induty_name_div is not None


def test_names_for_preferred_uses_primary_then_fallback() -> None:
    """11차에 있으면 그 이름을 쓰고, 없을 때만 10차를 쓴다. 부모 사슬은 섞지 않는다."""
    ksic11 = {
        "C": KsicEntry(name="제조업", parent=None, level="div"),
        "21": KsicEntry(name="의료용 물질 및 의약품 제조업", parent="C", level="group"),
        "212": KsicEntry(name="의약품 제조업", parent="21", level="class"),
        "2121": KsicEntry(name="완제 의약품 제조업", parent="212", level="subclass"),
        "21212": KsicEntry(
            name="합성의약품 및 기타 완제 의약품 제조업", parent="2121", level="item"
        ),
    }
    ksic10 = {
        "C": KsicEntry(name="제조업10", parent=None, level="div"),
        "21210": KsicEntry(name="완제 의약품 제조업", parent="C", level="item"),
    }
    eleven = names_for_preferred("21212", ksic11, ksic10)
    assert eleven.induty_name_item == "합성의약품 및 기타 완제 의약품 제조업"
    assert eleven.induty_name_div == "제조업"
    ten_only = names_for_preferred("21210", ksic11, ksic10)
    assert ten_only.induty_name_item == "완제 의약품 제조업"
    assert ten_only.induty_name_div == "제조업10"
    assert names_for_preferred("99999", ksic11, ksic10).induty_name_item is None


def test_hierarchy_rows_from_ksic11_link_uses_right_block() -> None:
    """연계표 오른쪽 표준산업분류(11차)만 계층 10열로 뽑는다."""
    sheet = [[None] * 23 for _ in range(6)]
    sheet[5][13] = "21212"
    sheet[5][14] = "C"
    sheet[5][15] = "제조업"
    sheet[5][16] = "21"
    sheet[5][17] = "의료용 물질 및 의약품 제조업"
    sheet[5][18] = "212"
    sheet[5][19] = "의약품 제조업"
    sheet[5][20] = "2121"
    sheet[5][21] = "완제 의약품 제조업"
    sheet[5][22] = "합성의약품 및 기타 완제 의약품 제조업"
    rows = hierarchy_rows_from_ksic11_link(sheet)
    table = table_from_hierarchy_rows(rows)
    assert table["21212"].name == "합성의약품 및 기타 완제 의약품 제조업"
    assert table["21212"].parent == "2121"
    assert names_for("21212", table).induty_name_div == "제조업"


def test_load_ksic_table_covers_official_10th_counts() -> None:
    """저장소 표는 제10차 전 계층이고 대분류 이름에 범위 표기가 없다."""
    table = load_ksic_table()
    by_level: dict[str, int] = {}
    for entry in table.values():
        by_level[entry.level] = by_level.get(entry.level, 0) + 1
    assert by_level["div"] == 21
    assert by_level["group"] == 77
    assert by_level["class"] == 232
    assert by_level["subclass"] == 495
    assert by_level["item"] == 1196
    assert len(table) == 2021
    assert table["C"].name == "제조업"
    names = names_for("264", table)
    assert names.induty_name_div == "제조업"
    assert names.induty_name_class == "통신 및 방송장비 제조업"


def test_load_ksic11_table_includes_21212() -> None:
    """11차 표에 OpenDART 미적중 예시 21212가 있고 대분류까지 이어진다."""
    from app.ksic import KSIC11_PATH, load_ksic_tables, names_for_preferred

    table11 = load_ksic_table(KSIC11_PATH)
    by_level: dict[str, int] = {}
    for entry in table11.values():
        by_level[entry.level] = by_level.get(entry.level, 0) + 1
    assert by_level["div"] == 21
    assert by_level["item"] == 1257
    assert len(table11) == 2090
    names = names_for("21212", table11)
    assert names.induty_name_item == "합성의약품 및 기타 완제 의약품 제조업"
    assert names.induty_name_div == "제조업"
    primary, fallback = load_ksic_tables()
    assert names_for_preferred("21212", primary, fallback).induty_name_item is not None
    assert names_for_preferred("264", primary, fallback).induty_name_class is not None
