"""DART 원문 HTML 수집기. 한국어 인코딩을 자동 판별한다."""

from __future__ import annotations

import asyncio
import re

import httpx

from app.errors import SourceFetchError

_CHARSET_IN_HEADER = re.compile(r"charset=([\w\-]+)", re.IGNORECASE)
_CHARSET_IN_META = re.compile(rb"charset=[\"']?\s*([\w\-]+)", re.IGNORECASE)
# EUC-KR로 표기된 문서에도 확장 한글이 들어오므로 상위 호환 코덱으로 읽는다.
_KOREAN_ALIASES = {"euc-kr", "euckr", "ks_c_5601-1987", "ksc5601", "korean"}


def _normalize_charset(charset: str | None) -> str | None:
    """문자셋 이름을 파이썬 코덱 이름으로 정규화한다."""
    if charset is None:
        return None
    lowered = charset.strip().lower()
    return "cp949" if lowered in _KOREAN_ALIASES else lowered


def decode_html(content: bytes, content_type: str | None = None) -> str:
    """응답 헤더 → meta charset → 한국어 코덱 순으로 디코딩을 시도한다.

    :param content: 원문 바이트
    :param content_type: 응답의 Content-Type 헤더 값
    :return: 디코딩된 HTML 문자열
    """
    declared = None
    if content_type:
        matched = _CHARSET_IN_HEADER.search(content_type)
        declared = matched.group(1) if matched else None

    if declared is None:
        matched_meta = _CHARSET_IN_META.search(content[:4096])
        declared = matched_meta.group(1).decode("ascii", "ignore") if matched_meta else None

    candidates = [_normalize_charset(declared), "utf-8", "cp949"]
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return content.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue

    # 어떤 코덱으로도 완전히 읽히지 않으면 손실을 허용해서라도 본문을 반환한다.
    return content.decode("cp949", errors="replace")


class DartHttpClient:
    """공용 httpx 클라이언트로 DART 원문을 가져온다."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds

    async def fetch_html(self, url: str) -> str:
        """원문 HTML을 가져와 문자열로 반환한다.

        일시적 오류는 지수 백오프로 재시도하고, 끝까지 실패하면 예외를 던진다.

        :raises SourceFetchError: 재시도 후에도 원문을 가져오지 못한 경우
        """
        last_reason = "알 수 없는 오류"

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(url, timeout=self._timeout_seconds)
                if response.status_code >= 500:
                    last_reason = f"DART 서버 오류(HTTP {response.status_code})"
                elif response.status_code >= 400:
                    raise SourceFetchError(
                        f"원문을 가져오지 못했습니다(HTTP {response.status_code}): {url}"
                    )
                else:
                    return decode_html(response.content, response.headers.get("Content-Type"))
            except httpx.HTTPError as exc:
                last_reason = f"네트워크 오류({exc})"

            if attempt < self._max_retries:
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))

        raise SourceFetchError(f"원문을 가져오지 못했습니다({last_reason}): {url}")
