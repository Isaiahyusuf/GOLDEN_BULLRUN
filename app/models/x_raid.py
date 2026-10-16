from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class XRaidCampaign(Base):
    __tablename__ = "x_raid_campaigns"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    post_id: Mapped[str] = mapped_column(String(32), nullable=False)
    post_url: Mapped[str] = mapped_column(String(512), nullable=False)
    quiz_question: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    quiz_answer_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", index=True
    )
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    target_user_id: Mapped[str] = mapped_column(
        String(32), nullable=False, default="", server_default=""
    )
    target_username: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )


class XRaidClaim(Base):
    __tablename__ = "x_raid_claims"

    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("x_raid_campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        primary_key=True,
    )
    awarded_points: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    verified_actions: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
