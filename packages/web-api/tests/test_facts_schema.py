"""FactListItem 조인 칸·공개 컬럼 테스트."""

from datetime import datetime, timezone

from app.extracting.constants import EXTRACTOR_VERSION
from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
from app.schemas.facts import (
    DATE_RESOLVER_COLUMNS,
    FACT_PUBLIC_COLUMNS,
    JOIN_COLUMNS,
    LIST_COLUMNS,
    fact_list_item_from,
)


def test_public_columns_follow_model_and_drop_resolver() -> None:
    names = [column.name for column in AuditReportFact.__table__.columns]
    assert DATE_RESOLVER_COLUMNS == (
        "date_resolver_model",
        "date_resolver_prompt_version",
        "date_resolver_raw_response",
    )
    assert FACT_PUBLIC_COLUMNS == tuple(
        name for name in names if name not in DATE_RESOLVER_COLUMNS
    )
    assert JOIN_COLUMNS == ("corp_name", "year_end", "rcept_dt", "correction_type")
    assert LIST_COLUMNS == JOIN_COLUMNS + FACT_PUBLIC_COLUMNS


def test_fact_list_item_from_joins_catalog_and_hides_resolver() -> None:
    fact = AuditReportFact(
        rcept_no="20200331000001",
        dcm_no="11111",
        source_report_type="F001",
        fs_scope="separate",
        fetch_status="ok",
        extractor_version=EXTRACTOR_VERSION,
        date_resolver_model="gpt-4o-mini",
        extracted_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
    )
    disc = Disclosure(
        rcept_no="20200331000001",
        corp_name="삼호저축은행",
        year_end="(2025.12)",
        rcept_dt="2026.06.01",
        correction_type="최초공시",
        entry_count=1,
    )
    item = fact_list_item_from(fact, disc)
    dumped = item.model_dump()
    keys = list(dumped)
    assert keys[:4] == ["corp_name", "year_end", "rcept_dt", "correction_type"]
    assert dumped["corp_name"] == "삼호저축은행"
    assert dumped["year_end"] == "(2025.12)"
    assert dumped["rcept_dt"] == "2026.06.01"
    assert dumped["correction_type"] == "최초공시"
    assert dumped["rcept_no"] == "20200331000001"
    assert dumped["dcm_no"] == "11111"
    assert "date_resolver_model" not in dumped
