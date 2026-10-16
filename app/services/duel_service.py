from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.database.connection import SessionLocal
from app.models.duel import Duel
from app.models.transaction import PointTransaction
from app.models.user import User
from app.services.daily_rewards import record_completed_duel


MAX_WAGER = 1_000_000
MAX_ROUNDS = 3
WINNING_SCORE = 2


class DuelError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


async def create_duel(
    challenger_id: int,
    opponent_id: int,
    wager: int,
    chat_id: int,
):
    if settings.pvp_group_id is None:
        raise DuelError("PvP is not configured yet.")
    if chat_id != settings.pvp_group_id:
        raise DuelError("Duels are only available in the official group.")
    if challenger_id == opponent_id:
        raise DuelError("You cannot challenge yourself.")
    if wager <= 0 or wager > MAX_WAGER:
        raise DuelError(f"Wager must be between 1 and {MAX_WAGER:,} points.")

    async with SessionLocal() as session:
        async with session.begin():
            ids = sorted((challenger_id, opponent_id))
            players = (
                await session.scalars(
                    select(User)
                    .where(User.telegram_id.in_(ids))
                    .order_by(User.telegram_id)
                    .with_for_update()
                )
            ).all()
            by_id = {player.telegram_id: player for player in players}

            if challenger_id not in by_id:
                raise DuelError("The challenger must register with /start first.")
            if opponent_id not in by_id:
                raise DuelError("The opponent must register with /start first.")
            if by_id[challenger_id].points < wager:
                raise DuelError("You do not have enough points for that wager.")

            duel = Duel(
                challenger_id=challenger_id,
                opponent_id=opponent_id,
                wager=wager,
                status="pending",
                chat_id=chat_id,
                created_at=_now(),
            )
            session.add(duel)
            await session.flush()
            duel_id = duel.id

    return duel_id


async def accept_duel(duel_id: int, accepting_user_id: int, chat_id: int):
    if settings.pvp_group_id is None or chat_id != settings.pvp_group_id:
        raise DuelError("Duels are only available in the official group.")

    async with SessionLocal() as session:
        async with session.begin():
            duel = await session.scalar(
                select(Duel).where(Duel.id == duel_id).with_for_update()
            )
            if duel is None:
                raise DuelError("Duel not found.")
            if duel.chat_id != chat_id:
                raise DuelError("This duel belongs to another chat.")
            if duel.status != "pending":
                raise DuelError("This duel is no longer available.")
            if accepting_user_id != duel.opponent_id:
                raise DuelError("Only the challenged player can accept.")

            ids = sorted((duel.challenger_id, duel.opponent_id))
            players = (
                await session.scalars(
                    select(User)
                    .where(User.telegram_id.in_(ids))
                    .order_by(User.telegram_id)
                    .with_for_update()
                )
            ).all()
            by_id = {player.telegram_id: player for player in players}

            if len(by_id) != 2:
                raise DuelError("Both players must have registered.")
            for player_id in ids:
                if by_id[player_id].points < duel.wager:
                    raise DuelError("A player no longer has enough points.")

            for player_id in ids:
                by_id[player_id].points -= duel.wager
                session.add(
                    PointTransaction(
                        telegram_id=player_id,
                        amount=-duel.wager,
                        reason=f"duel_reserve:{duel.id}",
                    )
                )

            accepted_time = _now()
            duel.status = "accepted"
            duel.accepted_at = accepted_time
            duel.last_activity_at = accepted_time

    return {"duel_id": duel_id, "wager": duel.wager, "status": "accepted"}


