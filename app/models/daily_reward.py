from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class DailyActivity(Base):
    __tablename__ = "daily_activities"

    day_key: Mapped[date] = mapped_column(Date, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    completed_duels: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    scored_duels: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    scored_duel_wins: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    first_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DailyRewardSettlement(Base):
    __tablename__ = "daily_reward_settlements"

    day_key: Mapped[date] = mapped_column(Date, primary_key=True)
    winners: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    settled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
