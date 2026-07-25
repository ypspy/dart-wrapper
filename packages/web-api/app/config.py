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

    # Admin 운영: 1인 운영을 전제로 공유 토큰 하나만 사용한다.
    admin_token: str = "dev-admin-token"
    # 공시 1건이 일시 오류로 실패했을 때 다시 시도하는 횟수
    disclosure_max_retries: int = 3
    # 연속 차단성 응답이 이만큼 이어지면 슬라이스를 blocked로 두고 쉬어간다.
    block_streak_threshold: int = 5
    # blocked 상태에서 재개까지 기다리는 시간(초)
    block_wait_seconds: float = 60.0
    # 히트맵에 항상 표시할 보고서 유형(쉼표 구분)
    heatmap_report_types: str = "A001,F001"

    @property
    def heatmap_report_type_list(self) -> tuple[str, ...]:
        """히트맵 고정 보고서 유형을 중복 없이 정규화한다."""
        return tuple(
            dict.fromkeys(
                item.strip().upper()
                for item in self.heatmap_report_types.split(",")
                if item.strip()
            )
        )


@lru_cache
def get_settings() -> Settings:
    """설정 객체를 캐시해 반환한다."""
    return Settings()
