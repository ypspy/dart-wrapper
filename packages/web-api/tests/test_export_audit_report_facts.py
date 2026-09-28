"""감사보고서 facts TSV export 스크립트 테스트."""

from __future__ import annotations

from io import StringIO

import pytest

from app.config import Settings
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.extracting.constants import EXTRACTOR_VERSION
from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
from app.models.entry import Entry
from app.models.extraction_review import ExtractionReview
from scripts.export_audit_report_facts import build_parser, iter_rows, write_tsv


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def _fact(**overrides: object) -> AuditReportFact:
    """export 조인 검증용 최소 facts 행."""
    values: dict[str, object] = {
        "rcept_no": "20200331000001",
        "dcm_no": "11111",
        "source_report_type": "F001",
        "fs_scope": "separate",
        "opinion_resolved": "unqualified",
        "fetch_status": "ok",
        "conflicts": [{"field": "auditor", "left": "표지", "right": "본문"}],
        "audit_report_date_candidates": [
            {"date": "2020-02-20", "snippet": "감사보고서일은 2020년 2월 20일입니다."},
        ],
        "extractor_version": EXTRACTOR_VERSION,
    }
    values.update(overrides)
    return AuditReportFact(**values)


def _entry(**overrides: object) -> Entry:
    """같은 문서의 leaf entry. 조인 폴백에 쓴다."""
    values: dict[str, object] = {
        "entry_id": "e-cover",
        "rcept_no": "20200331000001",
        "source": "body",
        "dcm_no": "11111",
        "corp_name": "삼성전자",
        "year_end": "(2019.12)",
        "rcept_dt": "20200331",
        "correction_type": None,
        "path": ["감사보고서"],
    }
    values.update(overrides)
    return Entry(**values)


def _disclosure(**overrides: object) -> Disclosure:
    """접수 단위 카탈로그. export가 우선하는 조인 대상이다."""
    values: dict[str, object] = {
        "rcept_no": "20200331000001",
        "corp_name": "삼성전자",
        "year_end": "(2019.12)",
        "rcept_dt": "20200331",
        "correction_type": None,
        "report_type": "F001",
        "entry_count": 1,
    }
    values.update(overrides)
    return Disclosure(**values)


async def test_iter_rows_joins_disclosure_catalog_fields(sessionmaker_fixture) -> None:
    """facts에 없는 회사명·결산월·접수일·정정구분을 disclosures에서 붙인다."""
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        session.add(_disclosure())
        session.add(_entry())
        await session.commit()
        rows = list(await iter_rows(session))

    assert len(rows) == 1
    row = rows[0]
    assert row["rcept_no"] == "20200331000001"
    assert row["dcm_no"] == "11111"
    assert row["corp_name"] == "삼성전자"
    assert row["year_end"] == "(2019.12)"
    assert row["rcept_dt"] == "20200331"
    assert row["correction_type"] is None
    assert row["opinion_resolved"] == "unqualified"
    assert row["fetch_status"] == "ok"


async def test_iter_rows_includes_original_and_correction(sessionmaker_fixture) -> None:
    """최종 접수만 남기는 필터가 없다. 정정 전·후 행이 모두 나온다."""
    async with sessionmaker_fixture() as session:
        session.add(_fact(rcept_no="20200331000001", dcm_no="111"))
        session.add(
            _disclosure(
                rcept_no="20200331000001",
                correction_type=None,
                rcept_dt="20200330",
            )
        )
        session.add(
            _fact(
                rcept_no="20200331000002",
                dcm_no="222",
                opinion_resolved="qualified",
            )
        )
        session.add(
            _disclosure(
                rcept_no="20200331000002",
                correction_type="정정",
                rcept_dt="20200331",
                corp_name="삼성전자",
            )
        )
        await session.commit()
        rows = list(await iter_rows(session))

    by_rcept = {row["rcept_no"]: row for row in rows}
    assert set(by_rcept) == {"20200331000001", "20200331000002"}
    assert by_rcept["20200331000001"]["correction_type"] is None
    assert by_rcept["20200331000002"]["correction_type"] == "정정"


async def test_iter_rows_falls_back_to_entry_when_disclosure_missing(
    sessionmaker_fixture,
) -> None:
    """disclosure가 없으면 같은 rcept_no·dcm_no entry에서 카탈로그 필드를 가져온다."""
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        session.add(_entry(corp_name="엔트리회사", year_end="(2018.12)"))
        await session.commit()
        rows = list(await iter_rows(session))

    assert rows[0]["corp_name"] == "엔트리회사"
    assert rows[0]["year_end"] == "(2018.12)"
    assert rows[0]["rcept_dt"] == "20200331"


