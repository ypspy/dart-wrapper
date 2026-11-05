"""감리결과 섹션 적재. 저장된 HTML만 쓰고 네트워크는 호출하지 않는다."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.adapters.dart_http import DartHttpClient
from app.errors import SourceFetchError
from app.sections.load import (
    CollectorWindowError,
    LoadSummary,
    _chicago_from_rule,
    build_parser,
    in_collector_quiet_window,
    load_section_bodies,
    main,
)
from app.sections.store import open_catalog_readonly, open_sections_db
from app.sections.text import body_hash, normalize_body, section_plain_text
from app.sections.toc import (
    canonical_section_code,
    disclosure_main_url,
    find_section,
    parse_toc,
    title_matches,
)

FIXTURES = Path(__file__).parent / "fixtures"
OUTSIDE = datetime(2026, 11, 5, 18, 0, tzinfo=timezone.utc)
INSIDE = datetime(2026, 11, 5, 6, 30, tzinfo=timezone.utc)
VIEWER_URL = (
    "https://dart.fss.or.kr/report/viewer.do?rcpNo=20250701000044"
    "&dcmNo=10706914&eleId=69&offset=219409&length=8972&dtd=dart4.xsd"
)


def _write_catalog(path: Path, rows: list[tuple[str, str, str | None]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute("""
        CREATE TABLE disclosures (
            rcept_no TEXT PRIMARY KEY,
            report_type TEXT,
            disclosure_url TEXT
        )
        """)
    connection.executemany(
        "INSERT INTO disclosures (rcept_no, report_type, disclosure_url) VALUES (?, ?, ?)",
        rows,
    )
    connection.commit()
    connection.close()


def _schema(path: Path) -> list[tuple[str, str, str | None]]:
    connection = sqlite3.connect(path)
    rows = connection.execute(
        "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
    ).fetchall()
    connection.close()
    return rows


def _bodies(path: Path) -> list[sqlite3.Row]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    rows = connection.execute("SELECT * FROM section_bodies ORDER BY rcept_no").fetchall()
    connection.close()
    return rows


def _failures(path: Path) -> list[sqlite3.Row]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    rows = connection.execute("SELECT * FROM section_failures ORDER BY rcept_no").fetchall()
    connection.close()
    return rows


def _toc() -> str:
    return (FIXTURES / "f004_vi_toc.html").read_text(encoding="utf-8")


def _viewer() -> str:
    return (FIXTURES / "f004_vi_viewer.html").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("title", "depth", "expected"),
    [
        ("Ⅵ. 감리결과", 1, True),
        ("Ⅵ. 최근 3개 사업연도의 감리결과", 1, True),
        ("VI. 감리결과", 1, True),
        ("Ⅵ.감리결과", 1, True),
        ("Ⅵ . 감 리 결 과", 1, True),
        ("ＶＩ．감리결과", 1, True),
        ("제6장 감리결과", 1, True),
        ("6. 감리결과", 1, True),
        ("감리결과", 1, True),
        ("1. 감사보고서 감리결과", 2, False),
        ("2. 감사인 감리결과", 2, False),
        ("6. 모니터링 감리", 2, False),
        ("Ⅴ. 감리결과", 1, False),
        ("VIII. 감리결과", 1, False),
        ("Ⅶ. 최근 3개 사업연도의 소송 현황", 1, False),
        ("I. 회계법인의 개황", 1, False),
    ],
)
def test_title_matches_roman_variants(title: str, depth: int, expected: bool) -> None:
    assert title_matches(title, "VI", depth=depth) is expected


def test_disclosure_main_url_fills_missing_or_relative() -> None:
    assert disclosure_main_url("1", None) == ("https://dart.fss.or.kr/dsaf001/main.do?rcpNo=1")
    assert disclosure_main_url("1", "/dsaf001/main.do?rcpNo=1") == (
        "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=1"
    )


def test_section_code_collapses_to_ascii_roman() -> None:
    assert canonical_section_code("Ⅵ") == "VI"
    assert canonical_section_code("6") == "VI"
    assert canonical_section_code("vi") == "VI"


def test_saved_toc_selects_parent_section_not_child() -> None:
    node = find_section(parse_toc(_toc()), "VI")

    assert node is not None
    assert node.ele_id == "69"
    assert node.title == "Ⅵ. 최근 3개 사업연도의 감리결과"
    assert node.viewer_url == VIEWER_URL
    assert [child.ele_id for child in node.children] == ["70", "71"]


def test_letter_spaced_title_beats_subsection() -> None:
    html = """
    <script>
    var treeData = [];
    var node1 = {};
    node1['text'] = "Ⅵ . 감 리 결 과";
    node1['rcpNo'] = "1";
    node1['dcmNo'] = "2";
    node1['eleId'] = "9";
    node1['offset'] = "3";
    node1['length'] = "4";
    node1['dtd'] = "dart3.xsd";
    node1['children'] = [];
    var node2 = {};
    node2['text'] = "1. 감사보고서 감리결과";
    node2['rcpNo'] = "1";
    node2['dcmNo'] = "2";
    node2['eleId'] = "10";
    node2['offset'] = "5";
    node2['length'] = "6";
    node2['dtd'] = "dart3.xsd";
    node1['children'].push(node2);
    treeData.push(node1);
    </script>
    """
    node = find_section(parse_toc(html), "vi")

    assert node is not None
    assert node.ele_id == "9"


def test_longer_section_wins_when_two_match() -> None:
    html = """
    <script>
    var treeData = [];
    var node1 = {};
    node1['text'] = "Ⅵ. 감리결과";
    node1['rcpNo'] = "1";
    node1['dcmNo'] = "1";
    node1['eleId'] = "1";
    node1['offset'] = "1";
    node1['length'] = "10";
    node1['dtd'] = "dart4.xsd";
    treeData.push(node1);
    var node1 = {};
    node1['text'] = "Ⅵ. 최근 3개 사업연도의 감리결과";
    node1['rcpNo'] = "1";
    node1['dcmNo'] = "1";
    node1['eleId'] = "2";
    node1['offset'] = "2";
    node1['length'] = "99";
    node1['dtd'] = "dart4.xsd";
    treeData.push(node1);
    </script>
    """
    node = find_section(parse_toc(html), "VI")

    assert node is not None
    assert node.ele_id == "2"


def test_plain_text_keeps_table_cells_and_drops_script() -> None:
    text = section_plain_text(_viewer())

    assert "secret-marker" not in text
    assert "Ⅵ. 최근 3개 사업연도의 감리결과" in text
    assert "감사절차소홀 (특수관계자거래)" in text
    assert "조치일자 | 감리지적사항" in text
    assert body_hash(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_normalize_body_collapses_blank_lines() -> None:
    assert normalize_body("가\r\n\n  나  ") == "가\n나"
    assert body_hash("가\r\n\n  나  ") == body_hash("가\n나")


@pytest.mark.parametrize(
    ("moment", "quiet"),
    [
        (datetime(2026, 11, 5, 6, 30, tzinfo=timezone.utc), True),
        (datetime(2026, 11, 5, 10, 59, tzinfo=timezone.utc), True),
        (datetime(2026, 11, 5, 11, 0, tzinfo=timezone.utc), False),
        (datetime(2026, 11, 5, 5, 0, tzinfo=timezone.utc), False),
        (datetime(2026, 7, 15, 5, 30, tzinfo=timezone.utc), True),
        (datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc), False),
    ],
)
def test_quiet_window_follows_chicago_clock(moment: datetime, quiet: bool) -> None:
    assert in_collector_quiet_window(moment) is quiet


def test_quiet_window_uses_dst_rule_when_tzdata_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows에는 시스템 tzdb가 없다. ZoneInfo가 실패해도 같은 창을 쓴다."""
    monkeypatch.setattr("app.sections.load._chicago_zone", lambda: None)
    cases = [
        (datetime(2026, 11, 5, 6, 30, tzinfo=timezone.utc), True),
        (datetime(2026, 11, 5, 10, 59, tzinfo=timezone.utc), True),
        (datetime(2026, 11, 5, 11, 0, tzinfo=timezone.utc), False),
        (datetime(2026, 11, 5, 5, 0, tzinfo=timezone.utc), False),
        (datetime(2026, 7, 15, 5, 30, tzinfo=timezone.utc), True),
        (datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc), False),
        # 2026-03-08은 둘째 일요일. 07:59 UTC=01:59 CST, 08:00 UTC=03:00 CDT.
        (datetime(2026, 3, 8, 7, 59, tzinfo=timezone.utc), True),
        (datetime(2026, 3, 8, 8, 0, tzinfo=timezone.utc), True),
        (datetime(2026, 3, 8, 10, 0, tzinfo=timezone.utc), False),
        # 2026-11-01은 첫째 일요일. 06:59 UTC=01:59 CDT, 07:00 UTC=01:00 CST.
        (datetime(2026, 11, 1, 6, 59, tzinfo=timezone.utc), True),
        (datetime(2026, 11, 1, 7, 0, tzinfo=timezone.utc), True),
        (datetime(2026, 11, 1, 11, 0, tzinfo=timezone.utc), False),
    ]
    for moment, quiet in cases:
        assert in_collector_quiet_window(moment) is quiet, moment


