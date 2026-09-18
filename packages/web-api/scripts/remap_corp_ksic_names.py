"""저장된 회사 업종코드에 KSIC 이름을 다시 붙인다. OpenDART는 호출하지 않는다."""

from __future__ import annotations

import argparse
import asyncio

from app.config import Settings
from app.db.session import create_db_engine, create_sessionmaker
from app.ksic import load_ksic_tables
from app.services.corp_industry_service import CorpIndustryService


class _UnusedClient:
    """이름 재매핑은 HTTP를 쓰지 않는다."""

    async def fetch(self, corp_code: str, api_key: str) -> None:
        raise RuntimeError("이름 재매핑은 OpenDART를 호출하지 않습니다.")


def build_parser() -> argparse.ArgumentParser:
    """DB URL만 받는다."""
    parser = argparse.ArgumentParser(
        description="corps의 업종 이름을 로컬 KSIC 표로 다시 채웁니다. OpenDART는 치지 않습니다."
    )
    parser.add_argument(
        "--database-url",
        default=Settings().database_url,
        help="SQLAlchemy DB URL. 기본값은 앱 Settings와 같습니다.",
    )
    return parser


async def _run(database_url: str) -> tuple[int, int]:
    """세션을 열고 이름만 다시 붙인다."""
    engine = create_db_engine(database_url)
    sessionmaker = create_sessionmaker(engine)
    try:
        service = CorpIndustryService(
            sessionmaker,
            _UnusedClient(),  # type: ignore[arg-type]
            load_ksic_tables(),
            api_keys=("local-remap",),
        )
        return await service.remap_ksic_names()
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    """CLI 진입점."""
    args = build_parser().parse_args(argv)
    updated, unmatched = asyncio.run(_run(args.database_url))
    print(f"이름을 채운 회사 {updated}건, 표에 없는 코드 {unmatched}건.")


if __name__ == "__main__":
    main()
