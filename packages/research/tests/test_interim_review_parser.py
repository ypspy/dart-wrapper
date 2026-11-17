"""검토보고서 필드 파서 테스트. 합성 HTML fixture만 읽는다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.extracting.interim_review import parse_interim_review

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "interim_review"
_MANIFEST = json.loads((_FIXTURE / "manifest.json").read_text(encoding="utf-8"))
_KEYS = (
    "conclusion_code",
    "conclusion_status",
    "review_report_date",
    "review_report_date_status",
    "review_period_resolved",
    "review_period_status",
    "gaap_code",
    "gaap_status",
    "emphasis_of_matter",
    "going_concern",
    "emphasis_status",
    "reviewer_status",
    "reviewer_resolved",
)


@pytest.mark.parametrize("expect", _MANIFEST["documents"], ids=lambda item: item["file"])
def test_parse_interim_fixture(expect: dict[str, object]) -> None:
    """합성 검토보고서에서 결론·날짜·기간·GAAP·강조·검토인을 읽는다."""
    html = (_FIXTURE / str(expect["file"])).read_text(encoding="utf-8")
    parsed = parse_interim_review(html)
    for key in _KEYS:
        assert getattr(parsed, key) == expect[key], key
    assert [item["iso"] for item in parsed.review_report_date_candidates] == expect[
        "candidate_isos"
    ]
    if expect["emphasis_status"] == "not_found":
        assert parsed.emphasis_raw is None
    else:
        assert parsed.emphasis_raw is not None
        assert len(parsed.emphasis_raw) <= 300
        prefix = expect.get("emphasis_raw_prefix")
        if prefix:
            assert str(parsed.emphasis_raw).startswith(str(prefix))
        if expect.get("emphasis_raw_len") is not None:
            assert len(parsed.emphasis_raw) == expect["emphasis_raw_len"]
    if parsed.review_report_date_status == "ok":
        assert parsed.review_report_date not in {
            item["iso"] for item in parsed.review_report_date_candidates
        }


def test_dictionary_name_is_preferred_for_reviewer() -> None:
    """감사인 목록에 있으면 그 정규화 이름을 검토인으로 쓴다."""
    html = """
    <html><body>
    <p>검토결론</p>
    <p>추가 자료가 필요합니다.</p>
    <p>라마 바회계법인</p>
    <p>대표이사 홍길동</p>
    </body></html>
    """
    parsed = parse_interim_review(html, auditor_names=("라마 바회계법인",))
    assert parsed.reviewer_status == "ok"
    assert parsed.reviewer_resolved == "라마바회계법인"
    assert parsed.conclusion_code == "unknown"
