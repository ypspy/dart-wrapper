"""보고서 유형 코드·명칭 매핑 테스트."""

from app.report_types import report_type_label, report_type_options


def test_known_codes_return_korean_labels() -> None:
    assert report_type_label("A001") == "사업보고서"
    assert report_type_label("A002") == "반기보고서"
    assert report_type_label("A003") == "분기보고서"
    assert report_type_label("F001") == "감사보고서"
    assert report_type_label("F002") == "연결감사보고서"
    assert report_type_label("F004") == "회계법인사업보고서"


def test_unknown_code_falls_back_to_normalized_code() -> None:
    assert report_type_label(" z999 ") == "Z999"


def test_options_keep_input_order() -> None:
    assert report_type_options(("F002", "A001")) == [
        {"code": "F002", "label": "연결감사보고서"},
        {"code": "A001", "label": "사업보고서"},
    ]
