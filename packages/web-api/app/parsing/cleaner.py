"""DART 원문 HTML에서 읽을 수 있는 본문 텍스트를 추출한다.

블록 파서 결과에서 heading·paragraph만 이어 붙인다. 표 내용은 제외되며, 표는
`tables` 모듈에서 별도로 다룬다.
"""

from __future__ import annotations

from app.parsing.blocks import blocks_to_text, extract_blocks


def extract_text(html: str) -> str:
    """표를 제외한 본문 텍스트를 반환한다.

    :param html: 디코딩이 끝난 원문 HTML 문자열
    :return: 빈 줄이 없는 본문 텍스트(표 텍스트 제외)
    :raises ParseError: HTML 파싱에 실패한 경우
    """
    return blocks_to_text(extract_blocks(html))
