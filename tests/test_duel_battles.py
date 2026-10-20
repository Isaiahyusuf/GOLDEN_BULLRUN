import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import SessionLocal, engine, init_db
from app.models.daily_reward import DailyActivity
from app.models.duel import Duel
from app.models.group import TelegramGroup
from app.models.transaction import PointTransaction
from app.models.user import User
from app.services.duel_service import (
    DuelError,
    accept_duel,
    create_duel,
    expire_stale_duels,
    forfeit_duel,
    submit_move,
)


GROUP_ID = -1001234567890
PLAYER_A = 990002001
PLAYER_B = 990002002
OUTSIDER = 990002999


async def reset_players():
    await init_db()
    ids = [PLAYER_A, PLAYER_B, OUTSIDER]

    async with SessionLocal() as session:
        async with session.begin():
            group_statement = insert(TelegramGroup).values(
                chat_id=GROUP_ID,
                title="Battle test group",
                active=True,
            )
            await session.execute(
                group_statement.on_conflict_do_update(
                    index_elements=[TelegramGroup.chat_id],
                    set_={"active": True},
                )
            )
            await session.execute(
                delete(DailyActivity).where(DailyActivity.telegram_id.in_(ids))
            )
            await session.execute(
                delete(PointTransaction).where(
                    PointTransaction.telegram_id.in_(ids)
                )
            )
            await session.execute(
                delete(Duel).where(
                    Duel.challenger_id.in_(ids) | Duel.opponent_id.in_(ids)
                )
            )
            await session.execute(delete(User).where(User.telegram_id.in_(ids)))
            session.add_all([
                User(telegram_id=PLAYER_A, full_name="Player A", points=10_000),
                User(telegram_id=PLAYER_B, full_name="Player B", points=10_000),
                User(telegram_id=OUTSIDER, full_name="Outsider", points=10_000),
                PointTransaction(
                    telegram_id=PLAYER_A,
                    amount=10_000,
                    reason="welcome_bonus",
                ),
                PointTransaction(
                    telegram_id=PLAYER_B,
                    amount=10_000,
                    reason="welcome_bonus",
                ),
                PointTransaction(
                    telegram_id=OUTSIDER,
                    amount=10_000,
                    reason="welcome_bonus",
                ),
            ])


async def new_accepted_duel():
    duel_id = await create_duel(PLAYER_A, PLAYER_B, 1_000, GROUP_ID)
    with patch(
        "app.services.duel_service.secrets.choice",
        return_value=PLAYER_A,
    ):
        result = await accept_duel(duel_id, PLAYER_B, GROUP_ID)
    assert result["turn_player_id"] == PLAYER_A
    assert result["challenger_health"] == 100
    assert result["opponent_health"] == 100
    return duel_id


def run_async(coro):
    async def runner():
        try:
            await coro
        finally:
            await engine.dispose()

    asyncio.run(runner())


def test_alternating_attacks_end_at_zero_and_settle_wager_once():
    async def run():
        await reset_players()
        duel_id = await new_accepted_duel()

        first = await submit_move(
            duel_id, PLAYER_A, GROUP_ID, 1, "attack"
        )
        assert first == {
            "status": "next_turn",
            "turn": 2,
            "turn_player_id": PLAYER_B,
            "attacker_id": PLAYER_A,
            "target_id": PLAYER_B,
            "action": "attack",
            "damage": 20,
            "health": {PLAYER_A: 100, PLAYER_B: 80},
        }

        with pytest.raises(DuelError, match="not your turn"):
            await submit_move(duel_id, PLAYER_A, GROUP_ID, 2, "attack")
        with pytest.raises(DuelError, match="expired"):
            await submit_move(duel_id, PLAYER_B, GROUP_ID, 1, "attack")
        with pytest.raises(DuelError, match="Only duel participants"):
            await submit_move(duel_id, OUTSIDER, GROUP_ID, 2, "attack")

        result = None
        for turn_number, player_id in enumerate(
            (PLAYER_B, PLAYER_A, PLAYER_B, PLAYER_A,
             PLAYER_B, PLAYER_A, PLAYER_B, PLAYER_A),
            start=2,
        ):
            result = await submit_move(
                duel_id,
                player_id,
                GROUP_ID,
                turn_number,
                "attack",
            )

        assert result is not None
        assert result["status"] == "settled"
        assert result["winner_id"] == PLAYER_A
        assert result["prize"] == 2_000
        assert result["health"] == {PLAYER_A: 20, PLAYER_B: 0}
        assert result["activity_points"] == {
            PLAYER_A: 75,
            PLAYER_B: 25,
        }

        with pytest.raises(DuelError, match="not accepting moves"):
            await submit_move(duel_id, PLAYER_B, GROUP_ID, 10, "attack")

        async with SessionLocal() as session:
            a = await session.get(User, PLAYER_A)
            b = await session.get(User, PLAYER_B)
            duel = await session.get(Duel, duel_id)
            assert a.points == 11_075
            assert b.points == 9_025
            assert duel.status == "settled"
            assert duel.winner_id == PLAYER_A

    run_async(run())


