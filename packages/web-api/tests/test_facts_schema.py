"""FactListItem 조인 칸·공개 컬럼 테스트."""

import json
from datetime import datetime, timezone

from app.extracting.constants import EXTRACTOR_VERSION
from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
from app.schemas.facts import (
    DATE_RESOLVER_COLUMNS,
    FACT_PUBLIC_COLUMNS,
    JOIN_COLUMNS,
    LIST_COLUMNS,
    FactListItem,
    FactListResponse,
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


def _sample_fact_list_item():
    """조인·직렬화 테스트용 FactListItem을 만든다."""
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
    return fact_list_item_from(fact, disc)


def test_nested_and_json_serialization_keep_join_columns_first() -> None:
    """FactListResponse dump·dump_json 경로에서도 조인 칸이 앞에 온다."""
    item = _sample_fact_list_item()
    response = FactListResponse(items=[item], next_cursor=None)

    nested_keys = list(response.model_dump()["items"][0])
    assert nested_keys[:4] == ["corp_name", "year_end", "rcept_dt", "correction_type"]

    parsed = json.loads(response.model_dump_json())
    json_keys = list(parsed["items"][0])
    assert json_keys[:4] == ["corp_name", "year_end", "rcept_dt", "correction_type"]


def test_model_dump_exclude_none_does_not_keyerror() -> None:
    """exclude_none=True일 때 누락된 None 칸 때문에 KeyError가 나지 않는다."""
    item = _sample_fact_list_item()
    dumped = item.model_dump(exclude_none=True)
    assert dumped["corp_name"] == "삼호저축은행"
    assert dumped["rcept_no"] == "20200331000001"
    assert "cover_entry_id" not in dumped
    assert list(dumped)[:4] == ["corp_name", "year_end", "rcept_dt", "correction_type"]


def test_fact_list_item_json_schema_exposes_fields() -> None:
    """직렬화 JSON Schema(OpenAPI)에 필드가 남아 있다."""
    properties = FactListItem.model_json_schema(mode="serialization").get("properties") or {}
    assert "corp_name" in properties
    assert "rcept_no" in properties
    assert "source_report_type" in properties
    assert list(properties)[:4] == ["corp_name", "year_end", "rcept_dt", "correction_type"]
