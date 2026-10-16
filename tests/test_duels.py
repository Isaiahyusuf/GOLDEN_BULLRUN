import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from aiogram import Bot
from aiogram.filters import Command
from sqlalchemy import delete

from app.database.connection import SessionLocal, engine, init_db
from app.models.daily_reward import DailyActivity
from app.models.duel import Duel
from app.models.transaction import PointTransaction
from app.models.user import User
from app.services.duel_service import (
    DuelError,
    accept_duel,
    create_duel,
    expire_stale_duels,
    submit_choice,
)

GROUP_ID = -1001234567890
CHALLENGER_ID = 990001001
OPPONENT_ID = 990001002


def test_pvp_and_duel_commands_are_both_accepted():
    async def run():
        bot = Bot(token="123456:ABC")
        try:
            command_filter = Command("pvp", "duel")
            pvp = await command_filter.parse_command("/pvp @player 100", bot)
            duel = await command_filter.parse_command("/duel @player 100", bot)
            assert pvp.command.startswith("pvp")
            assert duel.command.startswith("duel")
        finally:
            await bot.session.close()

    asyncio.run(run())


def run_async(coro):
    async def runner():
        try:
            await coro
        finally:
            await engine.dispose()

    asyncio.run(runner())


async def reset_players():
    await init_db()
    ids = [CHALLENGER_ID, OPPONENT_ID]

    async with SessionLocal() as session:
        async with session.begin():
            await session.execute(
                delete(DailyActivity).where(
                    DailyActivity.telegram_id.in_(ids)
                )
            )
            await session.execute(
                delete(PointTransaction).where(
                    PointTransaction.telegram_id.in_(ids)
                )
            )
            await session.execute(
                delete(Duel).where(
                    (Duel.challenger_id.in_(ids))
                    | (Duel.opponent_id.in_(ids))
                )
            )
            await session.execute(
                delete(User).where(User.telegram_id.in_(ids))
            )
            session.add_all([
                User(
                    telegram_id=CHALLENGER_ID,
                    full_name="Test Challenger",
                    points=10_000,
                ),
                User(
                    telegram_id=OPPONENT_ID,
                    full_name="Test Opponent",
                    points=10_000,
                ),
                PointTransaction(
                    telegram_id=CHALLENGER_ID,
                    amount=10_000,
                    reason="welcome_bonus",
                ),
                PointTransaction(
                    telegram_id=OPPONENT_ID,
                    amount=10_000,
                    reason="welcome_bonus",
                ),
            ])


def test_duels_can_start_in_any_group_without_a_group_id_setting():
    other_group_id = -1009876543210

    async def run():
        await reset_players()
        duel_id = await create_duel(
            CHALLENGER_ID,
            OPPONENT_ID,
            500,
            other_group_id,
        )
        async with SessionLocal() as session:
            duel = await session.get(Duel, duel_id)
            assert duel.chat_id == other_group_id

    run_async(run())


def test_abandoned_accepted_duel_refunds_once():
    async def run():
        await reset_players()

        duel_id = await create_duel(
            CHALLENGER_ID, OPPONENT_ID, 1_000, GROUP_ID
        )
        result = await accept_duel(duel_id, OPPONENT_ID, GROUP_ID)
        assert result["status"] == "accepted"

        async with SessionLocal() as session:
            async with session.begin():
                duel = await session.get(Duel, duel_id)
                old_activity = datetime.now(timezone.utc) - timedelta(
                    minutes=16
                )
                duel.accepted_at = old_activity
                duel.last_activity_at = old_activity

        async with SessionLocal() as session:
            a = await session.get(User, CHALLENGER_ID)
            b = await session.get(User, OPPONENT_ID)
            assert a.points == 9_000
            assert b.points == 9_000

        expired = await expire_stale_duels()
        assert len(expired) == 1
        assert expired[0]["duel_id"] == duel_id
        assert expired[0]["refunded"] is True

        async with SessionLocal() as session:
            a = await session.get(User, CHALLENGER_ID)
            b = await session.get(User, OPPONENT_ID)
            duel = await session.get(Duel, duel_id)
            assert a.points == 10_000
            assert b.points == 10_000
            assert duel.status == "expired"
            assert duel.settled_at is not None

        assert await expire_stale_duels() == []

        async with SessionLocal() as session:
            a = await session.get(User, CHALLENGER_ID)
            b = await session.get(User, OPPONENT_ID)
            assert a.points == 10_000
            assert b.points == 10_000

        with pytest.raises(DuelError, match="enough points for that wager"):
            await create_duel(
                CHALLENGER_ID, OPPONENT_ID, 20_000, GROUP_ID
            )

    run_async(run())


def test_recent_move_prevents_accepted_duel_expiry():
    async def run():
        await reset_players()

        duel_id = await create_duel(
            CHALLENGER_ID, OPPONENT_ID, 1_000, GROUP_ID
        )
        await accept_duel(duel_id, OPPONENT_ID, GROUP_ID)

        result = await submit_choice(
            duel_id, CHALLENGER_ID, "attack", GROUP_ID, 1
        )
        assert result["status"] == "waiting"

        async with SessionLocal() as session:
            async with session.begin():
                duel = await session.get(Duel, duel_id)
                duel.accepted_at = (
                    datetime.now(timezone.utc) - timedelta(minutes=20)
                )

        assert await expire_stale_duels() == []

        async with SessionLocal() as session:
            duel = await session.get(Duel, duel_id)
            a = await session.get(User, CHALLENGER_ID)
            b = await session.get(User, OPPONENT_ID)

            assert duel.status == "accepted"
            assert duel.last_activity_at is not None
            assert a.points == 9_000
            assert b.points == 9_000

    run_async(run())


def test_pending_challenge_expires_without_deducting_points():
    async def run():
        await reset_players()

        duel_id = await create_duel(
            CHALLENGER_ID, OPPONENT_ID, 1_000, GROUP_ID
        )

        async with SessionLocal() as session:
            async with session.begin():
                duel = await session.get(Duel, duel_id)
                duel.created_at = datetime.now(timezone.utc) - timedelta(
                    minutes=6
                )

        expired = await expire_stale_duels()
        assert len(expired) == 1
        assert expired[0]["refunded"] is False

        async with SessionLocal() as session:
            a = await session.get(User, CHALLENGER_ID)
            b = await session.get(User, OPPONENT_ID)
            duel = await session.get(Duel, duel_id)
            assert a.points == 10_000
            assert b.points == 10_000
            assert duel.status == "expired"

    run_async(run())
