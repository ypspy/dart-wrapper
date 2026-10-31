"""회사 마스터. OpenDART 기업개황의 현재 스냅샷만 저장한다."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Corp(Base):
    """corp_code당 현재 업종·식별자 1행."""

    __tablename__ = "corps"

    corp_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    corp_name: Mapped[str | None] = mapped_column(String(255))
    stock_name: Mapped[str | None] = mapped_column(String(255))
    stock_code: Mapped[str | None] = mapped_column(String(16))
    corp_cls: Mapped[str | None] = mapped_column(String(8))
    bizr_no: Mapped[str | None] = mapped_column(String(32))
    acc_mt: Mapped[str | None] = mapped_column(String(8))
    induty_code: Mapped[str | None] = mapped_column(String(16))
    induty_name_div: Mapped[str | None] = mapped_column(String(255))
    induty_name_group: Mapped[str | None] = mapped_column(String(255))
    induty_name_class: Mapped[str | None] = mapped_column(String(255))
    induty_name_subclass: Mapped[str | None] = mapped_column(String(255))
    induty_name_item: Mapped[str | None] = mapped_column(String(255))
    fetch_status: Mapped[str] = mapped_column(String(16), nullable=False, default="api_error")
    opendart_status: Mapped[str | None] = mapped_column(String(8))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
