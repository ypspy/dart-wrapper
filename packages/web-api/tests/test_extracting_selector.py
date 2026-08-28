"""감사보고서 selector·텍스트 정규화 테스트."""

from app.extracting.selector import (
    SelectorEntry,
    fs_scope_for,
    group_by_dcm,
    is_audit_document,
    select_leaves,
)
from app.extracting.text import compact


def test_compact_strips_spaces() -> None:
    assert compact("독립된 감사인의 감사보고서") == "독립된감사인의감사보고서"
    assert compact(None) == ""


def test_rejects_statutory_auditor_report() -> None:
    assert not is_audit_document("A001", "attachment", "감사의감사보고서")
    assert not is_audit_document(
        "A001", "attachment", "내부회계관리제도운영보고서"
    )


def test_accepts_f001_and_a001_attachment() -> None:
    assert is_audit_document("F001", "body", "감사보고서")
    assert is_audit_document("A001", "attachment", "연결감사보고서")
    assert not is_audit_document("A001", "body", "사업보고서")


def test_select_leaves_f001() -> None:
    rows = [
        SelectorEntry("c", "r", "d", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry(
            "o", "r", "d", "F001", "body", "감사보고서", "독립된 감사인의 감사보고서"
        ),
        SelectorEntry("a", "r", "d", "F001", "body", "감사보고서", "외부감사 실시내용"),
        SelectorEntry(
            "x", "r", "d", "F001", "body", "감사보고서", "내부회계관리제도 검토의견"
        ),
    ]
    leaves = select_leaves(rows)
    assert leaves.cover_entry_id == "c"
    assert leaves.opinion_entry_id == "o"
    assert leaves.activity_entry_id == "a"
    assert leaves.a001_opinion_entry_id is None


def test_f001_body_does_not_fill_a001_leaves() -> None:
    """F001 본문 섹션명이 A001 전용 leaf로 오선택되지 않는다."""
    rows = [
        SelectorEntry("c", "r", "d", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry(
            "n1", "r", "d", "F001", "body", "감사보고서", "1. 외부감사에 관한 사항"
        ),
        SelectorEntry("cov", "r", "d", "F001", "body", "사업보고서", "사업보고서"),
    ]
    leaves = select_leaves(rows)
    assert leaves.a001_opinion_entry_id is None
    assert leaves.a001_cover_entry_id is None


def test_select_a001_opinion_prefers_numbered_section() -> None:
    same = dict(rcept_no="r", dcm_no="att", report_type="A001", source="attachment")
    body = dict(
        rcept_no="r",
        dcm_no="body",
        report_type="A001",
        source="body",
        document_name="사업보고서",
    )
    rows = [
        SelectorEntry(
            "att-c", **same, document_name="감사보고서", section_name="감사보고서"
        ),
        SelectorEntry("ch", **body, section_name="V. 감사인의 감사의견 등"),
        SelectorEntry("n1", **body, section_name="1. 외부감사에 관한 사항"),
        SelectorEntry("skip", **body, section_name="2. 감사제도에 관한 사항"),
        SelectorEntry("cov", **body, section_name="사업보고서"),
    ]
    leaves = select_leaves(rows)
    assert leaves.a001_opinion_entry_id == "n1"
    assert leaves.a001_cover_entry_id == "cov"


def test_fs_scope_for() -> None:
    assert fs_scope_for("F001", "감사보고서") == "separate"
    assert fs_scope_for("F002", "연결감사보고서") == "consolidated"
    assert fs_scope_for("A001", "감사보고서") == "separate"
    assert fs_scope_for("A001", "연결감사보고서") == "consolidated"
    assert fs_scope_for("A001", "사업보고서") == "unknown"
    assert fs_scope_for("Z999", None) == "unknown"


def test_group_by_dcm() -> None:
    e1 = SelectorEntry("a", "r", "d1", "F001", "body", "감사보고서", "감사보고서")
    e2 = SelectorEntry("b", "r", "d1", "F001", "body", "감사보고서", "외부감사 실시내용")
    e3 = SelectorEntry("c", "r", "d2", "F002", "body", "연결감사보고서", "감사보고서")
    grouped = group_by_dcm([e1, e2, e3])
    assert grouped == {"d1": [e1, e2], "d2": [e3]}
