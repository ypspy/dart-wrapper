"""OpenDART 기업개황(company.json) 클라이언트."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

COMPANY_URL = "https://opendart.fss.or.kr/api/company.json"


class OpenDartHttpError(Exception):
    """재시도 후에도 기업개황 HTTP가 실패한 경우."""


@dataclass(frozen=True)
class CompanyOverview:
    """기업개황 한 건. API status는 원문 코드."""

    status: str
    message: str
    corp_name: str | None = None
    stock_name: str | None = None
    stock_code: str | None = None
    corp_cls: str | None = None
    bizr_no: str | None = None
    acc_mt: str | None = None
    induty_code: str | None = None


def _blank_to_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _field(payload: dict[str, object], result: dict[str, object] | None, key: str) -> object:
    """개황 필드는 최상위를 우선하고, 없으면 result에서 읽는다."""
    if key in payload:
        return payload[key]
    if result is not None and key in result:
        return result[key]
    return None


def parse_company_payload(payload: dict[str, object]) -> CompanyOverview:
    """최상위 또는 result 아래 status·필드를 정규화한다."""
    nested = payload.get("result")
    result = nested if isinstance(nested, dict) else None
    status = str(payload.get("status") or (result or {}).get("status") or "")
    message = str(payload.get("message") or (result or {}).get("message") or "")
    return CompanyOverview(
        status=status,
        message=message,
        corp_name=_blank_to_none(_field(payload, result, "corp_name")),
        stock_name=_blank_to_none(_field(payload, result, "stock_name")),
        stock_code=_blank_to_none(_field(payload, result, "stock_code")),
        corp_cls=_blank_to_none(_field(payload, result, "corp_cls")),
        bizr_no=_blank_to_none(_field(payload, result, "bizr_no")),
        acc_mt=_blank_to_none(_field(payload, result, "acc_mt")),
        induty_code=_blank_to_none(_field(payload, result, "induty_code")),
    )


class OpenDartCompanyClient:
    """인증키와 고유번호로 기업개황 JSON을 가져온다."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds

    async def fetch(self, corp_code: str, api_key: str) -> CompanyOverview:
        """company.json 1건. HTTP 실패만 재시도한다."""
        last_reason = "알 수 없는 오류"
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(
                    COMPANY_URL,
                    params={"crtfc_key": api_key, "corp_code": corp_code},
                    timeout=self._timeout_seconds,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                if isinstance(exc, httpx.HTTPStatusError):
                    last_reason = (
                        f"HTTP {exc.response.status_code} "
                        f"({exc.__class__.__name__})"
                    )
                else:
                    last_reason = exc.__class__.__name__
                if attempt >= self._max_retries:
                    break
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
                continue
            try:
                payload = response.json()
            except ValueError as exc:
                raise OpenDartHttpError("기업개황 JSON 파싱에 실패했습니다.") from exc
            if not isinstance(payload, dict):
                raise OpenDartHttpError("기업개황 응답이 객체가 아닙니다.")
            return parse_company_payload(payload)
        raise OpenDartHttpError(
            f"기업개황을 가져오지 못했습니다({corp_code}): {last_reason}"
        )
