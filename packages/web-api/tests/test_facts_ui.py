"""Public Facts HTML 탐색 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape

from app.api.deps import get_fact_query_service
from app.main import create_app
from app.schemas.facts import LIST_COLUMNS, FactListItem, FactListResponse


class FakeFactQueryService:
    def __init__(self, response: FactListResponse) -> None:
        self._response = response
        self.last_kwargs: dict[str, object] = {}

    async def list_page(self, **kwargs: object) -> FactListResponse:
        self.last_kwargs = kwargs
        return self._response


def _item(**overrides: object) -> FactListItem:
    values: dict[str, object] = {
        "corp_name": "삼호저축은행",
        "year_end": "(2025.12)",
        "rcept_dt": "2026.06.01",
        "correction_type": "최초공시",
        "rcept_no": "20260601000466",
        "dcm_no": "11411460",
        "source_report_type": "F001",
        "fs_scope": "separate",
        "hours": [{"role": "cpa", "value": 10}],
        "fetch_status": "ok",
        "extracted_at": datetime(2026, 9, 4, tzinfo=timezone.utc),
        "extractor_version": "audit_opinion.v15",
    }
    values.update(overrides)
    return FactListItem.model_validate(values)


def _app(fake: FakeFactQueryService) -> object:
    app = create_app()
    app.dependency_overrides[get_fact_query_service] = lambda: fake
    return app


def test_fact_cell_dumps_json_without_path_join() -> None:
    from app.api.facts.ui import fact_cell

    dumped = fact_cell([{"role": "cpa", "value": 10}])
    assert dumped == '[{"role":"cpa","value":10}]'
    assert " › " not in dumped
    assert fact_cell([]) == "—"
    assert fact_cell({}) == "—"
    assert fact_cell(None) == "—"


async def test_facts_list_shows_join_and_public_headers(client_factory) -> None:
    fake = FakeFactQueryService(
        FactListResponse(items=[_item()], next_cursor="tok")
    )
    async with client_factory(_app(fake)) as client:
        response = await client.get("/facts")
    assert response.status_code == 200
    assert "Facts · 추출 결과" in response.text
    assert 'href="/catalog"' in response.text
    assert "date_resolver" not in response.text
    for header in LIST_COLUMNS:
        assert f"<th>{header}</th>" in response.text
    assert 'href="/catalog/20260601000466"' in response.text
    assert '{"role":"cpa","value":10}' in unescape(response.text)
    assert " › " not in unescape(response.text)
    assert "다음" in response.text
    assert "tok" in response.text


async def test_facts_list_empty_is_not_404(client_factory) -> None:
    fake = FakeFactQueryService(FactListResponse(items=[]))
    async with client_factory(_app(fake)) as client:
        response = await client.get("/facts")
    assert response.status_code == 200
    assert "표시할 추출 결과가 없습니다." in response.text


async def test_facts_a001_two_rows_stay_in_order(client_factory) -> None:
    items = [
        _item(source_report_type="A001", fs_scope="separate", dcm_no="1"),
        _item(source_report_type="A001", fs_scope="consolidated", dcm_no="2"),
    ]
    fake = FakeFactQueryService(FactListResponse(items=items))
    async with client_factory(_app(fake)) as client:
        response = await client.get("/facts")
    text = response.text
    assert text.find("separate") < text.find("consolidated")


async def test_facts_list_passes_query_filters(client_factory) -> None:
    fake = FakeFactQueryService(FactListResponse(items=[]))
    async with client_factory(_app(fake)) as client:
        response = await client.get(
            "/facts", params={"corp_name": "삼호", "limit": 10}
        )
    assert response.status_code == 200
    assert fake.last_kwargs["corp_name"] == "삼호"
    assert fake.last_kwargs["limit"] == 10
