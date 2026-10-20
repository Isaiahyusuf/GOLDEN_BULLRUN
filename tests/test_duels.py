import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import SessionLocal, engine, init_db
from app.models.daily_reward import DailyActivity
from app.models.duel import Duel
from app.models.group import TelegramGroup
from app.models.transaction import PointTransaction
from app.models.user import User
from app.handlers.duels import challenge_text
from app.services.duel_service import (
    DuelError,
    accept_duel,
    create_duel,
    decline_duel,
    expire_stale_duels,
    submit_move,
)
from app.handlers.duels import start_duel

GROUP_ID = -1001234567890
CHALLENGER_ID = 990001001
OPPONENT_ID = 990001002


def test_pvp_is_the_only_duel_command():
    async def run():
        bot = Bot(token="123456:ABC")
        try:
            parsed = await Command("pvp").parse_command(
                "/pvp @player 100",
                bot,
            )
            assert parsed.command.startswith("pvp")
        finally:
            await bot.session.close()

    asyncio.run(run())


def test_challenge_post_displays_assigned_duel_number():
    text = challenge_text(42, "@challenger", "@opponent", 500)

    assert "BATTLE #42" in text
    assert "Challenger: @challenger" in text
    assert "Opponent: @opponent" in text
    assert "Stake: 500 Bullrun Points each" in text


def test_unregistered_opponent_gets_start_registration_button():
    async def run():
        session = AsyncMock()
        session.scalar.return_value = None
        session_context = MagicMock()
        session_context.__aenter__ = AsyncMock(return_value=session)
        session_context.__aexit__ = AsyncMock(return_value=False)
        message = MagicMock()
        message.chat.type = ChatType.GROUP
        message.chat.id = GROUP_ID
        message.from_user.id = CHALLENGER_ID
        message.from_user.is_bot = False
        message.text = "/pvp @newplayer 100"
        message.answer = AsyncMock()

        with patch(
            "app.handlers.duels.SessionLocal",
            return_value=session_context,
        ):
            await start_duel(message, MagicMock())

        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        keyboard = message.answer.await_args.kwargs["reply_markup"]
        button = keyboard.inline_keyboard[0][0]
        assert "tap Start below to register" in text
        assert button.text == "🚀 TAP START TO REGISTER"
        assert button.url == "https://t.me/Trumpty_dumptybot?start=register"

    asyncio.run(run())


def test_stale_username_cannot_challenge_a_different_group_member():
    async def run():
        session = AsyncMock()
        session.scalar.return_value = SimpleNamespace(
            telegram_id=OPPONENT_ID,
            username="oldplayer",
            full_name="Registered Player",
            is_bot=False,
        )
        session_context = MagicMock()
        session_context.__aenter__ = AsyncMock(return_value=session)
        session_context.__aexit__ = AsyncMock(return_value=False)
        message = MagicMock()
        message.chat.type = ChatType.GROUP
        message.chat.id = GROUP_ID
        message.from_user.id = CHALLENGER_ID
        message.from_user.is_bot = False
        message.from_user.username = "challenger"
        message.from_user.full_name = "Challenger"
        message.text = "/pvp @oldplayer 100"
        message.answer = AsyncMock()
        bot = MagicMock()
        bot.get_chat_member = AsyncMock(
            return_value=SimpleNamespace(
                status=ChatMemberStatus.MEMBER,
                user=SimpleNamespace(
                    username="newplayer",
                    is_bot=False,
                ),
            )
        )

        with patch(
            "app.handlers.duels.SessionLocal",
            return_value=session_context,
        ):
            await start_duel(message, bot)

        message.answer.assert_awaited_once()
        assert "couldn't verify that username" in (
            message.answer.await_args.args[0]
        )
        assert message.answer.await_args.kwargs["reply_markup"].inline_keyboard

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
            group_statement = insert(TelegramGroup).values(
                chat_id=GROUP_ID,
                title="PvP test group",
                active=True,
            )
            await session.execute(
                group_statement.on_conflict_do_update(
                    index_elements=[TelegramGroup.chat_id],
                    set_={"active": True},
                )
            )
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


