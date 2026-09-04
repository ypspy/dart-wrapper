"""감사보고서 대상 문서·leaf selector."""

from __future__ import annotations

from dataclasses import dataclass

from app.extracting.text import compact

_AUDIT_DOC_EXCLUDE_MARKERS = ("내부회계", "내부감시장치", "감사의감사보고서")
_A001_ATTACHMENT_DOC_NAMES = frozenset({"감사보고서", "연결감사보고서"})
_OPINION_SECTION_NAMES = frozenset(
    {"독립된감사인의감사보고서", "외부감사인의감사보고서"}
)
_A001_OPINION_NUMBERED = "1.외부감사에관한사항"
_A001_OPINION_FALLBACK_MARKERS = ("감사인의감사의견등", "회계감사인의감사의견등")
_A001_OPINION_EXCLUDE = "2.감사제도에관한사항"


@dataclass(frozen=True)
class SelectorEntry:
    """카탈로그 entry 한 건."""

    entry_id: str
    rcept_no: str
    dcm_no: str
    report_type: str
    source: str
    document_name: str | None
    section_name: str | None


@dataclass(frozen=True)
class LeafIds:
    """감사보고서 추출 대상 leaf entry 식별자."""

    cover_entry_id: str | None
    opinion_entry_id: str | None
    activity_entry_id: str | None
    a001_opinion_entry_id: str | None
    a001_cover_entry_id: str | None
    bs_entry_id: str | None
    is_entry_id: str | None
    fs_parent_entry_id: str | None
    icfr_entry_id: str | None
    notes_entry_id: str | None
    a001_affiliate_entry_id: str | None


def is_audit_document(
    report_type: str | None,
    source: str,
    document_name: str | None,
) -> bool:
    """감사보고서 추출 대상 문서인지 판별한다."""
    if report_type in ("F001", "F002"):
        return True

    if report_type != "A001" or source != "attachment":
        return False

    compact_name = compact(document_name)
    if compact_name not in _A001_ATTACHMENT_DOC_NAMES:
        return False

    return not any(marker in compact_name for marker in _AUDIT_DOC_EXCLUDE_MARKERS)


def fs_scope_for(report_type: str, document_name: str | None) -> str:
    """재무제표 범위(separate/consolidated/unknown)를 반환한다."""
    if report_type == "F001":
        return "separate"
    if report_type == "F002":
        return "consolidated"

    if report_type == "A001":
        compact_name = compact(document_name)
        if compact_name == "연결감사보고서":
            return "consolidated"
        if compact_name == "감사보고서":
            return "separate"

    return "unknown"


