"""Entry ordinal 스키마 테스트."""

from __future__ import annotations

from app.schemas.catalog_query import EntrySummary
from app.schemas.entry import EntryRecord


def test_entry_record_accepts_ordinal() -> None:
    record = EntryRecord.model_validate(
        {
            "entry_id": "20260724000650_1_1",
            "rcept_no": "20260724000650",
            "source": "body",
            "ordinal": 3,
            "path": ["감사보고서"],
        }
    )
    assert record.ordinal == 3


def test_entry_summary_includes_full_leaf_features() -> None:
    class _Row:
        entry_id = "e1"
        rcept_no = "20260724000650"
        report_type = "F001"
        correction_type = "기재정정"
        report_nm = "감사보고서"
        year_end = "(2025.12)"
        corp_code = "00224628"
        corp_name = "테스트"
        submitter = "한울회계법인"
        rcept_dt = "2026.07.24"
        bsns_year = None
        disclosure_url = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260724000650"
        source = "body"
        dcm_no = "1"
        document_name = "감사보고서"
        section_name = "재무상태표"
        section_original_name = "재 무 상 태 표"
        depth = 2
        ordinal = 7
        is_leaf = True
        parent_ele_id = "4"
        ele_id = "1"
        offset = "100"
        length = "200"
        dtd = "dart4.xsd"
        path = ["감사보고서", "재무상태표"]
        viewer_url = "https://example.com/viewer"

    summary = EntrySummary.from_model(_Row())
    assert summary.ordinal == 7
    assert summary.rcept_no == "20260724000650"
    assert summary.viewer_url == "https://example.com/viewer"
    assert summary.section_original_name == "재 무 상 태 표"
    assert summary.correction_type == "기재정정"
    assert summary.parent_ele_id == "4"
    assert summary.dtd == "dart4.xsd"