def test_dst_rule_offsets_at_the_transitions() -> None:
    spring_before = _chicago_from_rule(datetime(2026, 3, 8, 7, 59, tzinfo=timezone.utc))
    spring_after = _chicago_from_rule(datetime(2026, 3, 8, 8, 0, tzinfo=timezone.utc))
    fall_before = _chicago_from_rule(datetime(2026, 11, 1, 6, 59, tzinfo=timezone.utc))
    fall_after = _chicago_from_rule(datetime(2026, 11, 1, 7, 0, tzinfo=timezone.utc))

    assert spring_before.utcoffset() == timedelta(hours=-6)
    assert spring_before.hour == 1 and spring_before.minute == 59
    assert spring_after.utcoffset() == timedelta(hours=-5)
    assert spring_after.hour == 3 and spring_after.minute == 0
    assert fall_before.utcoffset() == timedelta(hours=-5)
    assert fall_before.hour == 1 and fall_before.minute == 59
    assert fall_after.utcoffset() == timedelta(hours=-6)
    assert fall_after.hour == 1 and fall_after.minute == 0


def test_dst_rule_matches_iana_chicago_when_tzdb_exists() -> None:
    """규칙 구현이 설치본 ZoneInfo와 같은 벽시계를 내는지 시간 단위로 대조한다."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        zone = ZoneInfo("America/Chicago")
    except ZoneInfoNotFoundError:
        pytest.skip("이 환경에는 America/Chicago 시간대 자료가 없습니다.")

    cursor = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2027, 1, 1, tzinfo=timezone.utc)
    while cursor < end:
        via_rule = _chicago_from_rule(cursor)
        via_iana = cursor.astimezone(zone)
        assert via_rule.utcoffset() == via_iana.utcoffset(), cursor
        assert (via_rule.year, via_rule.month, via_rule.day, via_rule.hour) == (
            via_iana.year,
            via_iana.month,
            via_iana.day,
            via_iana.hour,
        ), cursor
        cursor += timedelta(hours=1)


async def test_load_upserts_and_skips_until_refresh(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.db"
    sections = tmp_path / "sections.db"
    _write_catalog(catalog, [("20250701000044", "F004", None), ("1", "A001", None)])
    before_schema = _schema(catalog)
    calls: list[str] = []

    async def fetch(url: str) -> str:
        calls.append(url)
        if "main.do" in url:
            return _toc()
        return _viewer()

    summary = await load_section_bodies(
        catalog_db=catalog,
        sections_db=sections,
        fetch_html=fetch,
        now=lambda: OUTSIDE,
        on_progress=lambda _message: None,
    )
    again = await load_section_bodies(
        catalog_db=catalog,
        sections_db=sections,
        fetch_html=fetch,
        now=lambda: OUTSIDE,
        on_progress=lambda _message: None,
    )
    refreshed = await load_section_bodies(
        catalog_db=catalog,
        sections_db=sections,
        fetch_html=fetch,
        now=lambda: OUTSIDE,
        on_progress=lambda _message: None,
        refresh=True,
    )

    assert summary.line() == "attempted=1 loaded=1 not_found=0 failed=0"
    assert again.skipped == 1 and again.attempted == 0
    assert refreshed.loaded == 1
    assert len(calls) == 4
    assert _schema(catalog) == before_schema
    stored = _bodies(sections)
    assert len(stored) == 1
    assert stored[0]["rcept_no"] == "20250701000044"
    assert stored[0]["section_code"] == "VI"
    assert stored[0]["section_title"] == "Ⅵ. 최근 3개 사업연도의 감리결과"
    assert stored[0]["source_url"] == VIEWER_URL
    assert (
        stored[0]["body_hash"] == hashlib.sha256(stored[0]["body_text"].encode("utf-8")).hexdigest()
    )
    assert "감사절차소홀 (특수관계자거래)" in stored[0]["body_text"]
    assert stored[0]["fetched_at"].endswith("Z")
    mode = sqlite3.connect(sections).execute("PRAGMA journal_mode").fetchone()
    assert str(mode[0]).lower() == "wal"


async def test_not_found_is_distinct_and_not_retried(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.db"
    sections = tmp_path / "sections.db"
    _write_catalog(catalog, [("20250000000001", "f004", None)])
    calls: list[str] = []
    html = """
    <script>
    var treeData = [];
    var node1 = {};
    node1['text'] = "Ⅰ. 회계법인의 개황";
    node1['rcpNo'] = "20250000000001";
    node1['dcmNo'] = "1";
    node1['eleId'] = "1";
    node1['offset'] = "1";
    node1['length'] = "10";
    node1['dtd'] = "dart4.xsd";
    treeData.push(node1);
    </script>
    """

    async def fetch(url: str) -> str:
        calls.append(url)
        return html

    summary = await load_section_bodies(
        catalog_db=catalog,
        sections_db=sections,
        fetch_html=fetch,
        report_type="f004",
        now=lambda: OUTSIDE,
        on_progress=lambda _message: None,
    )
    again = await load_section_bodies(
        catalog_db=catalog,
        sections_db=sections,
        fetch_html=fetch,
        report_type="F004",
        now=lambda: OUTSIDE,
        on_progress=lambda _message: None,
    )

    assert summary.not_found == 1 and summary.failed == 0
    assert again.attempted == 0 and again.skipped == 1
    assert len(calls) == 1
    failure = _failures(sections)[0]
    assert failure["kind"] == "not_found"
    assert "VI" in failure["reason"]
    assert _bodies(sections) == []


async def test_fetch_error_is_retried(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.db"
    sections = tmp_path / "sections.db"
    _write_catalog(catalog, [("20250000000009", "F004", None)])
    calls: list[str] = []

    async def fetch(url: str) -> str:
        calls.append(url)
        raise SourceFetchError("원문을 가져오지 못했습니다(네트워크 오류)")

    first = await load_section_bodies(
        catalog_db=catalog,
        sections_db=sections,
        fetch_html=fetch,
        now=lambda: OUTSIDE,
        on_progress=lambda _message: None,
    )
    second = await load_section_bodies(
        catalog_db=catalog,
        sections_db=sections,
        fetch_html=fetch,
        now=lambda: OUTSIDE,
        on_progress=lambda _message: None,
    )

    assert first.failed == 1 and first.not_found == 0
    assert second.failed == 1
    assert len(calls) == 2
    assert _failures(sections)[0]["kind"] == "fetch_error"


async def test_short_page_is_fetch_error_not_missing_section(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.db"
    sections = tmp_path / "sections.db"
    _write_catalog(catalog, [("20250000000008", "F004", None)])

    async def fetch(_url: str) -> str:
        return "<html>짧음</html>"

    summary = await load_section_bodies(
        catalog_db=catalog,
        sections_db=sections,
        fetch_html=fetch,
        now=lambda: OUTSIDE,
        on_progress=lambda _message: None,
    )

    assert summary.failed == 1 and summary.not_found == 0
    assert _failures(sections)[0]["kind"] == "fetch_error"


async def test_limit_and_section_code_six(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.db"
    sections = tmp_path / "sections.db"
    _write_catalog(
        catalog,
        [
            ("20250000000001", "F004", None),
            ("20250000000002", "F004", None),
        ],
    )
    calls: list[str] = []

    async def fetch(url: str) -> str:
        calls.append(url)
        if "main.do" in url:
            return _toc()
        return _viewer()

    summary = await load_section_bodies(
        catalog_db=catalog,
        sections_db=sections,
        fetch_html=fetch,
        section_code="6",
        limit=1,
        now=lambda: OUTSIDE,
        on_progress=lambda _message: None,
    )

    assert summary.attempted == 1 and summary.loaded == 1
    assert len(calls) == 2
    stored = _bodies(sections)
    assert [row["rcept_no"] for row in stored] == ["20250000000001"]
    assert stored[0]["section_code"] == "VI"


async def test_stops_when_clock_enters_quiet_window(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.db"
    sections = tmp_path / "sections.db"
    _write_catalog(
        catalog,
        [
            ("20250000000001", "F004", None),
            ("20250000000002", "F004", None),
        ],
    )
    state = {"now": OUTSIDE}
    calls: list[str] = []

    async def fetch(url: str) -> str:
        calls.append(url)
        if "viewer.do" in url:
            state["now"] = INSIDE
        if "main.do" in url:
            return _toc()
        return _viewer()

    summary = await load_section_bodies(
        catalog_db=catalog,
        sections_db=sections,
        fetch_html=fetch,
        now=lambda: state["now"],
        on_progress=lambda _message: None,
    )

    assert summary.stopped_for_window is True
    assert summary.loaded == 1 and summary.attempted == 1
    assert len(calls) == 2
    assert [row["rcept_no"] for row in _bodies(sections)] == ["20250000000001"]


async def test_refuses_to_start_inside_quiet_window(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.db"
    sections = tmp_path / "sections.db"
    _write_catalog(catalog, [("20250701000044", "F004", None)])

    async def fetch(_url: str) -> str:
        raise AssertionError("조용한 시간에는 DART를 호출하면 안 됩니다.")

    with pytest.raises(CollectorWindowError):
        await load_section_bodies(
            catalog_db=catalog,
            sections_db=sections,
            fetch_html=fetch,
            now=lambda: INSIDE,
            on_progress=lambda _message: None,
        )

    assert not sections.exists()


def test_catalog_connection_is_read_only(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.db"
    _write_catalog(catalog, [("20250701000044", "F004", None)])
    connection = open_catalog_readonly(catalog)
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM disclosures")
    finally:
        connection.close()
    names = {row[1] for row in _schema(catalog)}
    assert "disclosures" in names
    count = sqlite3.connect(catalog).execute("SELECT count(*) FROM disclosures").fetchone()
    assert count is not None and count[0] == 1


def test_sections_db_opens_in_wal_mode(tmp_path: Path) -> None:
    connection = open_sections_db(tmp_path / "sections.db")
    try:
        mode = connection.execute("PRAGMA journal_mode").fetchone()
        assert str(mode[0]).lower() == "wal"
    finally:
        connection.close()


async def test_requests_keep_minimum_interval(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.db"
    sections = tmp_path / "sections.db"
    _write_catalog(catalog, [("20250701000044", "F004", None)])
    times: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        times.append(time.perf_counter())
        if "main.do" in str(request.url):
            return httpx.Response(200, text=_toc())
        return httpx.Response(200, text=_viewer())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        dart = DartHttpClient(client, min_interval_seconds=0.05, max_retries=0)
        summary = await load_section_bodies(
            catalog_db=catalog,
            sections_db=sections,
            fetch_html=dart.fetch_html,
            now=lambda: OUTSIDE,
            on_progress=lambda _message: None,
        )

    assert summary.loaded == 1
    assert len(times) == 2
    assert times[1] - times[0] >= 0.05


def test_same_path_for_both_databases_is_rejected(tmp_path: Path) -> None:
    catalog = tmp_path / "same.db"
    _write_catalog(catalog, [])

    async def fetch(_url: str) -> str:
        return ""

    with pytest.raises(ValueError):
        import asyncio

        asyncio.run(
            load_section_bodies(
                catalog_db=catalog,
                sections_db=catalog,
                fetch_html=fetch,
                ignore_window=True,
                on_progress=lambda _message: None,
            )
        )


def test_parser_defaults() -> None:
    args = build_parser().parse_args([])

    assert args.catalog_db.name == "dart_catalog.db"
    assert args.sections_db.name == "dart_sections.db"
    assert args.report_type == "F004"
    assert args.section_code == "VI"
    assert args.interval == 1.0
    assert args.limit == 0
    assert args.refresh is False
    assert args.ignore_window is False


def test_main_refuses_quiet_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = tmp_path / "catalog.db"
    sections = tmp_path / "sections.db"
    _write_catalog(catalog, [])
    monkeypatch.setattr(
        "app.sections.load._utcnow",
        lambda: INSIDE,
    )

    code = main(
        [
            "--catalog-db",
            str(catalog),
            "--sections-db",
            str(sections),
            "--interval",
            "0",
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert "00:00" in captured.out
    assert "attempted=0 loaded=0 not_found=0 failed=0" in captured.out
    assert not sections.exists()


def test_main_missing_catalog_returns_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "--catalog-db",
            str(tmp_path / "missing.db"),
            "--sections-db",
            str(tmp_path / "sections.db"),
            "--ignore-window",
            "--interval",
            "0",
        ]
    )

    assert code == 1
    assert "카탈로그" in capsys.readouterr().out


def test_summary_line_names_the_four_counts() -> None:
    line = LoadSummary(attempted=4, loaded=2, not_found=1, failed=1).line()
    assert line == "attempted=4 loaded=2 not_found=1 failed=1"