def group_by_dcm(entries: list[SelectorEntry]) -> dict[str, list[SelectorEntry]]:
    """dcm_no별로 entry 목록을 묶는다."""
    grouped: dict[str, list[SelectorEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.dcm_no, []).append(entry)
    return grouped


def _is_cover_leaf(entry: SelectorEntry) -> bool:
    section = compact(entry.section_name)
    return section == "감사보고서"


def _is_opinion_leaf(entry: SelectorEntry) -> bool:
    return compact(entry.section_name) in _OPINION_SECTION_NAMES


def _is_activity_leaf(entry: SelectorEntry) -> bool:
    return compact(entry.section_name) == "외부감사실시내용"


def _is_a001_opinion_leaf(entry: SelectorEntry) -> bool:
    if entry.report_type != "A001" or entry.source != "body":
        return False
    section = compact(entry.section_name)
    if section == _A001_OPINION_EXCLUDE:
        return False
    if section == _A001_OPINION_NUMBERED:
        return True
    return any(marker in section for marker in _A001_OPINION_FALLBACK_MARKERS)


def _a001_opinion_priority(entry: SelectorEntry) -> int:
    """번호 섹션이 fallback보다 우선한다."""
    section = compact(entry.section_name)
    if section == _A001_OPINION_NUMBERED:
        return 0
    return 1


def _is_a001_cover_leaf(entry: SelectorEntry) -> bool:
    if entry.report_type != "A001" or entry.source != "body":
        return False
    return (
        compact(entry.document_name) == "사업보고서"
        and compact(entry.section_name) == "사업보고서"
    )


def _is_notes_section(entry: SelectorEntry) -> bool:
    return compact(entry.section_name) == "주석"


def _is_bs_section(entry: SelectorEntry) -> bool:
    token = compact(entry.section_name)
    if "주석" in token:
        return False
    return "연결재무상태표" in token or "재무상태표" in token


def _is_is_section(entry: SelectorEntry) -> bool:
    token = compact(entry.section_name)
    if _is_notes_section(entry) or "자본변동" in token or "현금흐름" in token:
        return False
    if "연결손익계산서" in token or (
        "손익계산서" in token and "포괄" not in token
    ):
        return True
    return False


def _is_ci_section(entry: SelectorEntry) -> bool:
    token = compact(entry.section_name)
    return "포괄손익계산서" in token


def _is_fs_parent(entry: SelectorEntry) -> bool:
    token = compact(entry.section_name)
    return "첨부" in token and "재무제표" in token and "주석" not in token


def _is_a001_affiliate_leaf(entry: SelectorEntry) -> bool:
    if entry.report_type != "A001" or entry.source != "body":
        return False
    token = compact(entry.section_name)
    if "타법인출자" in token:
        return False
    return "계열회사" in token


def _a001_affiliate_priority(entry: SelectorEntry) -> int:
    token = compact(entry.section_name)
    if "계열회사현황" in token or "계열회사의현황" in token:
        return 0
    return 1


def _is_icfr_section(entry: SelectorEntry, fs_scope: str) -> bool:
    """같은 dcm의 내부회계 leaf인지 본다. 주석은 제외한다."""
    token = compact(entry.section_name)
    if not token or "주석" in token:
        return False
    if "내부회계관리제도" not in token:
        return False
    if fs_scope == "consolidated":
        return "연결내부회계관리제도" in token
    return "연결" not in token


def _first_audit_dcm_no(entries: list[SelectorEntry]) -> str | None:
    for entry in entries:
        if is_audit_document(entry.report_type, entry.source, entry.document_name):
            return entry.dcm_no
    return None


def select_leaves(entries: list[SelectorEntry]) -> LeafIds:
    """같은 접수번호 entry 목록에서 추출 대상 leaf id를 선정한다."""
    audit_dcm_no = _first_audit_dcm_no(entries)
    audit_entries = (
        [entry for entry in entries if entry.dcm_no == audit_dcm_no]
        if audit_dcm_no is not None
        else []
    )
    sample = next(
        (
            entry
            for entry in audit_entries
            if is_audit_document(entry.report_type, entry.source, entry.document_name)
        ),
        None,
    )
    icfr_scope = (
        fs_scope_for(sample.report_type, sample.document_name)
        if sample is not None
        else "unknown"
    )

    cover_entry_id = next(
        (entry.entry_id for entry in audit_entries if _is_cover_leaf(entry)),
        None,
    )
    opinion_entry_id = next(
        (entry.entry_id for entry in audit_entries if _is_opinion_leaf(entry)),
        None,
    )
    activity_entry_id = next(
        (entry.entry_id for entry in audit_entries if _is_activity_leaf(entry)),
        None,
    )

    a001_opinion_candidates = [
        entry for entry in entries if _is_a001_opinion_leaf(entry)
    ]
    a001_opinion_entry_id = (
        min(a001_opinion_candidates, key=_a001_opinion_priority).entry_id
        if a001_opinion_candidates
        else None
    )

    a001_cover_entry_id = next(
        (entry.entry_id for entry in entries if _is_a001_cover_leaf(entry)),
        None,
    )

    bs_entry_id = next(
        (entry.entry_id for entry in audit_entries if _is_bs_section(entry)),
        None,
    )
    is_entry_id = next(
        (entry.entry_id for entry in audit_entries if _is_is_section(entry)),
        None,
    )
    if is_entry_id is None:
        is_entry_id = next(
            (entry.entry_id for entry in audit_entries if _is_ci_section(entry)),
            None,
        )
    fs_parent_candidate = next(
        (entry.entry_id for entry in audit_entries if _is_fs_parent(entry)),
        None,
    )
    fs_parent_entry_id = None
    if bs_entry_id is None and is_entry_id is None:
        fs_parent_entry_id = fs_parent_candidate

    icfr_entry_id = next(
        (
            entry.entry_id
            for entry in audit_entries
            if _is_icfr_section(entry, icfr_scope)
        ),
        None,
    )

    notes_entry_id = None
    if icfr_scope == "consolidated":
        notes_entry_id = next(
            (entry.entry_id for entry in audit_entries if _is_notes_section(entry)),
            None,
        )
        if (
            notes_entry_id is None
            and fs_parent_candidate is not None
            and fs_parent_entry_id is None
        ):
            fs_parent_entry_id = fs_parent_candidate

    affiliate_candidates = [entry for entry in entries if _is_a001_affiliate_leaf(entry)]
    a001_affiliate_entry_id = (
        min(affiliate_candidates, key=_a001_affiliate_priority).entry_id
        if affiliate_candidates
        else None
    )

    return LeafIds(
        cover_entry_id=cover_entry_id,
        opinion_entry_id=opinion_entry_id,
        activity_entry_id=activity_entry_id,
        a001_opinion_entry_id=a001_opinion_entry_id,
        a001_cover_entry_id=a001_cover_entry_id,
        bs_entry_id=bs_entry_id,
        is_entry_id=is_entry_id,
        fs_parent_entry_id=fs_parent_entry_id,
        icfr_entry_id=icfr_entry_id,
        notes_entry_id=notes_entry_id,
        a001_affiliate_entry_id=a001_affiliate_entry_id,
    )
