"""본문 텍스트 정제 테스트."""

from __future__ import annotations

from app.parsing.cleaner import extract_text

SAMPLE_HTML = """
<html>
  <head>
    <style>.a { color: red; }</style>
    <script>var x = 1;</script>
  </head>
  <body>
    <!-- 주석은 제외된다 -->
    <p>재무상태표</p>
    <p>자산총계&nbsp;&nbsp;1,000</p>
    <div>

    </div>
    <noscript>스크립트 비활성</noscript>
    <p>부채총계   400</p>
  </body>
</html>
"""


def test_extract_text_removes_noise_and_blank_lines() -> None:
    text = extract_text(SAMPLE_HTML)

    assert "재무상태표" in text
    assert "자산총계 1,000" in text
    assert "부채총계 400" in text
    assert "var x" not in text
    assert "color: red" not in text
    assert "주석은 제외된다" not in text
    assert "스크립트 비활성" not in text
    assert "\n\n" not in text


def test_extract_text_returns_empty_string_for_blank_html() -> None:
    assert extract_text("<html><body>   </body></html>") == ""


TABLE_HTML = """
<html><body>
  <p>서문</p>
  <table><tr><th>A</th></tr><tr><td>1</td></tr></table>
</body></html>
"""


def test_extract_text_excludes_table_contents() -> None:
    text = extract_text(TABLE_HTML)
    assert "서문" in text
    assert "1" not in text
    assert "A" not in text
