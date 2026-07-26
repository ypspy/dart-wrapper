"""DART 원문 HTML의 표를 JSON 구조로 변환한다.

블록 파서의 table 블록에서 headers/rows를 뽑아 dict 목록으로 돌려준다.
"""

from __future__ import annotations

from app.parsing.blocks import blocks_to_tables, extract_blocks


def extract_tables(html: str) -> list[dict[str, list]]:
    """HTML의 모든 표를 headers/rows 구조로 변환한다.

    :param html: 디코딩이 끝난 원문 HTML 문자열
    :return: 표별 {"headers": [...], "rows": [[...]]} 목록
    :raises ParseError: HTML 파싱에 실패한 경우
    """
    return [
        {"headers": table.headers, "rows": table.rows}
        for table in blocks_to_tables(extract_blocks(html))
    ]
