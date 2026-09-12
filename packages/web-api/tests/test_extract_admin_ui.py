"""감사 추출 Admin HTML 모니터 테스트."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI

from app.api.deps import (
    get_catalog_service,
    get_completeness_service,
    get_corp_industry_service,
    get_extraction_service,
    get_slice_query_service,
)
from app.errors import CatalogConflict
from app.extracting.constants import EXTRACTOR_VERSION
from app.extracting.field_bundles import BUNDLE_KEYS, BUNDLE_LABELS
from app.main import create_app
from app.schemas.catalog import JobLogItem
from app.schemas.extract import (
    CompletenessItem,
    CompletenessResponse,
    ExtractJobStatusResponse,
    FieldBundleCountsResponse,
    FieldBundleFailItem,
    FieldBundleFailListResponse,
    FieldBundleRow,
)
from tests.test_admin_ui import JOB_STATUS, FakeCatalogService, FakeSliceQueryService
from tests.test_corps_admin_ui import FakeCorpIndustryService

ClientFactory = Callable[[FastAPI], httpx.AsyncClient]


class FakeCompletenessService:
    """유형별 고정 집계를 돌려준다."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def summarize(self, **kwargs) -> CompletenessResponse:
        """테스트용 완전성 숫자."""
        self.calls.append(kwargs)
        status = kwargs.get("status")
        items = []
        if status == "unextracted":
            items = [CompletenessItem(rcept_no="20200331000001", dcm_no="11111")]
        return CompletenessResponse(
            target=10,
            ok=7,
            fetch_failed=1,
            blocked=0,
            section_missing=0,
            unextracted=2,
            stale_version=4,
            ambiguous_dates=1,
            field_partial=3,
            items=items,
        )

    async def summarize_many(
        self,
        *,
        start_date: str,
        end_date: str,
        report_types: list[str],
    ) -> dict[str, CompletenessResponse]:
        """카드용 세 유형 집계. 유형마다 summarize를 호출해 호출 기록을 남긴다."""
        return {
            report_type: await self.summarize(
                start_date=start_date,
                end_date=end_date,
                report_type=report_type,
            )
            for report_type in report_types
        }

    async def summarize_field_bundles(self, **kwargs) -> FieldBundleCountsResponse:
        """테스트용 12묶음 집계."""
        self.bundle_calls = getattr(self, "bundle_calls", [])
        self.bundle_calls.append(kwargs)
        rows = []
        for key in BUNDLE_KEYS:
            rows.append(
                FieldBundleRow(
                    bundle=key,
                    label=BUNDLE_LABELS[key],
                    ok=1,
                    not_applicable=0 if key != "subsidiary" else 2,
                    expected_missing=0 if key != "communications" else 3,
                    fail=4,
                )
            )
        return FieldBundleCountsResponse(
            start_date=str(kwargs.get("start_date", "")),
            end_date=str(kwargs.get("end_date", "")),
            extractor_version=EXTRACTOR_VERSION,
            eligible=10,
            bundles=rows,
        )

    async def list_field_bundle_fail_items(self, **kwargs) -> FieldBundleFailListResponse:
        """테스트용 묶음 실패 한 건."""
        return FieldBundleFailListResponse(
            items=[
                FieldBundleFailItem(
                    report_type="F001",
                    rcept_no="20200331000001",
                    dcm_no="11111",
                    fs_scope="separate",
                    bundle=str(kwargs.get("bundle", "opinion")),
                    status="not_found",
                    extractor_version=EXTRACTOR_VERSION,
                    viewer_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=1",
                )
            ]
        )


class FakeExtractionService:
    """최근 추출 잡만 돌려준다."""

    def __init__(self, job: ExtractJobStatusResponse | None = None) -> None:
        self.job = job
        self.started: list[tuple[str, str, list[str], str]] = []
        self.executed: list[str] = []
        self.stopped: list[str] = []
        self.finished: list[str] = []

    async def get_latest_status(self) -> ExtractJobStatusResponse | None:
        """HTML이 쓰는 최신 잡."""
        return self.job

    async def start(
        self,
        start_date: str,
        end_date: str,
        report_types: list[str],
        mode: str,
    ) -> str:
        """폼 시작을 기록한다."""
        self.started.append((start_date, end_date, report_types, mode))
        return "extract-job-1"

    async def run_job(self, job_id: str) -> None:
        """백그라운드 실행 요청을 기록한다."""
        self.executed.append(job_id)

    async def request_soft_stop(self, job_id: str) -> None:
        """소프트 스톱을 기록한다."""
        self.stopped.append(job_id)

    async def force_finish(self, job_id: str) -> None:
        """강제 종료를 기록한다."""
        self.finished.append(job_id)


class ConflictExtractionService(FakeExtractionService):
    """잠금 충돌을 흉내 낸다."""

    async def start(
        self,
        start_date: str,
        end_date: str,
        report_types: list[str],
        mode: str,
    ) -> str:
        """폼 시작을 기록한 뒤 잠금 충돌을 일으킨다."""
        self.started.append((start_date, end_date, report_types, mode))
        raise CatalogConflict("감사 추출 작업이 이미 진행 중입니다.")


