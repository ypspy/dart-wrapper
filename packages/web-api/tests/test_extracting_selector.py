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
    assert leaves.icfr_entry_id == "x"
    assert leaves.a001_opinion_entry_id is None
    assert leaves.notes_entry_id is None
    assert leaves.a001_affiliate_entry_id is None


def test_select_leaves_separate_ignores_consolidated_icfr() -> None:
    """별도 문서는 연결내부회계 leaf를 고르지 않는다."""
    rows = [
        SelectorEntry("c", "r", "d", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry(
            "con", "r", "d", "F001", "body", "감사보고서",
            "연결 내부회계관리제도 감사 또는 검토의견",
        ),
        SelectorEntry(
            "sep", "r", "d", "F001", "body", "감사보고서",
            "내부회계관리제도 감사 또는 검토의견",
        ),
    ]
    leaves = select_leaves(rows)
    assert leaves.icfr_entry_id == "sep"


def test_select_leaves_consolidated_prefers_consolidated_icfr() -> None:
    """연결 문서는 연결내부회계 leaf만 고른다."""
    rows = [
        SelectorEntry("c", "r", "d", "F002", "body", "연결감사보고서", "감사보고서"),
        SelectorEntry(
            "sep", "r", "d", "F002", "body", "연결감사보고서",
            "내부회계관리제도 검토의견",
        ),
        SelectorEntry(
            "con", "r", "d", "F002", "body", "연결감사보고서",
            "연결 내부회계관리제도 감사 또는 검토의견",
        ),
    ]
    leaves = select_leaves(rows)
    assert leaves.icfr_entry_id == "con"


def test_select_leaves_icfr_ignores_notes_and_other_dcm() -> None:
    """주석·다른 dcm의 내부회계는 고르지 않는다."""
    rows = [
        SelectorEntry("c", "r", "d1", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry(
            "n", "r", "d1", "F001", "body", "감사보고서", "내부회계관리제도 주석"
        ),
        SelectorEntry(
            "other", "r", "d2", "F001", "body", "감사보고서",
            "내부회계관리제도 검토의견",
        ),
    ]
    leaves = select_leaves(rows)
    assert leaves.icfr_entry_id is None


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


def test_select_leaves_prefers_bs_is_leaves() -> None:
    """재무상태표·손익계산서 leaf가 있으면 부모를 쓰지 않는다."""
    rows = [
        SelectorEntry("c", "r", "d", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry("p", "r", "d", "F001", "body", "감사보고서", "(첨부)재무제표"),
        SelectorEntry("bs", "r", "d", "F001", "body", "감사보고서", "재무상태표"),
        SelectorEntry("is_", "r", "d", "F001", "body", "감사보고서", "손익계산서"),
        SelectorEntry("n", "r", "d", "F001", "body", "감사보고서", "주석"),
    ]
    leaves = select_leaves(rows)
    assert leaves.bs_entry_id == "bs"
    assert leaves.is_entry_id == "is_"
    assert leaves.fs_parent_entry_id is None


def test_select_leaves_consolidated_statement_names() -> None:
    """연결 제표 섹션명을 BS/IS로 고른다."""
    rows = [
        SelectorEntry("c", "r", "d", "F002", "body", "연결감사보고서", "감사보고서"),
        SelectorEntry("bs", "r", "d", "F002", "body", "연결감사보고서", "연결재무상태표"),
        SelectorEntry("is_", "r", "d", "F002", "body", "연결감사보고서", "연결손익계산서"),
    ]
    leaves = select_leaves(rows)
    assert leaves.bs_entry_id == "bs"
    assert leaves.is_entry_id == "is_"


def test_select_leaves_falls_back_to_fs_parent_when_only_notes() -> None:
    """본표 leaf가 없고 주석만 있으면 부모 (첨부)연결재무제표를 쓴다."""
    rows = [
        SelectorEntry("c", "r", "d", "F002", "body", "연결감사보고서", "감사보고서"),
        SelectorEntry("p", "r", "d", "F002", "body", "연결감사보고서", "(첨부)연결재무제표"),
        SelectorEntry("n", "r", "d", "F002", "body", "연결감사보고서", "주석"),
    ]
    leaves = select_leaves(rows)
    assert leaves.bs_entry_id is None
    assert leaves.is_entry_id is None
    assert leaves.fs_parent_entry_id == "p"


def test_select_leaves_prefers_income_over_comprehensive() -> None:
    """손익계산서가 있으면 포괄손익계산서를 IS로 쓰지 않는다."""
    rows = [
        SelectorEntry("c", "r", "d", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry("is_", "r", "d", "F001", "body", "감사보고서", "손익계산서"),
        SelectorEntry("ci", "r", "d", "F001", "body", "감사보고서", "포괄손익계산서"),
    ]
    leaves = select_leaves(rows)
    assert leaves.is_entry_id == "is_"


def test_select_leaves_ignores_other_dcm_statements() -> None:
    """다른 dcm의 제표는 고르지 않는다."""
    rows = [
        SelectorEntry("c", "r", "d1", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry("bs", "r", "d2", "F001", "body", "감사보고서", "재무상태표"),
    ]
    leaves = select_leaves(rows)
    assert leaves.bs_entry_id is None


def test_select_leaves_excludes_bs_notes_section() -> None:
    """'재무상태표에 대한 주석'은 BS가 아니며 부모 fallback을 살린다."""
    rows = [
        SelectorEntry("c", "r", "d", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry("p", "r", "d", "F001", "body", "감사보고서", "(첨부)재무제표"),
        SelectorEntry(
            "n", "r", "d", "F001", "body", "감사보고서", "재무상태표에 대한 주석"
        ),
    ]
    leaves = select_leaves(rows)
    assert leaves.bs_entry_id is None
    assert leaves.is_entry_id is None
    assert leaves.fs_parent_entry_id == "p"


def test_select_leaves_consolidated_picks_exact_notes() -> None:
    """연결 문서의 정확 주석 leaf만 고르고 본표 주석은 제외한다."""
    rows = [
        SelectorEntry("c", "r", "d", "F002", "body", "연결감사보고서", "감사보고서"),
        SelectorEntry("n", "r", "d", "F002", "body", "연결감사보고서", "주석"),
        SelectorEntry(
            "bsn", "r", "d", "F002", "body", "연결감사보고서", "재무상태표에 대한 주석"
        ),
    ]
    leaves = select_leaves(rows)
    assert leaves.notes_entry_id == "n"


def test_select_leaves_separate_skips_notes() -> None:
    """별도 문서는 주석 leaf를 고르지 않는다."""
    rows = [
        SelectorEntry("c", "r", "d", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry("n", "r", "d", "F001", "body", "감사보고서", "주석"),
    ]
    leaves = select_leaves(rows)
    assert leaves.notes_entry_id is None


def test_select_leaves_a001_affiliate_prefers_status_section() -> None:
    """계열회사 현황이 부모보다 앞이고 타법인출자는 제외한다."""
    rows = [
        SelectorEntry("c", "r", "d1", "A001", "attachment", "연결감사보고서", "감사보고서"),
        SelectorEntry(
            "parent", "r", "d2", "A001", "body", "사업보고서", "IX. 계열회사 등에 관한 사항"
        ),
        SelectorEntry(
            "status", "r", "d2", "A001", "body", "사업보고서", "1. 계열회사의 현황"
        ),
        SelectorEntry(
            "inv", "r", "d2", "A001", "body", "사업보고서", "타법인출자 현황"
        ),
    ]
    leaves = select_leaves(rows)
    assert leaves.a001_affiliate_entry_id == "status"


def test_select_leaves_ci_only_sets_is_entry_id() -> None:
    """포괄손익계산서만 있어도 is_entry_id를 채운다."""
    rows = [
        SelectorEntry("c", "r", "d", "F001", "body", "감사보고서", "감사보고서"),
        SelectorEntry("ci", "r", "d", "F001", "body", "감사보고서", "포괄손익계산서"),
    ]
    leaves = select_leaves(rows)
    assert leaves.is_entry_id == "ci"
    assert leaves.bs_entry_id is None
