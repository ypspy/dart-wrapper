"""FactRepository.list_page 조인·정렬·cursor 테스트."""

import pytest

from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.extracting.constants import EXTRACTOR_VERSION
from app.models.audit_report_fact import AuditReportFact
from app.models.disclosure import Disclosure
from app.repositories.fact_repository import FactRepository


@pytest.fixture
async def sessionmaker_fixture():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    yield create_sessionmaker(engine)
    await engine.dispose()


def _fact(**overrides: object) -> AuditReportFact:
    values: dict[str, object] = {
        "rcept_no": "20200331000001",
        "dcm_no": "11111",
        "source_report_type": "F001",
        "fs_scope": "separate",
        "fetch_status": "ok",
        "extractor_version": EXTRACTOR_VERSION,
    }
    values.update(overrides)
    return AuditReportFact(**values)


def _disc(**overrides: object) -> Disclosure:
    values: dict[str, object] = {
        "rcept_no": "20200331000001",
        "corp_name": "갑",
        "year_end": "(2019.12)",
        "rcept_dt": "2020.03.31",
        "correction_type": "최초공시",
        "report_nm": "감사보고서",
        "report_type": "F001",
        "corp_code": "00123456",
        "entry_count": 1,
    }
    values.update(overrides)
    return Disclosure(**values)


async def test_list_page_inner_join_drops_orphan_facts(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add(_fact())
        await session.commit()
        rows = await FactRepository(session).list_page(limit=20)
    assert rows == []


async def test_list_page_orders_date_desc_rcept_desc_dcm_asc(
    sessionmaker_fixture,
) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all(
            [
                _disc(rcept_no="20240331000002", rcept_dt="2024.03.31", corp_name="을"),
                _disc(
                    rcept_no="20240331000001",
                    rcept_dt="2024.03.31",
                    corp_name="병",
                    report_type="A001",
                    report_nm="사업보고서",
                ),
                _disc(rcept_no="20200331000001", rcept_dt="2020.03.31"),
                _fact(rcept_no="20200331000001"),
                _fact(
                    rcept_no="20240331000001",
                    dcm_no="22222",
                    source_report_type="A001",
                    fs_scope="consolidated",
                ),
                _fact(
                    rcept_no="20240331000001",
                    dcm_no="11111",
                    source_report_type="A001",
                    fs_scope="separate",
                ),
                _fact(rcept_no="20240331000002", dcm_no="33333"),
            ]
        )
        await session.commit()
        rows = await FactRepository(session).list_page(limit=20)
    keys = [(d.rcept_dt, f.rcept_no, f.dcm_no) for f, d in rows]
    assert keys == [
        ("2024.03.31", "20240331000002", "33333"),
        ("2024.03.31", "20240331000001", "11111"),
        ("2024.03.31", "20240331000001", "22222"),
        ("2020.03.31", "20200331000001", "11111"),
    ]


async def test_list_page_filters_and_keyset(sessionmaker_fixture) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all(
            [
                _disc(rcept_no="a", rcept_dt="2024.03.31", corp_name="삼성전자"),
                _disc(rcept_no="b", rcept_dt="2024.03.31", corp_name="다른회사"),
                _fact(rcept_no="a", dcm_no="1"),
                _fact(rcept_no="b", dcm_no="1"),
            ]
        )
        await session.commit()
        repo = FactRepository(session)
        named = await repo.list_page(limit=20, corp_name="삼성")
        assert [f.rcept_no for f, _d in named] == ["a"]
        page1 = await repo.list_page(limit=1)
        assert page1[0][0].rcept_no == "b"
        page2 = await repo.list_page(
            limit=1,
            cursor_rcept_dt=page1[0][1].rcept_dt,
            cursor_rcept_no=page1[0][0].rcept_no,
            cursor_dcm_no=page1[0][0].dcm_no,
        )
        assert page2[0][0].rcept_no == "a"


async def test_list_page_report_type_uses_source_report_type(
    sessionmaker_fixture,
) -> None:
    async with sessionmaker_fixture() as session:
        session.add_all(
            [
                _disc(rcept_no="a", report_type="A001"),
                _fact(rcept_no="a", source_report_type="A001"),
            ]
        )
        await session.commit()
        repo = FactRepository(session)
        matched = await repo.list_page(limit=20, report_type="A001")
        missed = await repo.list_page(limit=20, report_type="F001")
    assert [f.source_report_type for f, _d in matched] == ["A001"]
    assert missed == []
