"""수집 포트 스키마(목록 결과·공시 항목) 검증."""

from __future__ import annotations

from app.ports.entry_collector import DisclosureListItem, DisclosureListResult


def test_disclosure_list_item_accepts_node_camel_case() -> None:
    item = DisclosureListItem.model_validate(
        {
            "reportType": "F001",
            "rcept_no": "20260724000650",
            "corp_code": "00224628",
            "corp_name": "테스트",
            "report_nm": "감사보고서",
            "rcept_dt": "2026.07.24",
            "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260724000650",
            "correction_type": "최초공시",
        }
    )

    assert item.rcept_no == "20260724000650"
    assert item.report_type == "F001"
    # Node 원본 필드를 그대로 되돌려 줄 수 있어야 extract 모드에 전달할 수 있다.
    assert item.to_node_payload()["url"].endswith("rcpNo=20260724000650")
    assert item.to_node_payload()["reportType"] == "F001"


def test_disclosure_list_result_holds_listed_count() -> None:
    result = DisclosureListResult.model_validate(
        {
            "listed_count": 2,
            "items": [
                {"rcept_no": "1", "reportType": "F001", "url": "https://dart.fss.or.kr/a"},
                {"rcept_no": "2", "reportType": "F001", "url": "https://dart.fss.or.kr/b"},
            ],
        }
    )

    assert result.listed_count == 2
    assert [item.rcept_no for item in result.items] == ["1", "2"]
