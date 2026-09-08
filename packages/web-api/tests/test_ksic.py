"""KSIC 제10차 코드 → 계층 이름 매퍼 테스트."""

from __future__ import annotations

from app.ksic import KsicEntry, load_ksic_table, names_for


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


def test_load_ksic_table_includes_sample_264() -> None:
    """저장소 코드표에 설계 예시 264가 있다."""
    table = load_ksic_table()
    names = names_for("264", table)
    assert names.induty_name_class is not None
    assert names.induty_name_div is not None
