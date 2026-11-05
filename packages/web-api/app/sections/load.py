"""F004 감리결과 섹션 본문을 DART에서 받아 별도 SQLite에 넣는다.

카탈로그 DB는 읽기만 한다. DART 요청은 한 번에 하나이고, 미국 중부시간
00:00–04:59에는 야간 수집과 겹치지 않도록 멈추다.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from app.adapters.dart_http import DartHttpClient
from app.errors import SourceFetchError
from app.sections.store import (
    SectionStore,
    list_disclosures,
    open_catalog_readonly,
    open_sections_db,
)
from app.sections.text import body_hash, section_plain_text
from app.sections.toc import (
    canonical_section_code,
    disclosure_main_url,
    display_title,
    find_section,
    parse_toc,
)

_CHICAGO = ZoneInfo("America/Chicago")
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_BLOCK_MARKERS = ("자동입력 방지", "captcha", "비정상적인 접근", "요청이 차단")
QUIET_WINDOW_MESSAGE = (
    "지금은 미국 중부시간(시카고) 00:00–04:59라서 시작하지 않습니다. "
    "이 시간에는 야간 수집이 DART를 사용합니다. "
    "그래도 실행하려면 --ignore-window 를 붙여 주세요."
)
_STOP_WINDOW_MESSAGE = (
    "미국 중부시간(시카고) 00:00–04:59에 들어가 남은 공시는 받지 않았습니다. "
    "저장해 둔 건은 남습니다. 이 시간이 지난 뒤 같은 명령을 다시 실행하면 이어 받습니다."
)
DART_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://dart.fss.or.kr/",
}


class CollectorWindowError(RuntimeError):
    """조용한 시간이라 이번 실행을 시작하지 않을 때."""


class _QuietWindowStop(Exception):
    """실행 도중 조용한 시간에 들어가 루프를 멈출 때."""


@dataclass
class LoadSummary:
    """한 번 실행한 결과 건수."""

    attempted: int = 0
    loaded: int = 0
    not_found: int = 0
    failed: int = 0
    skipped: int = 0
    stopped_for_window: bool = False

    def line(self) -> str:
        """마지막에 찍는 한 줄 요약."""
        return (
            f"attempted={self.attempted} loaded={self.loaded} "
            f"not_found={self.not_found} failed={self.failed}"
        )


def in_collector_quiet_window(now: datetime) -> bool:
    """시카고 기준 00:00–04:59이면 참. 05:00부터는 거짓."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(_CHICAGO).hour < 5


def _utcnow() -> datetime:
    """창 판정에 쓰는 현재 시각."""
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """저장용 UTC 시각. 예: 2026-11-05T18:00:00Z."""
    current = datetime.now(timezone.utc).replace(microsecond=0)
    return current.isoformat().replace("+00:00", "Z")


def make_dart_client(client: httpx.AsyncClient, interval_seconds: float) -> DartHttpClient:
    """요청 사이 최소 간격을 둔 DART 클라이언트를 만든다."""
    return DartHttpClient(
        client,
        timeout_seconds=30.0,
        max_retries=2,
        retry_backoff_seconds=0.5,
        min_interval_seconds=interval_seconds,
    )


def build_parser() -> argparse.ArgumentParser:
    """섹션 본문 적재 인자."""
    parser = argparse.ArgumentParser(
        description=(
            "공시 상세 목차에서 감리결과 절을 찾아 본문을 별도 SQLite에 넣습니다. "
            "카탈로그 DB는 읽기만 합니다."
        )
    )
    parser.add_argument(
        "--catalog-db",
        type=Path,
        default=_PACKAGE_ROOT / "dart_catalog.db",
        help="읽기 전용으로 열 카탈로그 DB. 기본은 packages/web-api/dart_catalog.db.",
    )
    parser.add_argument(
        "--sections-db",
        type=Path,
        default=_PACKAGE_ROOT / "dart_sections.db",
        help="본문을 쓸 DB. 기본은 packages/web-api/dart_sections.db.",
    )
    parser.add_argument(
        "--report-type",
        default="F004",
        help="disclosures.report_type. 기본 F004(회계법인사업보고서).",
    )
    parser.add_argument(
        "--section-code",
        default="VI",
        help="찾을 절 번호. VI, Ⅵ, 6은 모두 VI로 저장합니다. 기본 VI.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="DART 요청 사이 최소 간격(초). 기본 1.0.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="이번에 새로 시도할 최대 건수. 0이면 제한 없음.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="이미 받은 본문과 섹션 없음도 다시 받습니다.",
    )
    parser.add_argument(
        "--ignore-window",
        action="store_true",
        help="시카고 00:00–04:59에도 실행합니다. 야간 수집과 겹칠 수 있습니다.",
    )
    return parser


