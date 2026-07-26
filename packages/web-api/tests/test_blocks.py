"""문서 순서 블록 추출 테스트."""

from __future__ import annotations

from app.parsing.blocks import blocks_to_tables, blocks_to_text, extract_blocks

SAMPLE = """
<html><body>
  <script>bad()</script>
  <h2>재무상태표</h2>
  <p>자산총계는 다음과 같다.</p>
  <table>
    <tr><th>과목</th><th>당기</th></tr>
    <tr><td>자산총계</td><td>1,000</td></tr>
  </table>
  <p>주석을 참고한다.</p>
  <table></table>
</body></html>
"""


def test_extract_blocks_preserves_order_and_skips_table_text_in_paragraphs() -> None:
    blocks = extract_blocks(SAMPLE)

    assert [b.type for b in blocks] == [
        "heading",
        "paragraph",
        "table",
        "paragraph",
    ]
    assert blocks[0].text == "재무상태표"
    assert blocks[0].level == 2
    assert blocks[1].text == "자산총계는 다음과 같다."
    assert blocks[2].headers == ["과목", "당기"]
    assert blocks[2].rows == [["자산총계", "1,000"]]
    assert blocks[3].text == "주석을 참고한다."
    joined = " ".join(b.text for b in blocks if b.type == "paragraph")
    assert "1,000" not in joined


def test_blocks_to_text_excludes_tables() -> None:
    blocks = extract_blocks(SAMPLE)
    text = blocks_to_text(blocks)
    assert "재무상태표" in text
    assert "주석을 참고한다" in text
    assert "1,000" not in text
    assert "과목" not in text


def test_blocks_to_tables_matches_table_blocks() -> None:
    blocks = extract_blocks(SAMPLE)
    tables = blocks_to_tables(blocks)
    assert len(tables) == 1
    assert tables[0].headers == ["과목", "당기"]


def test_extract_blocks_removes_noise() -> None:
    blocks = extract_blocks(SAMPLE)
    dumped = " ".join(str(b) for b in blocks)
    assert "bad()" not in dumped


def test_heading_levels_clamped_to_three() -> None:
    blocks = extract_blocks("<html><body><h1>가</h1><h5>나</h5></body></html>")
    assert [b.level for b in blocks if b.type == "heading"] == [1, 3]


def test_blank_html_returns_no_blocks() -> None:
    assert extract_blocks("<html><body>   </body></html>") == []
