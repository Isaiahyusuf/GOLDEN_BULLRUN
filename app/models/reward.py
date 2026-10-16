from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class WeeklyRewardPool(Base):
    __tablename__ = "weekly_reward_pools"

    week_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    balance_snapshot: Mapped[Decimal] = mapped_column(
        Numeric(30, 9), nullable=False, default=Decimal("0")
    )
    purchase_total: Mapped[Decimal] = mapped_column(
        Numeric(30, 9), nullable=False, default=Decimal("0")
    )
    team_amount: Mapped[Decimal] = mapped_column(
        Numeric(30, 9), nullable=False, default=Decimal("0")
    )
    settlement_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="reserved"
    )
    pool_amount: Mapped[Decimal] = mapped_column(
        Numeric(30, 9), nullable=False
    )
    leaderboard_snapshot: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class WeeklyRewardPayout(Base):
    __tablename__ = "weekly_reward_payouts"
    __table_args__ = (
        UniqueConstraint("week_key", "rank", name="uq_weekly_payout_rank"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    week_key: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("weekly_reward_pools.week_key"),
        nullable=False,
        index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    winner_name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(30, 9), nullable=False)
    wallet_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), default="pending_wallet", nullable=False
    )
    tx_signature: Mapped[str | None] = mapped_column(
        String(100), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