RUNNING_EXTRACT = ExtractJobStatusResponse(
    job_id="abcdef12deadbeef",
    status="running",
    mode="extract",
    params={
        "start_date": "20160101",
        "end_date": "20260909",
        "report_types": ["F001", "F002"],
        "processed_count": 4,
        "target_count": 10,
    },
    started_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
    logs=[
        JobLogItem(
            level="info",
            message="20200331000001/11111 추출 완료(ok).",
            created_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
        )
    ],
)


def _app(
    extraction: FakeExtractionService | None = None,
    catalog: FakeCatalogService | None = None,
    completeness: FakeCompletenessService | None = None,
) -> FastAPI:
    """추출 Admin 화면용 의존성을 대역으로 바꾼다."""
    app = create_app()
    completeness_service = completeness or FakeCompletenessService()
    app.dependency_overrides[get_slice_query_service] = lambda: FakeSliceQueryService()
    app.dependency_overrides[get_catalog_service] = lambda: catalog or FakeCatalogService(
        job=None
    )
    app.dependency_overrides[get_corp_industry_service] = lambda: FakeCorpIndustryService()
    app.dependency_overrides[get_extraction_service] = lambda: extraction or FakeExtractionService()
    app.dependency_overrides[get_completeness_service] = lambda: completeness_service
    return app


async def test_extract_page_redirects_without_token(client_factory: ClientFactory) -> None:
    """토큰 없이 추출 화면은 토큰 페이지로 보낸다."""
    async with client_factory(_app()) as client:
        response = await client.get("/admin/extract")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/admin/token")


async def test_extract_page_defaults_research_window(
    client_factory: ClientFactory,
) -> None:
    """기본 기간은 잠긴 연구 창이다."""
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/extract")
    assert response.status_code == 200
    assert "20160101" in response.text
    assert "20260909" in response.text
    assert "추출 · 완전성" in response.text
    assert 'href="/admin/extract"' in response.text
    assert ">추출</a>" in response.text or "추출</a>" in response.text


