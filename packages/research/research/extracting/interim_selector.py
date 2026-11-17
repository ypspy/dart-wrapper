"""A002·A003 반기·분기 검토·감사 첨부 문서 selector.

기존 `selector.py`는 가져오기만 하고 바꾸지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from research.extracting.selector import SelectorEntry
from research.extracting.text import compact

_REVIEW_NAMES = frozenset(
    {
        "반기검토보고서",
        "반기연결검토보고서",
        "분기검토보고서",
        "분기연결검토보고서",
    }
)
_AUDIT_NAMES = frozenset(
    {
        "반기감사보고서",
        "반기연결감사보고서",
        "분기감사보고서",
        "분기연결감사보고서",
    }
)
# 가운데 점은 ㆍ(U+318D), ·(U+00B7), ・(U+30FB)를 같은 구분자로 본다.
_FOREIGN_RE = re.compile(r"^외국법인등의(반기|분기)(연결)?검토[ㆍ·・]감사보고서$")
_REPORT_LEAF_RE = re.compile(r"^(반기|분기)(연결)?재무제표검토보고서$")
_AUDIT_REPORT_LEAF = "독립된감사인의감사보고서"
_EXCLUDE_MARKERS = ("사유서", "내부회계", "내부감시장치")
_CORRECTION_PREFIX = "[정정]"
_TARGET_REPORT_TYPES = frozenset({"A002", "A003"})


@dataclass(frozen=True)
class InterimLeafIds:
    """검토보고서 문서 안의 leaf 주소."""

    cover_entry_id: str | None
    report_entry_id: str | None
    fs_parent_entry_id: str | None
    notes_entry_id: str | None


def normalize_interim_document_name(document_name: str | None) -> str:
    """공백·탭·줄바꿈을 없애고 앞의 `[정정]`을 반복해서 뺀다."""
    name = compact(document_name)
    while name.startswith(_CORRECTION_PREFIX):
        name = name[len(_CORRECTION_PREFIX) :]
    return name


def interim_doc_kind(
    report_type: str | None,
    source: str,
    document_name: str | None,
) -> str | None:
    """review / audit / foreign_mixed. 대상이 아니면 None."""
    if report_type not in _TARGET_REPORT_TYPES or source != "attachment":
        return None
    name = normalize_interim_document_name(document_name)
    if not name or name == "기타공시첨부서류":
        return None
    if any(marker in name for marker in _EXCLUDE_MARKERS):
        return None
    if name in _REVIEW_NAMES:
        return "review"
    if name in _AUDIT_NAMES:
        return "audit"
    if _FOREIGN_RE.match(name):
        return "foreign_mixed"
    return None


def is_interim_review_document(
    report_type: str | None,
    source: str,
    document_name: str | None,
) -> bool:
    """반기·분기 검토 추출 대상 첨부인지 판별한다."""
    return interim_doc_kind(report_type, source, document_name) is not None


def interim_review_kind(
    report_type: str | None,
    source: str,
    document_name: str | None,
) -> str | None:
    """문서명의 반기·분기로 half / quarter를 정한다. 대상이 아니면 None."""
    if not is_interim_review_document(report_type, source, document_name):
        return None
    name = normalize_interim_document_name(document_name)
    half_at = name.find("반기")
    quarter_at = name.find("분기")
    if half_at >= 0 and (quarter_at < 0 or half_at < quarter_at):
        return "half"
    if quarter_at >= 0:
        return "quarter"
    return None


def interim_fs_scope(
    report_type: str | None,
    source: str,
    document_name: str | None,
) -> str:
    """문서명에 연결이 있으면 consolidated, 대상인데 없으면 separate, 대상이 아니면 unknown."""
    if not is_interim_review_document(report_type, source, document_name):
        return "unknown"
    name = normalize_interim_document_name(document_name)
    if "연결" in name:
        return "consolidated"
    return "separate"


def collect_interim_document_keys(
    rows: Sequence[tuple[str, str | None, str | None, str, str | None]],
) -> list[tuple[str, str]]:
    """후보 행에서 검토 대상 (rcept_no, dcm_no)를 등장 순·중복 없이 모은다."""
    seen: dict[tuple[str, str], None] = {}
    for rcept_no, dcm_no, report_type, source, document_name in rows:
        if not dcm_no:
            continue
        if not is_interim_review_document(report_type, source, document_name):
            continue
        seen.setdefault((rcept_no, dcm_no), None)
    return list(seen.keys())


def _is_fs_parent(section: str) -> bool:
    """(첨부)…재무제표 부모 노드. 주석이 붙은 이름은 제외한다."""
    return "첨부" in section and "재무제표" in section and "주석" not in section


def select_interim_leaves(entries: Sequence[SelectorEntry]) -> InterimLeafIds:
    """한 문서의 entry에서 표지·검토보고서·첨부 제표·주석 leaf를 고른다."""
    doc_kind: str | None = None
    for entry in entries:
        doc_kind = interim_doc_kind(entry.report_type, entry.source, entry.document_name)
        if doc_kind is not None:
            break

    cover_entry_id: str | None = None
    audit_cover_entry_id: str | None = None
    report_entry_id: str | None = None
    fs_parent_entry_id: str | None = None
    notes_entry_id: str | None = None

    for entry in entries:
        section = compact(entry.section_name)
        if not section:
            continue
        if cover_entry_id is None and section == "검토보고서":
            cover_entry_id = entry.entry_id
        if audit_cover_entry_id is None and doc_kind == "audit" and section == "감사보고서":
            audit_cover_entry_id = entry.entry_id
        if report_entry_id is None and _REPORT_LEAF_RE.match(section):
            report_entry_id = entry.entry_id
        if report_entry_id is None and doc_kind == "audit" and section == _AUDIT_REPORT_LEAF:
            report_entry_id = entry.entry_id
        if fs_parent_entry_id is None and _is_fs_parent(section):
            fs_parent_entry_id = entry.entry_id
        if notes_entry_id is None and section == "주석":
            notes_entry_id = entry.entry_id

    if cover_entry_id is None:
        cover_entry_id = audit_cover_entry_id

    return InterimLeafIds(
        cover_entry_id=cover_entry_id,
        report_entry_id=report_entry_id,
        fs_parent_entry_id=fs_parent_entry_id,
        notes_entry_id=notes_entry_id,
    )
