"""Node 수집 브릿지 어댑터 테스트. 실제 node 대신 파이썬 가짜 스크립트를 실행한다."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.adapters.node_entry_collector import NodeEntryCollector
from app.errors import SourceFetchError
from app.ports.entry_collector import CollectRequest

FAKE_ENTRIES = [
    {
        "entry_id": "r1_d1_5",
        "rcept_no": "r1",
        "reportType": "F001",
        "dcmNo": "d1",
        "corp_code": "00224628",
        "source": "body",
        "section_name": "재무상태표",
        "path": ["감사보고서", "재무상태표"],
        "viewer_url": "https://dart.fss.or.kr/report/viewer.do?rcpNo=r1",
    },
    {
        "entry_id": "r2_d2_att",
        "rcept_no": "r2",
        "reportType": "F001",
        "dcmNo": "d2",
        "corp_code": "99999999",
        "source": "attachment",
        "section_name": "감사보고서",
        "path": ["감사보고서"],
        "viewer_url": "https://dart.fss.or.kr/report/viewer.do?rcpNo=r2",
    },
]


@pytest.fixture
def fake_script(tmp_path: Path) -> Path:
    """stdin JSON을 확인하고 고정 엔트리를 출력하는 가짜 수집 스크립트.

    Windows에서 파이프 기본 인코딩이 cp949이므로, 어댑터와 동일하게 UTF-8 바이트로 출력한다.
    """
    data_file = tmp_path / "entries.json"
    data_file.write_text(json.dumps(FAKE_ENTRIES, ensure_ascii=False), encoding="utf-8")

    script = tmp_path / "fake_collector.py"
    script.write_text(
        "import json, sys\n"
        "payload = json.loads(sys.stdin.read())\n"
        "assert payload['report_type'] == 'F001'\n"
        "sys.stderr.write('진행 로그\\n')\n"
        f"data = open(r'{data_file}', 'rb').read()\n"
        "sys.stdout.buffer.write(data)\n",
        encoding="utf-8",
    )
    return script


@pytest.fixture
def failing_script(tmp_path: Path) -> Path:
    """비정상 종료하는 가짜 수집 스크립트."""
    script = tmp_path / "failing_collector.py"
    script.write_text(
        "import sys\n"
        "sys.stderr.buffer.write('수집 실패: 목록 요청 오류\\n'.encode('utf-8'))\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    return script


async def test_collect_parses_entries(fake_script: Path) -> None:
    collector = NodeEntryCollector(sys.executable, fake_script)

    records = await collector.collect(
        CollectRequest(report_type="F001", start_date="20260701", end_date="20260724")
    )

    assert [record.entry_id for record in records] == ["r1_d1_5", "r2_d2_att"]
    assert records[0].report_type == "F001"
    assert records[0].dcm_no == "d1"


async def test_collect_filters_by_corp_code(fake_script: Path) -> None:
    collector = NodeEntryCollector(sys.executable, fake_script)

    records = await collector.collect(
        CollectRequest(
            report_type="F001",
            start_date="20260701",
            end_date="20260724",
            corp_code="00224628",
        )
    )

    assert [record.entry_id for record in records] == ["r1_d1_5"]


async def test_collect_raises_when_process_fails(failing_script: Path) -> None:
    collector = NodeEntryCollector(sys.executable, failing_script)

    with pytest.raises(SourceFetchError) as error:
        await collector.collect(
            CollectRequest(report_type="F001", start_date="20260701", end_date="20260724")
        )

    assert "수집 실패" in str(error.value)
