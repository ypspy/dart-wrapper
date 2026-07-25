"""애플리케이션 설정. 환경변수 또는 .env로 주입한다."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# packages/web-api/app/config.py → 모노레포 루트
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COLLECTOR_SCRIPT = REPO_ROOT / "packages" / "entry-extractor" / "bin" / "collect-entries.js"


class Settings(BaseSettings):
    """환경변수 기반 설정값.

    개발 환경은 SQLite, 웹 배포는 PostgreSQL(Neon)을 사용한다.
    DATABASE_URL만 교체하면 코드 변경 없이 전환된다.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./dart_catalog.db"
    node_executable: str = "node"
    entry_collector_script: Path = DEFAULT_COLLECTOR_SCRIPT
    collector_timeout_seconds: int = 900
    dart_fetch_concurrency: int = 4
    dart_fetch_timeout_seconds: float = 15.0
    dart_fetch_max_retries: int = 2


@lru_cache
def get_settings() -> Settings:
    """설정 객체를 캐시해 반환한다."""
    return Settings()