def test_first_turn_is_selected_for_either_player():
    async def run():
        await reset_players()
        duel_id = await create_duel(PLAYER_A, PLAYER_B, 1_000, GROUP_ID)

        with patch(
            "app.services.duel_service.secrets.choice",
            return_value=PLAYER_B,
        ):
            result = await accept_duel(duel_id, PLAYER_B, GROUP_ID)

        assert result["turn_player_id"] == PLAYER_B
        async with SessionLocal() as session:
            duel = await session.get(Duel, duel_id)
            assert duel.turn_player_id == PLAYER_B

    run_async(run())


def test_guard_reduces_the_next_hit_and_can_only_be_used_once():
    async def run():
        await reset_players()
        duel_id = await new_accepted_duel()

        guarded = await submit_move(duel_id, PLAYER_A, GROUP_ID, 1, "guard")
        assert guarded["status"] == "next_turn"
        assert guarded["action"] == "guard"
        assert guarded["damage"] == 0
        assert guarded["turn_player_id"] == PLAYER_B

        result = await submit_move(
            duel_id, PLAYER_B, GROUP_ID, 2, "attack"
        )
        assert result["damage"] == 10
        assert result["health"] == {PLAYER_A: 90, PLAYER_B: 100}
        assert result["turn_player_id"] == PLAYER_A

        with pytest.raises(DuelError, match="already used your guard"):
            await submit_move(duel_id, PLAYER_A, GROUP_ID, 3, "guard")

        async with SessionLocal() as session:
            duel = await session.get(Duel, duel_id)
            assert duel.challenger_guard_used is True
            assert duel.challenger_guard_active is False

    run_async(run())


def test_forfeit_awards_both_reserved_stakes_to_other_player():
    async def run():
        await reset_players()
        duel_id = await new_accepted_duel()

        result = await forfeit_duel(duel_id, PLAYER_B, GROUP_ID)

        assert result["status"] == "forfeit"
        assert result["forfeited_by"] == PLAYER_B
        assert result["winner_id"] == PLAYER_A
        assert result["prize"] == 2_000
        async with SessionLocal() as session:
            duel = await session.get(Duel, duel_id)
            a = await session.get(User, PLAYER_A)
            b = await session.get(User, PLAYER_B)
            assert duel.status == "settled"
            assert a.points == 11_075
            assert b.points == 9_025

    run_async(run())


def test_late_action_refunds_expired_battle_and_cannot_settle_twice():
    async def run():
        await reset_players()
        duel_id = await new_accepted_duel()

        async with SessionLocal() as session:
            async with session.begin():
                duel = await session.get(Duel, duel_id)
                duel.last_activity_at = datetime.now(timezone.utc) - timedelta(
                    minutes=16
                )

        with pytest.raises(DuelError, match="both stakes were refunded"):
            await submit_move(duel_id, PLAYER_A, GROUP_ID, 1, "attack")

        async with SessionLocal() as session:
            duel = await session.get(Duel, duel_id)
            a = await session.get(User, PLAYER_A)
            b = await session.get(User, PLAYER_B)
            assert duel.status == "expired"
            assert a.points == 10_000
            assert b.points == 10_000

        assert await expire_stale_duels() == []
        async with SessionLocal() as session:
            a = await session.get(User, PLAYER_A)
            b = await session.get(User, PLAYER_B)
            assert a.points == 10_000
            assert b.points == 10_000

    run_async(run())


def test_wins_count_only_settled_battles_and_announcement_text():
    from app.handlers.duels import bull_that_ran_text
    from app.services.leaderboard_service import get_leaderboard
    from app.services.points_service import get_player

    async def run():
        await reset_players()
        expired_id = await new_accepted_duel()
        async with SessionLocal() as session:
            async with session.begin():
                duel = await session.get(Duel, expired_id)
                duel.last_activity_at = datetime.now(timezone.utc) - timedelta(
                    minutes=16
                )
        assert [item["duel_id"] for item in await expire_stale_duels()] == [
            expired_id
        ]
        assert (await get_player(PLAYER_A))["wins"] == 0

        duel_id = await new_accepted_duel()
        result = await forfeit_duel(duel_id, PLAYER_B, GROUP_ID)
        assert result["winner_id"] == PLAYER_A

        assert (await get_player(PLAYER_A))["wins"] == 1
        assert (await get_player(PLAYER_B))["wins"] == 0
        board = {p["telegram_id"]: p for p in await get_leaderboard(50)}
        if PLAYER_A in board:
            assert board[PLAYER_A]["wins"] == 1

    run_async(run())

    text = bull_that_ran_text(
        7, "@winner", "@winner", "@loser",
        {"challenger": 40, "opponent": 0}, 2_000,
    )
    assert text.startswith("🏆 THE BULL THAT RAN")
    assert "Congratulations @winner." in text
    assert "The Bull That Ran!" in text
    assert "2,000 Bullrun Points" in text
