"""D-2 감사보고서 표지 당기·감사인 추출."""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.extracting.result import FieldResult
from app.extracting.text import compact

_NOT_FOUND = FieldResult(raw=None, code=None, status="not_found")


def extract_cover_period(html_or_text: str) -> FieldResult:
    """표 텍스트에서 기/期 뒤 당기 구간을 뽑는다 (D-2-1)."""
    soup = BeautifulSoup(html_or_text, "lxml")
    tables = soup.find_all("table")
    if tables:
        current_period = ""
        found_year = False
        for table in tables:
            current_period = compact(table.get_text())
            if "20" in current_period:
                found_year = True
                break
        if not found_year:
            return _NOT_FOUND
    else:
        current_period = compact(soup.get_text())

    if "期" in current_period:
        period = current_period.split("期")[1]
    elif "기" in current_period:
        period = current_period.split("기")[1]
    else:
        return _NOT_FOUND

    if not period:
        return _NOT_FOUND
    return FieldResult(raw=period, code=None, status="ok")


def extract_cover_auditor(html: str) -> FieldResult:
    """p/td에서 회계법인 또는 감사반 문구를 뽑는다 (D-2-2)."""
    soup = BeautifulSoup(html, "lxml")
    firm_name = ""
    for tag in soup.find_all("p"):
        text = compact(tag.get_text())
        if "회계법인" in text or "감사반" in text:
            firm_name = text
    for tag in soup.find_all("td"):
        text = compact(tag.get_text())
        if "회계법인" in text or "감사반" in text:
            firm_name = text
    if not firm_name:
        return _NOT_FOUND
    return FieldResult(raw=firm_name, code=None, status="ok")
