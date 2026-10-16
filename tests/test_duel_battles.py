import asyncio

import pytest
from sqlalchemy import delete

from app.config import settings
from app.database.connection import SessionLocal, engine, init_db
from app.models.duel import Duel
from app.models.transaction import PointTransaction
from app.models.user import User
from app.services.duel_service import (
    DuelError,
    accept_duel,
    create_duel,
    submit_choice,
)


GROUP_ID = -1001234567890
PLAYER_A = 990002001
PLAYER_B = 990002002


async def reset_players():
    await init_db()
    ids = [PLAYER_A, PLAYER_B]

    async with SessionLocal() as session:
        async with session.begin():
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
                User(telegram_id=PLAYER_A, full_name="Player A", points=10_000),
                User(telegram_id=PLAYER_B, full_name="Player B", points=10_000),
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
            ])


async def new_accepted_duel():
    duel_id = await create_duel(PLAYER_A, PLAYER_B, 1_000, GROUP_ID)
    await accept_duel(duel_id, PLAYER_B, GROUP_ID)
    return duel_id



def run_async(coro):
    async def runner():
        try:
            await coro
        finally:
            await engine.dispose()

    asyncio.run(runner())


def test_defend_beats_attack_and_stale_moves_are_rejected(monkeypatch):
    monkeypatch.setattr(settings, "pvp_group_id", GROUP_ID)

    async def run():
        await reset_players()
        duel_id = await new_accepted_duel()

        first = await submit_choice(duel_id, PLAYER_A, "defend", GROUP_ID, 1)
        assert first["status"] == "waiting"

        with pytest.raises(DuelError, match="already locked in"):
            await submit_choice(duel_id, PLAYER_A, "attack", GROUP_ID, 1)

        second = await submit_choice(duel_id, PLAYER_B, "attack", GROUP_ID, 1)
        assert second["status"] == "next_round"
        assert second["score"] == {"challenger": 1, "opponent": 0}

        with pytest.raises(DuelError, match="expired"):
            await submit_choice(duel_id, PLAYER_A, "attack", GROUP_ID, 1)

        await submit_choice(duel_id, PLAYER_A, "defend", GROUP_ID, 2)
        result = await submit_choice(
            duel_id, PLAYER_B, "attack", GROUP_ID, 2
        )
        assert result["status"] == "settled"
        assert result["winner_id"] == PLAYER_A
        assert result["prize"] == 2_000

        async with SessionLocal() as session:
            a = await session.get(User, PLAYER_A)
            b = await session.get(User, PLAYER_B)
            assert a.points == 11_075
            assert b.points == 9_025
            assert result["activity_points"] == {
                PLAYER_A: 75,
                PLAYER_B: 25,
            }

    run_async(run())


def test_matching_moves_draw_and_refund_both_wagers(monkeypatch):
    monkeypatch.setattr(settings, "pvp_group_id", GROUP_ID)

    async def run():
        await reset_players()
        duel_id = await new_accepted_duel()

        # Round 1: both attack — draw.
        await submit_choice(duel_id, PLAYER_A, "attack", GROUP_ID, 1)
        result = await submit_choice(
            duel_id, PLAYER_B, "attack", GROUP_ID, 1
        )
        assert result["status"] == "next_round"
        assert result["score"] == {"challenger": 0, "opponent": 0}

        # Round 2: both defend — draw.
        await submit_choice(duel_id, PLAYER_A, "defend", GROUP_ID, 2)
        result = await submit_choice(
            duel_id, PLAYER_B, "defend", GROUP_ID, 2
        )
        assert result["status"] == "next_round"

        # Round 3: both attack — final score tied, wagers refunded.
        await submit_choice(duel_id, PLAYER_A, "attack", GROUP_ID, 3)
        result = await submit_choice(
            duel_id, PLAYER_B, "attack", GROUP_ID, 3
        )
        assert result["status"] == "draw"

        async with SessionLocal() as session:
            a = await session.get(User, PLAYER_A)
            b = await session.get(User, PLAYER_B)
            duel = await session.get(Duel, duel_id)
            assert a.points == 10_025
            assert b.points == 10_025
            assert result["activity_points"] == {
                PLAYER_A: 25,
                PLAYER_B: 25,
            }
            assert duel.status == "draw"
            assert duel.settled_at is not None

        with pytest.raises(DuelError, match="not accepting moves"):
            await submit_choice(duel_id, PLAYER_A, "attack", GROUP_ID, 3)

    run_async(run())


def test_nonparticipant_cannot_submit_move(monkeypatch):
    monkeypatch.setattr(settings, "pvp_group_id", GROUP_ID)

    async def run():
        await reset_players()
        duel_id = await new_accepted_duel()

        with pytest.raises(DuelError, match="Only duel participants"):
            await submit_choice(duel_id, 990002999, "attack", GROUP_ID, 1)

    run_async(run())
