"""v19 추출기와 합성 fixture가 이 변경에서 그대로인지 확인한다."""

from __future__ import annotations

import json
from pathlib import Path

from research.extracting.constants import EXTRACTOR_VERSION
from research.extracting.interim_review import INTERIM_EXTRACTOR_VERSION
from research.extracting.selector import (
    collect_audit_document_keys,
    fs_scope_for,
    is_audit_document,
)

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "interim_review"
_NEW_FILES = (
    "research/extracting/interim_selector.py",
    "research/extracting/interim_review.py",
    "research/models/interim_review_fact.py",
    "research/repositories/interim_fact_repository.py",
    "research/services/interim_review_service.py",
    "scripts/create_interim_review_table.py",
)
_BANNED = ("openai", "gemini", "boto3", "anthropic", "resolve-dates")


def test_v19_selector_and_version_stay() -> None:
    """감사 추출 버전과 A001·F001 selector는 A002 검토 문서를 대상에 넣지 않는다."""
    assert EXTRACTOR_VERSION == "audit_opinion.v19"
    assert INTERIM_EXTRACTOR_VERSION == "interim_review.v1"
    assert is_audit_document("A002", "attachment", "반기검토보고서") is False
    assert is_audit_document("A003", "attachment", "분기연결검토보고서") is False
    assert is_audit_document("A001", "attachment", "감사보고서") is True
    assert is_audit_document("A001", "attachment", "연결감사보고서") is True
    assert fs_scope_for("F001", "감사보고서") == "separate"
    assert fs_scope_for("F002", "연결감사보고서") == "consolidated"
    assert collect_audit_document_keys(
        [
            ("r1", "d1", "A002", "attachment", "반기검토보고서"),
            ("r2", "d2", "A001", "attachment", "연결감사보고서"),
        ]
    ) == [("r2", "d2")]


def test_fixtures_are_synthetic_and_cover_the_matrix() -> None:
    """fixture는 8개 이상이고 가상 회사명만 있다."""
    htmls = sorted(_FIXTURE.glob("*.html"))
    assert len(htmls) >= 8
    manifest = json.loads((_FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    names = {path.name for path in htmls}
    assert {item["file"] for item in manifest["documents"]} == names
    codes = {item["conclusion_code"] for item in manifest["documents"]}
    assert {"unmodified", "qualified", "adverse", "disclaimer", "unknown"} <= codes
    blob = "\n".join(path.read_text(encoding="utf-8") for path in htmls)
    assert "주식회사 테스트" in blob
    assert "가나다회계법인" in blob
    for banned in ("삼성전자", "삼일회계법인", "현대자동차"):
        assert banned not in blob


def test_new_modules_do_not_mention_paid_apis() -> None:
    """새 파일에 유료 API·날짜 해소 경로 문자열이 없다."""
    for relative in _NEW_FILES:
        text = (_ROOT / relative).read_text(encoding="utf-8").casefold()
        for token in _BANNED:
            assert token not in text, relative
