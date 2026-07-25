"""entries로부터 disclosures를 일회성으로 채운다."""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.db.session import create_all, create_db_engine, create_sessionmaker
from app.repositories.disclosure_repository import DisclosureRepository


async def main() -> None:
    """DATABASE_URL의 entries를 집계해 disclosures에 upsert한다."""
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        count = await DisclosureRepository(session).backfill_from_entries()
        await session.commit()
    await engine.dispose()
    print(f"disclosures upsert {count}건 완료")


if __name__ == "__main__":
    asyncio.run(main())
