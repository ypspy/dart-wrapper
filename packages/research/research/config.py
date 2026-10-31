"""연구 패키지 설정. OpenDART·날짜 LLM 값만 다루고, DB·DART 수집 값은 web-api `Settings`를 쓴다."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ResearchSettings(BaseSettings):
    """OpenDART 기업개황과 날짜 LLM 해소에 쓰는 환경변수 설정."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    opendart_api_key: str = ""
    opendart_api_key_2: str = ""
    opendart_concurrency: int = 2
    opendart_timeout_seconds: float = 15.0
    opendart_max_retries: int = 2
    # TCP 차단을 피하려고 분당 1,000보다 여유 있게 200으로 둔다.
    opendart_max_per_minute: int = 200

    # ambiguous 감사보고서일 LLM 해소. 키가 비어 있으면 잡을 시작하지 않는다.
    date_resolver_api_key: str = ""
    date_resolver_model: str = "gpt-4o-mini"
    date_resolver_prompt_version: str = "v1"

    # 골드 검수. 카탈로그와 다른 파일이고, 기본 앱은 이 경로를 만들지 않는다.
    gold_db_path: str = "C:/dev/dart-wrapper/data/gold/gold.db"
    gold_cache_root: str = "C:/dev/dart-wrapper/data/gold_cache"
    gold_run_id: str = "gold-2026-10"

    @property
    def opendart_api_keys(self) -> tuple[str, ...]:
        """OpenDART 인증키를 우선순위대로 모은다. 한도가 차면 다음 키를 쓴다."""
        return parse_opendart_api_keys(self.opendart_api_key, self.opendart_api_key_2)


def parse_opendart_api_keys(*raw: str) -> tuple[str, ...]:
    """쉼표·세미콜론으로 나눈 키를 중복 없이 순서대로 반환한다."""
    keys: list[str] = []
    for blob in raw:
        for item in blob.replace(";", ",").split(","):
            key = item.strip()
            if key and key not in keys:
                keys.append(key)
    return tuple(keys)


@lru_cache
def get_research_settings() -> ResearchSettings:
    """연구 설정 객체를 캐시해 반환한다."""
    return ResearchSettings()