def test_duels_can_start_in_any_registered_group():
    other_group_id = -1009876543210

    async def run():
        await reset_players()
        async with SessionLocal() as session:
            async with session.begin():
                statement = insert(TelegramGroup).values(
                    chat_id=other_group_id,
                    title="Second PvP test group",
                    active=True,
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[TelegramGroup.chat_id],
                        set_={"active": True},
                    )
                )
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


def test_challenge_decline_is_limited_to_opponent_and_does_not_charge_points():
    async def run():
        await reset_players()
        duel_id = await create_duel(
            CHALLENGER_ID, OPPONENT_ID, 1_000, GROUP_ID
        )

        with pytest.raises(DuelError, match="Only the challenged Bull"):
            await decline_duel(duel_id, CHALLENGER_ID, GROUP_ID)

        result = await decline_duel(duel_id, OPPONENT_ID, GROUP_ID)
        assert result["status"] == "declined"
        async with SessionLocal() as session:
            duel = await session.get(Duel, duel_id)
            a = await session.get(User, CHALLENGER_ID)
            b = await session.get(User, OPPONENT_ID)
            assert duel.status == "declined"
            assert a.points == 10_000
            assert b.points == 10_000

    run_async(run())


def test_only_opponent_can_accept_and_challenger_stake_is_not_reserved_early():
    async def run():
        await reset_players()
        duel_id = await create_duel(
            CHALLENGER_ID, OPPONENT_ID, 1_000, GROUP_ID
        )

        with pytest.raises(DuelError, match="Only the challenged Bull"):
            await accept_duel(duel_id, CHALLENGER_ID, GROUP_ID)

        async with SessionLocal() as session:
            duel = await session.get(Duel, duel_id)
            a = await session.get(User, CHALLENGER_ID)
            b = await session.get(User, OPPONENT_ID)
            assert duel.status == "pending"
            assert a.points == 10_000
            assert b.points == 10_000

    run_async(run())


def test_accepting_expired_challenge_marks_it_expired_without_reserving_stakes():
    async def run():
        await reset_players()
        duel_id = await create_duel(
            CHALLENGER_ID, OPPONENT_ID, 1_000, GROUP_ID
        )
        async with SessionLocal() as session:
            async with session.begin():
                duel = await session.get(Duel, duel_id)
                duel.created_at = datetime.now(timezone.utc) - timedelta(
                    seconds=61
                )

        with pytest.raises(DuelError, match="challenge has expired"):
            await accept_duel(duel_id, OPPONENT_ID, GROUP_ID)

        async with SessionLocal() as session:
            duel = await session.get(Duel, duel_id)
            a = await session.get(User, CHALLENGER_ID)
            b = await session.get(User, OPPONENT_ID)
            assert duel.status == "expired"
            assert a.points == 10_000
            assert b.points == 10_000

    run_async(run())


def test_active_challenge_blocks_duplicate_or_overlapping_challenges():
    async def run():
        await reset_players()
        await create_duel(CHALLENGER_ID, OPPONENT_ID, 100, GROUP_ID)

        with pytest.raises(DuelError, match="already has an active"):
            await create_duel(OPPONENT_ID, CHALLENGER_ID, 100, GROUP_ID)

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

        with pytest.raises(DuelError, match="enough Bullrun Points for that wager"):
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
        with patch(
            "app.services.duel_service.secrets.choice",
            return_value=CHALLENGER_ID,
        ):
            await accept_duel(duel_id, OPPONENT_ID, GROUP_ID)

        result = await submit_move(
            duel_id,
            CHALLENGER_ID,
            GROUP_ID,
            1,
            "attack",
        )
        assert result["status"] == "next_turn"

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
                duel.created_at = datetime.now(timezone.utc) - timedelta(seconds=61)

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