def _block_reason(html: str) -> str | None:
    """차단·빈 응답이면 이유를, 아니면 None."""
    lowered = html.lower()
    for marker in _BLOCK_MARKERS:
        if marker.lower() in lowered:
            return f"DART 응답이 차단으로 보입니다({marker}). 잠시 뒤 다시 시도해 주세요."
    if len(html) < 300:
        return "DART 응답이 너무 짧아 본문으로 보지 않았습니다."
    return None


async def load_section_bodies(
    *,
    catalog_db: Path,
    sections_db: Path,
    fetch_html: Callable[[str], Awaitable[str]],
    report_type: str = "F004",
    section_code: str = "VI",
    limit: int | None = None,
    refresh: bool = False,
    ignore_window: bool = False,
    now: Callable[[], datetime] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> LoadSummary:
    """카탈로그의 공시마다 감리 절 본문을 받아 넣는다.

    성공한 접수와 섹션 없음은 기본적으로 건너뛴다. 받아 오기 실패는 다음 실행에서
    다시 시도한다. `--refresh`면 모두 다시 받는다.

    :raises CollectorWindowError: 시작 시각이 조용한 시간일 때
    :raises FileNotFoundError: 카탈로그 파일이 없을 때
    :raises ValueError: 섹션 DB와 카탈로그 경로가 같을 때
    :raises RuntimeError: disclosures를 읽지 못할 때
    """
    clock = now or _utcnow
    progress = on_progress or (lambda message: print(message, flush=True))
    if catalog_db.resolve() == sections_db.resolve():
        raise ValueError(
            "섹션 DB는 카탈로그와 다른 파일이어야 합니다. " "카탈로그에는 쓰지 않습니다."
        )
    if not ignore_window and in_collector_quiet_window(clock()):
        raise CollectorWindowError(QUIET_WINDOW_MESSAGE)

    code = canonical_section_code(section_code)
    if not code:
        raise ValueError("섹션 코드(--section-code)가 비어 있습니다.")
    summary = LoadSummary()
    catalog = open_catalog_readonly(catalog_db)
    try:
        rows = list_disclosures(catalog, report_type)
        sections_conn = open_sections_db(sections_db)
        store = SectionStore(sections_conn)
        try:
            await _load_rows(
                rows=rows,
                store=store,
                fetch_html=fetch_html,
                section_code=code,
                limit=limit,
                refresh=refresh,
                ignore_window=ignore_window,
                clock=clock,
                progress=progress,
                summary=summary,
            )
        finally:
            sections_conn.close()
    finally:
        catalog.close()
    return summary


async def _load_rows(
    *,
    rows: list[tuple[str, str | None]],
    store: SectionStore,
    fetch_html: Callable[[str], Awaitable[str]],
    section_code: str,
    limit: int | None,
    refresh: bool,
    ignore_window: bool,
    clock: Callable[[], datetime],
    progress: Callable[[str], None],
    summary: LoadSummary,
) -> None:
    """접수 목록을 직렬로 처리한다."""

    async def fetch(url: str) -> str:
        if not ignore_window and in_collector_quiet_window(clock()):
            raise _QuietWindowStop()
        html = await fetch_html(url)
        reason = _block_reason(html)
        if reason:
            raise SourceFetchError(reason)
        return html

    capped = limit if limit is not None and limit > 0 else None
    for rcept_no, disclosure_url in rows:
        if capped is not None and summary.attempted >= capped:
            break
        if not ignore_window and in_collector_quiet_window(clock()):
            summary.stopped_for_window = True
            progress(_STOP_WINDOW_MESSAGE)
            break
        if not refresh and store.has_body(rcept_no, section_code):
            summary.skipped += 1
            continue
        if not refresh and store.failure_kind(rcept_no, section_code) == "not_found":
            summary.skipped += 1
            continue
        try:
            await _load_one(
                rcept_no=rcept_no,
                disclosure_url=disclosure_url,
                section_code=section_code,
                store=store,
                fetch=fetch,
                progress=progress,
                summary=summary,
            )
        except _QuietWindowStop:
            summary.stopped_for_window = True
            progress(_STOP_WINDOW_MESSAGE)
            break


async def _load_one(
    *,
    rcept_no: str,
    disclosure_url: str | None,
    section_code: str,
    store: SectionStore,
    fetch: Callable[[str], Awaitable[str]],
    progress: Callable[[str], None],
    summary: LoadSummary,
) -> None:
    """공시 하나의 목차를 열고 절 본문을 저장한다."""
    main_url = disclosure_main_url(rcept_no, disclosure_url)
    try:
        main_html = await fetch(main_url)
        node = _locate(main_html, section_code)
        if node is None:
            reason = _missing_reason(main_html, section_code)
            kind = "fetch_error" if reason[0] == "fetch_error" else "not_found"
            store.upsert_failure(
                rcept_no=rcept_no,
                section_code=section_code,
                kind=kind,
                reason=reason[1],
                fetched_at=utc_now_iso(),
            )
            summary.attempted += 1
            if kind == "not_found":
                summary.not_found += 1
                progress(f"{rcept_no} 섹션 없음")
            else:
                summary.failed += 1
                progress(f"{rcept_no} 실패: {reason[1]}")
            return
        body_html = await fetch(node.viewer_url)
        text = section_plain_text(body_html)
        title = display_title(node.title)
        store.upsert_body(
            rcept_no=rcept_no,
            section_code=section_code,
            section_title=title,
            body_text=text,
            body_hash=body_hash(text),
            source_url=node.viewer_url,
            fetched_at=utc_now_iso(),
        )
        summary.attempted += 1
        summary.loaded += 1
        progress(f"{rcept_no} 적재 ({len(text)}자) {title}")
    except _QuietWindowStop:
        raise
    except SourceFetchError as exc:
        store.upsert_failure(
            rcept_no=rcept_no,
            section_code=section_code,
            kind="fetch_error",
            reason=str(exc),
            fetched_at=utc_now_iso(),
        )
        summary.attempted += 1
        summary.failed += 1
        progress(f"{rcept_no} 실패: {exc}")
    except Exception as exc:
        store.upsert_failure(
            rcept_no=rcept_no,
            section_code=section_code,
            kind="fetch_error",
            reason=f"본문을 처리하지 못했습니다: {exc}",
            fetched_at=utc_now_iso(),
        )
        summary.attempted += 1
        summary.failed += 1
        progress(f"{rcept_no} 실패: {exc}")


def _locate(main_html: str, section_code: str):
    """목차에서 절을 찾는다. 목차 자체가 이상하면 None."""
    if _block_reason(main_html):
        return None
    return find_section(parse_toc(main_html), section_code)


def _missing_reason(main_html: str, section_code: str) -> tuple[str, str]:
    """섹션을 못 찾은 이유를 (kind, 설명)으로 나눈다."""
    blocked = _block_reason(main_html)
    if blocked:
        return ("fetch_error", blocked)
    if "treeData" in main_html and not parse_toc(main_html):
        return (
            "fetch_error",
            "상세페이지에 목차 스크립트는 있으나 읽지 못했습니다. 다음 실행에서 다시 시도합니다.",
        )
    if "treeData" not in main_html and len(main_html) < 8000:
        return (
            "fetch_error",
            "상세페이지에서 목차를 찾지 못했습니다. 응답이 짧아 다음 실행에서 다시 시도합니다.",
        )
    return (
        "not_found",
        f"목차에서 감리 섹션({section_code})을 찾지 못했습니다.",
    )


async def _run(args: argparse.Namespace) -> LoadSummary:
    """CLI 인자로 클라이언트를 만들고 적재를 실행한다."""
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(
        headers=DART_HEADERS,
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        dart = make_dart_client(client, args.interval)
        return await load_section_bodies(
            catalog_db=args.catalog_db,
            sections_db=args.sections_db,
            fetch_html=dart.fetch_html,
            report_type=args.report_type,
            section_code=args.section_code,
            limit=args.limit,
            refresh=args.refresh,
            ignore_window=args.ignore_window,
        )


def main(argv: list[str] | None = None) -> int:
    """인자를 해석해 적재하고 프로세스 종료 코드를 반환한다."""
    args = build_parser().parse_args(argv)
    if args.interval < 0:
        print("간격(--interval)은 0 이상이어야 합니다.")
        return 1
    try:
        summary = asyncio.run(_run(args))
    except CollectorWindowError as exc:
        print(exc)
        print(LoadSummary().line())
        return 2
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(exc)
        return 1
    print(summary.line())
    return 0
