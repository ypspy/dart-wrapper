"""primary 섹션 allowlist 매칭 테스트."""

from __future__ import annotations

from app.catalog.primary_sections import is_primary_section


def test_f001_matches_financial_statements() -> None:
    assert is_primary_section("F001", "재무상태표") is True
    assert is_primary_section("F001", "  주석  ") is True
    assert is_primary_section("F001", "감사인의 감사보고서") is False


def test_unknown_report_type_is_never_primary() -> None:
    assert is_primary_section("A001", "재무상태표") is False
    assert is_primary_section(None, "재무상태표") is False


def test_falls_back_to_document_name() -> None:
    assert is_primary_section("F001", None, "손익계산서") is True
