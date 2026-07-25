"""NodeEntryCollector의 list/extract 모드 계약 테스트.

실제 Node 프로세스를 띄우지 않고, 서브프로세스 실행 결과만 대체한다.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.adapters.node_entry_collector import NodeEntryCollector
from app.errors import SourceFetchError
from app.ports.entry_collector import CollectRequest, DisclosureListItem

REQUEST = CollectRequest(report_type="F001", start_date="20260724", end_date="20260724")

LIST_OUTPUT = {
    "listed_count": 2,
    "items": [
        {
            "reportType": "F001",
            "rcept_no": "20260724000650",
            "corp_name": "테스트",
            "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260724000650",
        },
        {
            "reportType": "F001",
            "rcept_no": "20260724000651",
            "corp_name": "다른회사",
            "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260724000651",
        },
    ],
}

ENTRY_OUTPUT = [
    {
        "entry_id": "20260724000650_1_5",
        "rcept_no": "20260724000650",
        "reportType": "F001",
        "source": "body",
        "section_name": "재무상태표",
        "viewer_url": "https://dart.fss.or.kr/report/viewer.do?rcpNo=20260724000650",
    }
]


@pytest.fixture
def collector() -> NodeEntryCollector:
    return NodeEntryCollector("node", Path("collect-entries.js"), timeout_seconds=10)


def _fake_run(stdout: object, recorder: list[dict]):
    """subprocess.run을 대체해 stdin 페이로드를 기록하고 고정 출력을 돌려준다."""

    def runner(args, input=None, capture_output=None, timeout=None):  # noqa: A002
        recorder.append(json.loads(input.decode("utf-8")))
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(stdout, ensure_ascii=False).encode("utf-8"),
            stderr=b"",
        )

    return runner


async def test_list_disclosures_parses_listed_count(monkeypatch, collector) -> None:
    payloads: list[dict] = []
    monkeypatch.setattr(subprocess, "run", _fake_run(LIST_OUTPUT, payloads))

    result = await collector.list_disclosures(REQUEST)

    assert payloads[0]["mode"] == "list"
    assert payloads[0]["start_date"] == "20260724"
    assert result.listed_count == 2
    assert [item.rcept_no for item in result.items] == ["20260724000650", "20260724000651"]


async def test_extract_disclosure_returns_entries(monkeypatch, collector) -> None:
    payloads: list[dict] = []
    monkeypatch.setattr(subprocess, "run", _fake_run(ENTRY_OUTPUT, payloads))

    item = DisclosureListItem.model_validate(LIST_OUTPUT["items"][0])
    records = await collector.extract_disclosure(item, include_attachments=False)

    assert payloads[0]["mode"] == "extract"
    assert payloads[0]["include_attachments"] is False
    assert payloads[0]["disclosure"]["rcept_no"] == "20260724000650"
    assert [record.entry_id for record in records] == ["20260724000650_1_5"]


async def test_extract_disclosure_raises_on_process_failure(monkeypatch, collector) -> None:
    def failing_run(args, input=None, capture_output=None, timeout=None):  # noqa: A002
        return subprocess.CompletedProcess(
            args=args, returncode=1, stdout=b"", stderr="상세 파싱 실패".encode("utf-8")
        )

    monkeypatch.setattr(subprocess, "run", failing_run)
    item = DisclosureListItem.model_validate(LIST_OUTPUT["items"][0])

    with pytest.raises(SourceFetchError):
        await collector.extract_disclosure(item)
