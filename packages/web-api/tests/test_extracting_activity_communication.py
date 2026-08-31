"""외부감사 실시내용 4절 커뮤니케이션 추출 테스트."""

from app.extracting.activity_communication import extract_communications

_HTML = """
<html><body>
<p>3. 주요 감사실시내용</p>
<table><tr><td>지배기구와의 커뮤니케이션</td><td>감사위원회</td></tr></table>
<p>4. 감사(감사위원회)와의 커뮤니케이션</p>
<table>
<tr><th>구분</th><th>일자</th><th>참석자</th><th>방식</th><th>주요 논의 내용</th></tr>
<tr><td>1</td><td>2024.05.14</td><td>회사측: 감사위원회 위원 3명</td><td>대면회의</td><td>1분기</td></tr>
</table>
<p>5. 감사인의 중요성 금액</p>
<table><tr><td>재무제표 전체 중요성</td><td>10억원</td></tr></table>
</body></html>
"""


def test_communications_reads_section_four_not_three_or_five() -> None:
    """4절 표만 읽고 3절·5절 표는 무시한다."""
    payload, status = extract_communications(_HTML)
    assert status == "ok"
    assert payload["has_audit_committee"] is True
    assert payload["items"][0]["일자"] == "2024.05.14"
    assert "10억원" not in str(payload)


def test_title_alone_is_not_audit_committee() -> None:
    """제목의 감사위원회는 has_audit_committee를 켜지 않는다."""
    html = """
    <html><body>
    <p>4. 감사(감사위원회)와의 커뮤니케이션</p>
    <table>
    <tr><th>구분</th><th>일자</th><th>참석자</th></tr>
    <tr><td>1</td><td>2019.03.01</td><td>감사 1명</td></tr>
    </table>
    </body></html>
    """
    payload, status = extract_communications(html)
    assert status == "ok"
    assert payload["has_audit_committee"] is False


def test_missing_section_four_is_not_found() -> None:
    """4절이 없으면 not_found와 빈 페이로드다."""
    payload, status = extract_communications("<html><body><p>3. 주요</p></body></html>")
    assert status == "not_found"
    assert payload["items"] == []
    assert payload["has_audit_committee"] is False
