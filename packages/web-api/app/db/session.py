"""비동기 DB 엔진·세션 팩토리. SQLite와 PostgreSQL을 함께 지원한다."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import Base


def create_db_engine(database_url: str) -> AsyncEngine:
    """DATABASE_URL로 비동기 엔진을 만든다."""
    return create_async_engine(database_url, future=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """요청 단위 세션을 만드는 세션메이커를 반환한다."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def create_all(engine: AsyncEngine) -> None:
    """모델 정의를 기준으로 테이블을 생성한다(뼈대 단계용)."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
