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


def test_entry_summary_includes_ordinal() -> None:
    class _Row:
        entry_id = "e1"
        source = "body"
        dcm_no = "1"
        ele_id = "1"
        document_name = "감사보고서"
        section_name = "재무상태표"
        path = ["감사보고서", "재무상태표"]
        depth = 2
        ordinal = 7

    summary = EntrySummary.from_model(_Row())
    assert summary.ordinal == 7
