"""외부감사 실시내용 상단 회사명·결산월 헤더."""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.extracting.text import compact

_CORP_LABEL = "회사명"


def extract_activity_header(html: str) -> tuple[str | None, str | None]:
    """회사명·결산/사업연도 라벨 행에서 회사명과 결산월을 읽는다.

    D-4-1의 투입시간·Indexing·ParsingTime은 가져오지 않는다.
    """
    soup = BeautifulSoup(html, "lxml")
    corp_name: str | None = None
    from_fiscal: str | None = None
    from_year: str | None = None

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [compact(cell.get_text()) for cell in row.find_all(["th", "td"])]
            for index, text in enumerate(cells):
                if not text or index + 1 >= len(cells):
                    continue
                value = cells[index + 1]
                if not value:
                    continue
                if _CORP_LABEL in text and corp_name is None:
                    corp_name = value
                elif "결산" in text and from_fiscal is None:
                    from_fiscal = value
                elif "사업연도" in text and from_year is None:
                    from_year = value

    return corp_name, from_fiscal or from_year
