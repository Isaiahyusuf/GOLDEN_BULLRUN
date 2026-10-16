import os

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


def normalize_database_url(value):
    if value is None:
        return "postgresql+asyncpg://localhost/trumpty_royale"

    value = str(value).strip()
    if not value:
        return "postgresql+asyncpg://localhost/trumpty_royale"

    url = make_url(value)
    drivername = url.drivername.lower()

    if drivername in {"postgres", "postgresql"} or drivername.startswith("postgresql+"):
        url = url.set(drivername="postgresql+asyncpg")

    return url.render_as_string(hide_password=False)


DATABASE_URL = normalize_database_url(
    os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://localhost/trumpty_royale",
    )
)

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    from app.models.user import User
    from app.models.transaction import PointTransaction
    from app.models.duel import Duel
    from app.models.weekly_reset import WeeklyReset
    from app.models.payment import Payment
    from app.models.group import TelegramGroup
    from app.models.reward import WeeklyRewardPool, WeeklyRewardPayout

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
            "purchased_credits INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS "
            "purchase_reference VARCHAR(36)"
        ))
        await conn.execute(text(
            "UPDATE payments SET purchase_reference = "
            "md5(random()::text || clock_timestamp()::text || id::text) "
            "WHERE purchase_reference IS NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE payments ALTER COLUMN purchase_reference SET NOT NULL"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "ix_payments_purchase_reference ON payments (purchase_reference)"
        ))
        await conn.execute(text(
            "ALTER TABLE payments ALTER COLUMN signature DROP NOT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS "
            "received_at TIMESTAMP WITH TIME ZONE"
        ))
        await conn.execute(text(
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS "
            "buyer_wallet VARCHAR(64)"
        ))
        await conn.execute(text(
            "ALTER TABLE weekly_reward_pools "
            "ADD COLUMN IF NOT EXISTS purchase_total "
            "NUMERIC(30, 9) NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE weekly_reward_pools "
            "ADD COLUMN IF NOT EXISTS team_amount "
            "NUMERIC(30, 9) NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE weekly_reward_pools "
            "ADD COLUMN IF NOT EXISTS settlement_status "
            "VARCHAR(24) NOT NULL DEFAULT 'reserved'"
        ))
        await conn.execute(text(
            "ALTER TABLE weekly_reward_pools "
            "ADD COLUMN IF NOT EXISTS leaderboard_snapshot "
            "JSON NOT NULL DEFAULT '[]'::json"
        ))
