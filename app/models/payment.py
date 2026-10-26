from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    package_id: Mapped[str] = mapped_column(String(24))
    purchase_reference: Mapped[str] = mapped_column(
        String(36), unique=True, default=lambda: str(uuid4()), nullable=False
    )
    token_mint: Mapped[str] = mapped_column(String(64))
    recipient: Mapped[str] = mapped_column(String(64))
    buyer_wallet: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    token_amount: Mapped[Decimal] = mapped_column(Numeric(30, 9))
    credits: Mapped[int] = mapped_column(Integer)
    signature: Mapped[str | None] = mapped_column(
        String(100), unique=True, index=True, nullable=True
    )
    verification_signature: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(24), default="pending", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    credited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
