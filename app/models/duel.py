from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class Duel(Base):
    __tablename__ = "duels"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    challenger_id: Mapped[int] = mapped_column(BigInteger, index=True)
    opponent_id: Mapped[int] = mapped_column(BigInteger, index=True)
    wager: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending")

    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    winner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    round_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    challenger_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opponent_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    challenger_choice: Mapped[str | None] = mapped_column(String(10), nullable=True)
    opponent_choice: Mapped[str | None] = mapped_column(String(10), nullable=True)

    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
