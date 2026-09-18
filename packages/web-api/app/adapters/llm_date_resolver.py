"""OpenAI Chat Completions로 감사보고서일 인덱스를 고르는 어댑터."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_CHAT_URL = "https://api.openai.com/v1/chat/completions"
# 공유 httpx 클라이언트 기본 타임아웃(5초)보다 길다. DART fetch는 요청마다 15초.
_LLM_TIMEOUT_SECONDS = 30.0
_PROMPTS: dict[str, str] = {
    "v1": (
        "당신은 감사보고서일 후보 중 실제 서명일(감사보고서일)을 고릅니다. "
        "JSON만 답하세요. 형식은 {\"index\": n} 또는 {\"index\": null} 입니다. "
        "새 날짜를 만들지 마세요. 고를 수 없으면 null 을 주세요. "
        "결산일(period_end)과 인증일(auth_date)은 참고만 하세요."
    ),
}


class LlmDateResolver:
    """LLM HTTP 응답에서 index JSON만 파싱한다. 실패·범위 밖은 None."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        prompt_version: str = "v1",
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._model = model
        self._prompt_version = prompt_version
        self.last_raw_response: str | None = None

    async def pick_index(
        self,
        *,
        candidates: list[dict],
        period_end: str,
        auth_date: str,
    ) -> int | None:
        """Chat Completions를 호출하고 index만 반환한다. 오류 시 None."""
        self.last_raw_response = None
        try:
            response = await self._client.post(
                _CHAT_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=self._payload(candidates, period_end, auth_date),
                timeout=_LLM_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except Exception:
            logger.exception("날짜 LLM 호출에 실패했습니다.")
            return None

        if not isinstance(content, str):
            return None
        self.last_raw_response = content
        return _parse_index(content, len(candidates))

    def _payload(
        self,
        candidates: list[dict],
        period_end: str,
        auth_date: str,
    ) -> dict[str, Any]:
        """temperature 0 JSON 요청 본문을 만든다."""
        system = _PROMPTS.get(self._prompt_version, _PROMPTS["v1"])
        user = json.dumps(
            {
                "period_end": period_end,
                "auth_date": auth_date,
                "candidates": candidates,
            },
            ensure_ascii=False,
        )
        return {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }


def _parse_index(raw: str, count: int) -> int | None:
    """{"index": n} 또는 {"index": null}만 허용한다. 그 외는 None."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or "index" not in payload:
        return None
    value = payload["index"]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value >= count:
        return None
    return value
