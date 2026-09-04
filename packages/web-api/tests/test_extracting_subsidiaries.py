from app.extracting.accounts import cut_notes
from app.extracting.subsidiaries import extract_subsidiaries, notes_tail


def test_separate_is_not_applicable() -> None:
    result = extract_subsidiaries(
        fs_scope="separate",
        notes_html="<p>종속기업</p>",
        a001_html=None,
    )
    assert result.status == "not_applicable"
    assert result.count is None


def test_notes_counts_body_rows() -> None:
    html = """
    <html><body>
    <p>3. 종속기업</p>
    <table>
    <tr><td>회사명</td><td>소재지</td><td>지분율</td></tr>
    <tr><td>갑주식회사</td><td>한국</td><td>100%</td></tr>
    <tr><td>을주식회사</td><td>한국</td><td>80%</td></tr>
    <tr><td>합계</td><td></td><td></td></tr>
    </table>
    </body></html>
    """
    result = extract_subsidiaries(fs_scope="consolidated", notes_html=html, a001_html=None)
    assert result.status == "ok"
    assert result.count == 2
    assert result.source == "notes"


def test_kind_column_counts_subsidiary_only() -> None:
    html = """
    <html><body>
    <p>연결대상 및 관계기업</p>
    <table>
    <tr><td>회사명</td><td>구분</td></tr>
    <tr><td>갑</td><td>종속기업</td></tr>
    <tr><td>을</td><td>관계기업</td></tr>
    <tr><td>병</td><td>공동기업</td></tr>
    </table>
    </body></html>
    """
    result = extract_subsidiaries(fs_scope="consolidated", notes_html=html, a001_html=None)
    assert result.status == "ok"
    assert result.count == 1


def test_related_party_title_without_kind_is_not_found() -> None:
    html = """
    <html><body>
    <p>특수관계자</p>
    <table>
    <tr><td>회사명</td><td>거래</td></tr>
    <tr><td>갑</td><td>매출</td></tr>
    </table>
    </body></html>
    """
    result = extract_subsidiaries(fs_scope="consolidated", notes_html=html, a001_html=None)
    assert result.status == "not_found"
    assert result.count is None


def test_empty_subsidiary_table_is_zero() -> None:
    html = """
    <html><body>
    <p>종속기업</p>
    <table>
    <tr><td>회사명</td><td>소재지</td></tr>
    </table>
    </body></html>
    """
    result = extract_subsidiaries(fs_scope="consolidated", notes_html=html, a001_html=None)
    assert result.status == "ok"
    assert result.count == 0


def test_a001_requires_kind_column() -> None:
    mixed = """
    <html><body>
    <p>계열회사의 현황</p>
    <table>
    <tr><td>회사명</td><td>업종</td></tr>
    <tr><td>갑</td><td>제조</td></tr>
    <tr><td>을</td><td>판매</td></tr>
    </table>
    </body></html>
    """
    result = extract_subsidiaries(fs_scope="consolidated", notes_html=None, a001_html=mixed)
    assert result.status == "not_found"

    ok_html = """
    <html><body>
    <p>계열회사의 현황</p>
    <table>
    <tr><td>회사명</td><td>관계</td></tr>
    <tr><td>갑</td><td>종속회사</td></tr>
    <tr><td>을</td><td>관계회사</td></tr>
    </table>
    </body></html>
    """
    result = extract_subsidiaries(fs_scope="consolidated", notes_html=None, a001_html=ok_html)
    assert result.status == "ok"
    assert result.count == 1
    assert result.source == "a001"


def test_a001_kind_column_without_subsidiary_is_not_found() -> None:
    html = """
    <table>
    <tr><td>회사명</td><td>기업구분</td></tr>
    <tr><td>갑</td><td>관계기업</td></tr>
    <tr><td>을</td><td>계열회사</td></tr>
    </table>
    """
    result = extract_subsidiaries(fs_scope="consolidated", notes_html=None, a001_html=html)
    assert result.status == "not_found"
    assert result.count is None


def test_notes_uses_first_matching_heading_table() -> None:
    html = """
    <p>관계기업 현황</p>
    <table>
    <tr><td>회사명</td></tr>
    <tr><td>관계사</td></tr>
    </table>
    <p>종속기업 현황</p>
    <table>
    <tr><td>회사명</td></tr>
    <tr><td>갑</td></tr>
    </table>
    <p>연결대상 현황</p>
    <table>
    <tr><td>회사명</td></tr>
    <tr><td>을</td></tr>
    <tr><td>병</td></tr>
    </table>
    """
    result = extract_subsidiaries(fs_scope="consolidated", notes_html=html, a001_html=None)
    assert result.status == "ok"
    assert result.count == 1
    assert result.source == "notes"


def test_notes_tail_is_inverse_of_cut_notes() -> None:
    html = "<p>재무상태표</p><table><tr><td>자산총계</td></tr></table>" "주석 1. 종속기업"
    assert "자산총계" in cut_notes(html)
    assert "종속기업" in notes_tail(html)
    assert "자산총계" not in notes_tail(html)