async def submit_choice(duel_id: int, player_id: int, choice: str, chat_id: int, expected_round: int):
    choice = choice.lower()
    if choice not in {"attack", "defend"}:
        raise DuelError("Choose ATTACK or DEFEND.")
    if settings.pvp_group_id is None or chat_id != settings.pvp_group_id:
        raise DuelError("Duels are only available in the official group.")

    async with SessionLocal() as session:
        async with session.begin():
            duel = await session.scalar(
                select(Duel).where(Duel.id == duel_id).with_for_update()
            )
            if duel is None:
                raise DuelError("Duel not found.")
            if duel.chat_id != chat_id:
                raise DuelError("This duel belongs to another chat.")
            if duel.status != "accepted":
                raise DuelError("This duel is not accepting moves.")
            if duel.round_number != expected_round:
                raise DuelError("That move button has expired. Use the current round's buttons.")
            if player_id == duel.challenger_id:
                if duel.challenger_choice is not None:
                    raise DuelError("Your move for this round is already locked in.")
                duel.challenger_choice = choice
            elif player_id == duel.opponent_id:
                if duel.opponent_choice is not None:
                    raise DuelError("Your move for this round is already locked in.")
                duel.opponent_choice = choice
            else:
                raise DuelError("Only duel participants can make a move.")

            duel.last_activity_at = _now()

            if duel.challenger_choice is None or duel.opponent_choice is None:
                return {
                    "status": "waiting",
                    "round": duel.round_number,
                    "message": "Move locked in. Waiting for the other player.",
                }

            challenger_choice = duel.challenger_choice
            opponent_choice = duel.opponent_choice

            if challenger_choice != opponent_choice:
                if challenger_choice == "defend":
                    duel.challenger_score += 1
                    round_winner = duel.challenger_id
                else:
                    duel.opponent_score += 1
                    round_winner = duel.opponent_id
            else:
                round_winner = None

            score = {
                "challenger": duel.challenger_score,
                "opponent": duel.opponent_score,
            }
            completed_round = duel.round_number
            duel.challenger_choice = None
            duel.opponent_choice = None

            finished = (
                duel.challenger_score >= WINNING_SCORE
                or duel.opponent_score >= WINNING_SCORE
                or completed_round >= MAX_ROUNDS
            )

            if finished:
                if duel.challenger_score == duel.opponent_score:
                    ids = sorted((duel.challenger_id, duel.opponent_id))
                    players = (
                        await session.scalars(
                            select(User)
                            .where(User.telegram_id.in_(ids))
                            .order_by(User.telegram_id)
                            .with_for_update()
                        )
                    ).all()
                    by_id = {player.telegram_id: player for player in players}
                    for participant_id in ids:
                        by_id[participant_id].points += duel.wager
                        session.add(
                            PointTransaction(
                                telegram_id=participant_id,
                                amount=duel.wager,
                                reason=f"duel_refund:{duel.id}",
                            )
                        )
                    activity_points = await record_completed_duel(
                        session,
                        duel.id,
                        duel.challenger_id,
                        duel.opponent_id,
                        winner_id=None,
                    )
                    duel.status = "draw"
                    duel.settled_at = _now()
                    return {
                        "status": "draw",
                        "round": completed_round,
                        "score": score,
                        "activity_points": activity_points,
                        "message": "The duel is a draw. Both wagers have been refunded.",
                    }

                winner_id = (
                    duel.challenger_id
                    if duel.challenger_score > duel.opponent_score
                    else duel.opponent_id
                )
                winner = await session.scalar(
                    select(User)
                    .where(User.telegram_id == winner_id)
                    .with_for_update()
                )
                if winner is None:
                    raise DuelError("Winner account not found.")

                prize = duel.wager * 2
                winner.points += prize
                duel.status = "settled"
                duel.winner_id = winner_id
                duel.settled_at = _now()
                session.add(
                    PointTransaction(
                        telegram_id=winner_id,
                        amount=prize,
                        reason=f"duel_prize:{duel.id}",
                    )
                )
                activity_points = await record_completed_duel(
                    session,
                    duel.id,
                    duel.challenger_id,
                    duel.opponent_id,
                    winner_id=winner_id,
                )
                return {
                    "status": "settled",
                    "round": completed_round,
                    "score": score,
                    "winner_id": winner_id,
                    "prize": prize,
                    "activity_points": activity_points,
                    "message": "The duel is over.",
                }

            duel.round_number += 1
            return {
                "status": "next_round",
                "round": completed_round,
                "score": score,
                "round_winner_id": round_winner,
                "next_round": duel.round_number,
                "message": "Round complete. Choose your next move.",
            }



PENDING_DUEL_TIMEOUT = timedelta(minutes=5)
ACCEPTED_DUEL_TIMEOUT = timedelta(minutes=15)


def _is_expired(timestamp, now, timeout):
    if timestamp is None:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return now - timestamp >= timeout


async def expire_stale_duels():
    now = _now()
    expired = []

    async with SessionLocal() as session:
        async with session.begin():
            duel_ids = list(
                await session.scalars(
                    select(Duel.id).where(
                        Duel.status.in_(("pending", "accepted"))
                    )
                )
            )

            for duel_id in duel_ids:
                duel = await session.scalar(
                    select(Duel)
                    .where(Duel.id == duel_id)
                    .with_for_update()
                )
                if duel is None:
                    continue

                if duel.status == "pending":
                    stale = _is_expired(
                        duel.created_at, now, PENDING_DUEL_TIMEOUT
                    )
                    refunded = False
                elif duel.status == "accepted":
                    last_activity = duel.last_activity_at or duel.accepted_at
                    stale = _is_expired(
                        last_activity, now, ACCEPTED_DUEL_TIMEOUT
                    )
                    refunded = True
                else:
                    continue

                if not stale:
                    continue

                if refunded:
                    ids = sorted((duel.challenger_id, duel.opponent_id))
                    players = (
                        await session.scalars(
                            select(User)
                            .where(User.telegram_id.in_(ids))
                            .order_by(User.telegram_id)
                            .with_for_update()
                        )
                    ).all()
                    by_id = {player.telegram_id: player for player in players}

                    if len(by_id) != 2:
                        continue

                    for player_id in ids:
                        by_id[player_id].points += duel.wager
                        session.add(
                            PointTransaction(
                                telegram_id=player_id,
                                amount=duel.wager,
                                reason=f"duel_timeout_refund:{duel.id}",
                            )
                        )

                duel.status = "expired"
                duel.settled_at = now
                duel.challenger_choice = None
                duel.opponent_choice = None

                expired.append(
                    {
                        "duel_id": duel.id,
                        "chat_id": duel.chat_id,
                        "status": "expired",
                        "refunded": refunded,
                    }
                )

    return expired