async def test_iter_rows_prefers_disclosure_over_entry(sessionmaker_fixture) -> None:
    """같은 접수에 entry와 disclosure가 있으면 disclosure 값을 쓴다.

    disclosure 컬럼이 NULL이어도 entry로 덮지 않는다. 원본 접수의
    correction_type=None을 유지해야 한다.
    """
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        session.add(_entry(corp_name="옛이름", correction_type="정정"))
        session.add(_disclosure(corp_name="공시이름", correction_type=None))
        await session.commit()
        rows = list(await iter_rows(session))

    assert rows[0]["corp_name"] == "공시이름"
    assert rows[0]["correction_type"] is None


async def test_iter_rows_does_not_duplicate_when_many_entries(
    sessionmaker_fixture,
) -> None:
    """한 문서에 leaf가 여러 개여도 facts 행은 하나다."""
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        session.add(_disclosure())
        session.add(_entry(entry_id="e-cover", section_name="감사보고서"))
        session.add(
            _entry(
                entry_id="e-opinion",
                section_name="독립된 감사인의 감사보고서",
            )
        )
        await session.commit()
        rows = list(await iter_rows(session))

    assert len(rows) == 1


async def test_iter_rows_empty_when_no_facts(sessionmaker_fixture) -> None:
    """facts가 없으면 빈 목록이다."""
    async with sessionmaker_fixture() as session:
        session.add(_disclosure())
        await session.commit()
        rows = list(await iter_rows(session))

    assert rows == []


def test_parser_database_url_defaults_to_app_config() -> None:
    """--database-url 기본값은 앱 Settings와 같다."""
    parser = build_parser()
    args = parser.parse_args([])
    assert args.database_url == Settings().database_url
    assert args.out is None


def test_parser_accepts_out_and_has_no_final_reception_flag() -> None:
    """--out만 두고 최종 접수 필터 플래그는 없다."""
    parser = build_parser()
    args = parser.parse_args(["--out", "facts.tsv"])
    assert args.out == "facts.tsv"
    dests = {action.dest for action in parser._actions}
    option_strings = {flag for action in parser._actions for flag in action.option_strings}
    assert "final_reception" not in dests
    assert "--final-reception" not in option_strings


def test_write_tsv_emits_header_and_joined_fields() -> None:
    """TSV 첫 줄은 헤더이고 조인 컬럼·facts 값이 탭으로 구분된다."""
    buf = StringIO()
    write_tsv(
        [
            {
                "corp_name": "삼성전자",
                "year_end": "(2019.12)",
                "rcept_dt": "20200331",
                "correction_type": None,
                "rcept_no": "20200331000001",
                "dcm_no": "11111",
                "opinion_resolved": "unqualified",
                "conflicts": [{"field": "auditor"}],
            }
        ],
        buf,
    )
    lines = buf.getvalue().splitlines()
    header = lines[0].split("\t")
    assert header[:4] == ["corp_name", "year_end", "rcept_dt", "correction_type"]
    assert "rcept_no" in header
    body = lines[1].split("\t")
    by_col = dict(zip(header, body, strict=True))
    assert by_col["corp_name"] == "삼성전자"
    assert by_col["correction_type"] == ""
    assert by_col["opinion_resolved"] == "unqualified"
    assert "auditor" in by_col["conflicts"]


async def test_with_reviews_appends_source_tags_only(sessionmaker_fixture) -> None:
    """소스 판정 태그만 source_tags로 붙이고, 기본 호출은 그 열을 넣지 않는다."""
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        session.add(
            ExtractionReview(
                rcept_no="20200331000001",
                dcm_no="11111",
                bundle="accounts",
                signal="account_negative",
                subject="total_asset",
                extractor_version=EXTRACTOR_VERSION,
                in_research_panel=True,
                stratum="F001|separate|total_asset",
                tail="",
                raw_value="-1",
                active=True,
                verdict="source",
                tag="as_written",
                note="",
            )
        )
        session.add(
            ExtractionReview(
                rcept_no="20200331000001",
                dcm_no="11111",
                bundle="hours",
                signal="fail",
                subject="not_found|missing=1|conflicts=0",
                extractor_version=EXTRACTOR_VERSION,
                in_research_panel=False,
                stratum="*|*|hours",
                tail="",
                raw_value="",
                active=True,
                verdict="logic",
                tag="",
                note="",
            )
        )
        await session.commit()
        rows = list(await iter_rows(session, with_reviews=True))
        plain = list(await iter_rows(session))
    assert rows[0]["source_tags"] == "accounts:total_asset:as_written"
    assert "source_tags" not in plain[0]