async def test_extract_job_card_shows_progress(
    client_factory: ClientFactory,
) -> None:
    """잡 카드는 처리/대상과 최근 로그를 보여 준다."""
    extraction = FakeExtractionService(RUNNING_EXTRACT)
    async with client_factory(_app(extraction)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/extract/job-status")
    assert response.status_code == 200
    assert "처리 4 / 대상 10" in response.text or "4 / 10" in response.text
    assert "추출 완료(ok)" in response.text


async def test_extract_page_does_not_block_on_completeness(
    client_factory: ClientFactory,
) -> None:
    """첫 화면은 집계를 기다리지 않고 카드만 HTMX로 불러온다."""
    completeness = FakeCompletenessService()
    async with client_factory(_app(completeness=completeness)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/extract")
    body = response.text
    assert response.status_code == 200
    assert completeness.calls == []
    assert "대상 10" not in body
    assert "미추출 2" not in body
    assert "완전성 카드를 불러오는 중" in body
    assert "every 60s" in body
    assert "hx-trigger=" in body and "load" in body
    assert 'hx-get="/admin/extract/completeness-cards' in body
    assert "status=ok" not in body


async def test_completeness_cards_query_uses_requested_dates(
    client_factory: ClientFactory,
) -> None:
    """카드 partial은 쿼리 기간으로 세 유형을 집계한다."""
    completeness = FakeCompletenessService()
    async with client_factory(_app(completeness=completeness)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get(
            "/admin/extract/completeness-cards?start_date=20200101&end_date=20201231"
        )
    assert response.status_code == 200
    types = [call["report_type"] for call in completeness.calls]
    assert types == ["F001", "F002", "A001"]
    assert all(call["start_date"] == "20200101" for call in completeness.calls)
    assert "대상 10" in response.text
    assert "미추출 2" in response.text
    assert "구버전 4" in response.text
    assert "재추출 필요" in response.text
    assert "ok 중 구멍" in response.text or "부분실패 3" in response.text


async def test_completeness_cards_include_twelve_bundle_rows(
    client_factory: ClientFactory,
) -> None:
    """카드 partial에 12묶음 표와 실패 TSV 링크가 있다."""
    completeness = FakeCompletenessService()
    async with client_factory(_app(completeness=completeness)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get(
            "/admin/extract/completeness-cards?start_date=20200101&end_date=20201231"
        )
    assert response.status_code == 200
    assert "감사인" in response.text
    assert "종속기업" in response.text
    assert "제도상없음" in response.text
    assert "field-bundles/export" in response.text
    assert completeness.bundle_calls[0]["start_date"] == "20200101"


async def test_field_bundle_items_partial_lists_fail_row(
    client_factory: ClientFactory,
) -> None:
    """실패 목록 partial에 접수번호와 원문 링크가 있다."""
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get(
            "/admin/extract/field-bundle-items"
            "?start_date=20200101&end_date=20201231&bundle=opinion"
        )
    assert response.status_code == 200
    assert "20200331000001" in response.text
    assert "viewer.do" in response.text


async def test_completeness_items_lists_documents(
    client_factory: ClientFactory,
) -> None:
    """상태 숫자를 누르면 문서 식별자가 나온다."""
    async with client_factory(_app()) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get(
            "/admin/extract/completeness-items"
            "?start_date=20160101&end_date=20260909"
            "&report_type=F001&status=unextracted"
        )
    assert response.status_code == 200
    assert "20200331000001" in response.text
    assert "11111" in response.text


async def test_extract_page_invalid_dates_keep_form_and_notice(
    client_factory: ClientFactory,
) -> None:
    """잘못된 YYYYMMDD는 notice로 남기고 폼 날짜를 연구 창으로 되돌리지 않는다."""
    completeness = FakeCompletenessService()
    async with client_factory(_app(completeness=completeness)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/extract?start_date=bad&end_date=20260909")
    assert response.status_code == 200
    assert 'value="bad"' in response.text
    assert "20160101" not in response.text
    assert "YYYYMMDD" in response.text
    assert completeness.calls == []


async def test_start_extract_form_runs_job(
    client_factory: ClientFactory,
) -> None:
    """폼 POST는 서비스를 호출하고 추출 화면으로 돌아온다."""
    extraction = FakeExtractionService()
    async with client_factory(_app(extraction)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post(
            "/admin/extract/start",
            data={
                "start_date": "20160101",
                "end_date": "20260909",
                "report_types": ["F001", "F002"],
                "mode": "resume",
            },
        )
    assert response.status_code == 303
    assert response.headers["location"].endswith("/admin/extract")
    assert extraction.started == [
        ("20160101", "20260909", ["F001", "F002"], "resume")
    ]
    assert extraction.executed == ["extract-job-1"]


async def test_start_extract_conflict_sets_notice(
    client_factory: ClientFactory,
) -> None:
    """잠금이면 JSON 대신 notice와 함께 추출 화면으로 돌아온다."""
    extraction = ConflictExtractionService()
    async with client_factory(_app(extraction)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post(
            "/admin/extract/start",
            data={
                "start_date": "20160101",
                "end_date": "20260909",
                "report_types": ["F001"],
                "mode": "extract",
            },
            follow_redirects=True,
        )
    assert "진행 중" in response.text
    assert extraction.executed == []


async def test_extract_form_disabled_when_catalog_busy(
    client_factory: ClientFactory,
) -> None:
    """수집이 돌면 추출 시작 버튼이 비활성이다."""
    async with client_factory(_app(catalog=FakeCatalogService(job=JOB_STATUS))) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/extract")
    assert "수집 중이니 추출을 시작할 수 없습니다" in response.text
    assert "disabled" in response.text


async def test_extract_soft_stop_and_force_finish(
    client_factory: ClientFactory,
) -> None:
    """중단·강제 종료 폼이 추출 화면으로 돌아온다."""
    extraction = FakeExtractionService(RUNNING_EXTRACT)
    async with client_factory(_app(extraction)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        card = await client.get("/admin/extract/job-status")
        assert "/admin/extract/jobs/abcdef12deadbeef/stop" in card.text
        assert "/admin/extract/jobs/abcdef12deadbeef/finish" in card.text
        assert "/soft-stop" not in card.text
        assert "/force-finish" not in card.text
        stop = await client.post("/admin/extract/jobs/abcdef12deadbeef/stop")
        finish = await client.post("/admin/extract/jobs/abcdef12deadbeef/finish")
    assert stop.status_code == 303
    assert finish.status_code == 303
    assert extraction.stopped == ["abcdef12deadbeef"]
    assert extraction.finished == ["abcdef12deadbeef"]


async def test_start_extract_requires_report_types(
    client_factory: ClientFactory,
) -> None:
    """유형을 하나도 고르지 않으면 notice로 돌아온다."""
    extraction = FakeExtractionService()
    async with client_factory(_app(extraction)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.post(
            "/admin/extract/start",
            data={
                "start_date": "20160101",
                "end_date": "20260909",
                "mode": "extract",
            },
            follow_redirects=True,
        )
    assert "유형을 하나 이상 선택해 주세요." in response.text
    assert extraction.started == []
    assert extraction.executed == []


async def test_extract_page_shows_extract_busy_banner(
    client_factory: ClientFactory,
) -> None:
    """추출이 돌면 상단에 진행 배너가 보인다."""
    extraction = FakeExtractionService(RUNNING_EXTRACT)
    async with client_factory(_app(extraction)) as client:
        client.cookies.set("admin_token", "dev-admin-token")
        response = await client.get("/admin/extract")
    assert "추출 작업이 진행 중입니다." in response.text
    assert "disabled" in response.text
