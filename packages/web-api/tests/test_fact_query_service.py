"""FactQueryService cursor·목록 테스트."""

import pytest

from app.errors import BadRequest
from app.services.fact_query_service import decode_fact_cursor, encode_fact_cursor


def test_fact_cursor_roundtrip() -> None:
    token = encode_fact_cursor("2026.06.01", "20260601000466", "11411460")
    assert decode_fact_cursor(token) == (
        "2026.06.01",
        "20260601000466",
        "11411460",
    )


def test_decode_fact_cursor_rejects_garbage() -> None:
    with pytest.raises(BadRequest, match="커서 값이 올바르지 않습니다"):
        decode_fact_cursor("!!!")
