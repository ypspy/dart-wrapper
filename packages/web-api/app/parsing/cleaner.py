"""DART 원문 HTML에서 읽을 수 있는 본문 텍스트를 추출한다."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment

from app.errors import ParseError

# 본문과 무관한 태그는 통째로 제거한다.
_NOISE_TAGS = ("script", "style", "noscript", "iframe", "link", "meta")
_SPACES = re.compile(r"[ \t\u00a0\u3000]+")


def extract_text(html: str) -> str:
    """script/style/주석을 제거하고 공백을 정리한 본문 텍스트를 반환한다.

    :param html: 디코딩이 끝난 원문 HTML 문자열
    :return: 빈 줄이 없는 본문 텍스트
    :raises ParseError: HTML 파싱에 실패한 경우
    """
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:  # pragma: no cover - lxml 내부 오류 방어
        raise ParseError(f"본문 HTML을 파싱하지 못했습니다: {exc}") from exc

    for tag in soup(list(_NOISE_TAGS)):
        tag.decompose()
    for comment in soup.find_all(string=lambda node: isinstance(node, Comment)):
        comment.extract()

    raw_text = soup.get_text("\n")
    lines = (_SPACES.sub(" ", line).strip() for line in raw_text.splitlines())
    return "\n".join(line for line in lines if line)
