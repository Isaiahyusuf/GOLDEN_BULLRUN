from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class TelegramGroup(Base):
    __tablename__ = "telegram_groups"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    announcements_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    play_post_message_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    protection_reminder_week: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
