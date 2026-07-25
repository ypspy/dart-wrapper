"""SQLAlchemy 선언적 베이스."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """모든 모델의 공통 베이스."""
