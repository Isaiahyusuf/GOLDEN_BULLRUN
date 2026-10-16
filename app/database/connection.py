import asyncio
import logging
import os

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


DATABASE_CONNECT_ATTEMPTS = 5
DATABASE_RETRY_DELAY_SECONDS = 1


class DatabaseConnectionError(RuntimeError):
    pass


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


async def _initialize_schema():
    from app.models.user import User
    from app.models.transaction import PointTransaction
    from app.models.duel import Duel
    from app.models.weekly_reset import WeeklyReset
    from app.models.payment import Payment
    from app.models.group import TelegramGroup
    from app.models.reward import WeeklyRewardPool, WeeklyRewardPayout
    from app.models.daily_reward import DailyActivity, DailyRewardSettlement
    from app.models.x_raid import XRaidCampaign, XRaidClaim

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
            "protection_rank INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "UPDATE users SET protection_rank = 5 "
            "WHERE protection_rank = 0 "
            "AND protection_expires_at > CURRENT_TIMESTAMP"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
            "purchased_credits INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
            "is_bot BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE telegram_groups ADD COLUMN IF NOT EXISTS "
            "play_post_message_id BIGINT"
        ))
        await conn.execute(text(
            "ALTER TABLE duels ADD COLUMN IF NOT EXISTS "
            "turn_player_id BIGINT"
        ))
        await conn.execute(text(
            "ALTER TABLE duels ADD COLUMN IF NOT EXISTS "
            "challenger_health INTEGER NOT NULL DEFAULT 100"
        ))
        await conn.execute(text(
            "ALTER TABLE duels ADD COLUMN IF NOT EXISTS "
            "opponent_health INTEGER NOT NULL DEFAULT 100"
        ))
        await conn.execute(text(
            "ALTER TABLE duels ADD COLUMN IF NOT EXISTS "
            "challenger_guard_active BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE duels ADD COLUMN IF NOT EXISTS "
            "opponent_guard_active BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE duels ADD COLUMN IF NOT EXISTS "
            "challenger_guard_used BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE duels ADD COLUMN IF NOT EXISTS "
            "opponent_guard_used BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "UPDATE duels SET turn_player_id = challenger_id "
            "WHERE status = 'accepted' AND turn_player_id IS NULL"
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
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "ix_x_raid_campaigns_one_active ON x_raid_campaigns (active) "
            "WHERE active"
        ))
        await conn.execute(text(
            "ALTER TABLE x_raid_campaigns ADD COLUMN IF NOT EXISTS "
            "quiz_question TEXT NOT NULL DEFAULT ''"
        ))
        await conn.execute(text(
            "ALTER TABLE x_raid_campaigns ADD COLUMN IF NOT EXISTS "
            "quiz_answer_hash VARCHAR(64) NOT NULL DEFAULT ''"
        ))
        await conn.execute(text(
            "ALTER TABLE x_raid_claims ADD COLUMN IF NOT EXISTS "
            "attempts INTEGER NOT NULL DEFAULT 0"
        ))


async def init_db():
    for attempt in range(1, DATABASE_CONNECT_ATTEMPTS + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            break
        except OperationalError as exc:
            if attempt == DATABASE_CONNECT_ATTEMPTS:
                raise DatabaseConnectionError(
                    "Could not connect to PostgreSQL after "
                    f"{DATABASE_CONNECT_ATTEMPTS} attempts."
                ) from exc

            delay = DATABASE_RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
            logging.warning(
                "PostgreSQL is not ready (attempt %s/%s); retrying in %s seconds.",
                attempt,
                DATABASE_CONNECT_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)

    await _initialize_schema()
