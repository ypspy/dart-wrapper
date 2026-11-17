"""A002·A003 검토보고서 selector 테스트. 합성 문서명만 쓴다."""

from __future__ import annotations

import pytest

from research.extracting.interim_selector import (
    collect_interim_document_keys,
    interim_doc_kind,
    interim_fs_scope,
    interim_review_kind,
    is_interim_review_document,
    select_interim_leaves,
)
from research.extracting.selector import SelectorEntry

_FOREIGN_HALF = "외국법인등의반기검토ㆍ감사보고서"
_FOREIGN_QUARTER = "외국법인등의분기연결검토ㆍ감사보고서"

_CASES = [
    ("A002", "attachment", "반기검토보고서", "review", "half", "separate"),
    ("A002", "attachment", "반기연결검토보고서", "review", "half", "consolidated"),
    ("A003", "attachment", "분기검토보고서", "review", "quarter", "separate"),
    ("A003", "attachment", "분기연결검토보고서", "review", "quarter", "consolidated"),
    ("A002", "attachment", "[정정] 반기검토보고서", "review", "half", "separate"),
    ("A002", "attachment", "[정정][정정] 반기검토보고서", "review", "half", "separate"),
    ("A002", "attachment", "반기\t검토보고서", "review", "half", "separate"),
    ("A002", "attachment", "반기감사보고서", "audit", "half", "separate"),
    ("A002", "attachment", "반기연결감사보고서", "audit", "half", "consolidated"),
    ("A003", "attachment", "분기감사보고서", "audit", "quarter", "separate"),
    ("A003", "attachment", "분기연결감사보고서", "audit", "quarter", "consolidated"),
    ("A002", "attachment", _FOREIGN_HALF, "foreign_mixed", "half", "separate"),
    ("A003", "attachment", _FOREIGN_QUARTER, "foreign_mixed", "quarter", "consolidated"),
    ("A002", "body", "반기검토보고서", None, None, "unknown"),
    ("A002", "attachment", "기타공시첨부서류", None, None, "unknown"),
    ("A002", "attachment", "회계감사인의 사유서", None, None, "unknown"),
    ("A002", "attachment", "반기검토보고서 사유서", None, None, "unknown"),
    ("A002", "attachment", "내부회계관리제도운영보고서", None, None, "unknown"),
    ("A002", "attachment", "내부감시장치에 대한 검토", None, None, "unknown"),
    ("A001", "attachment", "감사보고서", None, None, "unknown"),
    ("F001", "body", "감사보고서", None, None, "unknown"),
    ("A002", "attachment", "사업보고서", None, None, "unknown"),
]


@pytest.mark.parametrize(
    ("report_type", "source", "document_name", "doc_kind", "review_kind", "fs_scope"),
    _CASES,
)
def test_interim_document_name_table(
    report_type: str,
    source: str,
    document_name: str,
    doc_kind: str | None,
    review_kind: str | None,
    fs_scope: str,
) -> None:
    """대상·제외 문서명마다 종류·반기/분기·연결 범위를 가른다."""
    assert interim_doc_kind(report_type, source, document_name) == doc_kind
    assert is_interim_review_document(report_type, source, document_name) is (doc_kind is not None)
    assert interim_review_kind(report_type, source, document_name) == review_kind
    assert interim_fs_scope(report_type, source, document_name) == fs_scope


def test_collect_interim_document_keys_keeps_first_seen_targets() -> None:
    """대상만, 빈 dcm과 중복은 빼고 등장 순을 유지한다."""
    rows = [
        ("r1", "d1", "A002", "attachment", "반기검토보고서"),
        ("r1", "d1", "A002", "attachment", "반기검토보고서"),
        ("r1", None, "A002", "attachment", "반기검토보고서"),
        ("r1", "d2", "A002", "body", "반기검토보고서"),
        ("r2", "d3", "A003", "attachment", "분기연결검토보고서"),
        ("r3", "d4", "A002", "attachment", "기타공시첨부서류"),
    ]
    assert collect_interim_document_keys(rows) == [("r1", "d1"), ("r2", "d3")]


def _entry(
    entry_id: str,
    section_name: str,
    *,
    document_name: str = "반기검토보고서",
    report_type: str = "A002",
) -> SelectorEntry:
    return SelectorEntry(
        entry_id,
        "r",
        "d",
        report_type,
        "attachment",
        document_name,
        section_name,
    )


def test_select_interim_leaves_review_document() -> None:
    """검토보고서는 표지·결론·첨부 제표·주석을 고르고 주석 붙은 첨부는 부모가 아니다."""
    leaves = select_interim_leaves(
        [
            _entry("cover", "검토보고서"),
            _entry("report", "반기 재무제표 검토보고서"),
            _entry("parent", "(첨부)반기재무제표"),
            _entry("notes-parent", "(첨부)반기재무제표 주석"),
            _entry("notes", "주석"),
        ]
    )
    assert leaves.cover_entry_id == "cover"
    assert leaves.report_entry_id == "report"
    assert leaves.fs_parent_entry_id == "parent"
    assert leaves.notes_entry_id == "notes"


def test_select_interim_leaves_consolidated_report_name() -> None:
    """연결 검토보고서 섹션명도 report leaf다."""
    leaves = select_interim_leaves(
        [
            _entry("cover", "검토보고서", document_name="분기연결검토보고서", report_type="A003"),
            _entry(
                "report",
                "분기연결재무제표 검토보고서",
                document_name="분기연결검토보고서",
                report_type="A003",
            ),
        ]
    )
    assert leaves.report_entry_id == "report"


def test_audit_document_accepts_independent_auditor_report_leaf() -> None:
    """doc_kind가 audit이면 독립된 감사인의 감사보고서를 report leaf로 본다."""
    leaves = select_interim_leaves(
        [
            _entry("cover", "감사보고서", document_name="반기감사보고서"),
            _entry(
                "report",
                "독립된 감사인의 감사보고서",
                document_name="반기감사보고서",
            ),
        ]
    )
    assert leaves.cover_entry_id == "cover"
    assert leaves.report_entry_id == "report"


def test_review_document_does_not_use_audit_report_leaf() -> None:
    """검토 문서는 감사보고서 섹션명을 report leaf로 쓰지 않는다."""
    leaves = select_interim_leaves(
        [
            _entry("cover", "검토보고서"),
            _entry("opinion", "독립된 감사인의 감사보고서"),
        ]
    )
    assert leaves.report_entry_id is None
    assert leaves.cover_entry_id == "cover"
