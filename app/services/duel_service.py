import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import SessionLocal
from app.models.duel import Duel
from app.models.group import TelegramGroup
from app.models.transaction import PointTransaction
from app.models.user import User
from app.services.daily_rewards import record_completed_duel


MIN_WAGER = 1
MAX_WAGER = 1_000_000
STARTING_HEALTH = 100
ATTACK_DAMAGE = 20
GUARD_REDUCTION = 10
PENDING_DUEL_TIMEOUT = timedelta(seconds=60)
ACCEPTED_DUEL_TIMEOUT = timedelta(minutes=15)
ACTIVE_DUEL_STATUSES = ("pending", "accepted")


class DuelError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


async def _locked_players(session: AsyncSession, player_ids: tuple[int, int]):
    ids = sorted(player_ids)
    players = (
        await session.scalars(
            select(User)
            .where(User.telegram_id.in_(ids))
            .order_by(User.telegram_id)
            .with_for_update()
        )
    ).all()
    return {player.telegram_id: player for player in players}


async def _settle_winner(
    session: AsyncSession,
    duel: Duel,
    winner_id: int,
):
    ids = (duel.challenger_id, duel.opponent_id)
    players = await _locked_players(session, ids)
    if len(players) != 2:
        raise DuelError("Both duel accounts must still be registered.")

    prize = duel.wager * 2
    players[winner_id].points += prize
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
    duel.status = "settled"
    duel.winner_id = winner_id
    duel.settled_at = _now()
    return {
        "status": "settled",
        "winner_id": winner_id,
        "prize": prize,
        "activity_points": activity_points,
    }


async def create_duel(
    challenger_id: int,
    opponent_id: int,
    wager: int,
    chat_id: int,
):
    if chat_id >= 0:
        raise DuelError("Duels are only available in group chats.")
    if challenger_id == opponent_id:
        raise DuelError("You cannot challenge yourself.")
    if wager < MIN_WAGER or wager > MAX_WAGER:
        raise DuelError(
            f"Wager must be between {MIN_WAGER:,} and {MAX_WAGER:,} Bullrun Points."
        )

    async with SessionLocal() as session:
        async with session.begin():
            group = await session.scalar(
                select(TelegramGroup).where(
                    TelegramGroup.chat_id == chat_id,
                    TelegramGroup.active.is_(True),
                )
            )
            if group is None:
                raise DuelError(
                    "The Bull Arena is only available in groups where the bot is registered."
                )

            players = await _locked_players(
                session,
                (challenger_id, opponent_id),
            )
            if challenger_id not in players:
                raise DuelError(
                    "The challenger must send /start in a group or the bot first."
                )
            if opponent_id not in players:
                raise DuelError(
                    "The opponent must send /start in a group or the bot first."
                )
            if players[challenger_id].is_bot or players[opponent_id].is_bot:
                raise DuelError("Bots cannot participate in PvP.")
            for player_id, player in players.items():
                if player.points < wager:
                    if player_id == challenger_id:
                        raise DuelError(
                            "You do not have enough Bullrun Points for that wager."
                        )
                    raise DuelError(
                        "The challenged Bull does not have enough Bullrun Points "
                        "for that wager."
                    )

            active_duel = await session.scalar(
                select(Duel.id).where(
                    Duel.status.in_(ACTIVE_DUEL_STATUSES),
                    or_(
                        Duel.challenger_id.in_((challenger_id, opponent_id)),
                        Duel.opponent_id.in_((challenger_id, opponent_id)),
                    ),
                ).limit(1)
            )
            if active_duel is not None:
                raise DuelError(
                    "One of these Bulls already has an active challenge "
                    "or battle."
                )

            duel = Duel(
                challenger_id=challenger_id,
                opponent_id=opponent_id,
                wager=wager,
                status="pending",
                chat_id=chat_id,
                created_at=_now(),
                challenger_health=STARTING_HEALTH,
                opponent_health=STARTING_HEALTH,
            )
            session.add(duel)
            await session.flush()
            duel_id = duel.id

    return duel_id


async def accept_duel(duel_id: int, accepting_user_id: int, chat_id: int):
    if chat_id >= 0:
        raise DuelError("Duels are only available in group chats.")

    expired = False
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
                if duel.status == "expired":
                    raise DuelError("This challenge has expired.")
                raise DuelError("This challenge is no longer available.")
            if _expired(duel.created_at, _now(), PENDING_DUEL_TIMEOUT):
                duel.status = "expired"
                duel.settled_at = _now()
                expired = True
            else:
                if accepting_user_id != duel.opponent_id:
                    raise DuelError("Only the challenged Bull can accept.")

                players = await _locked_players(
                    session,
                    (duel.challenger_id, duel.opponent_id),
                )
                if len(players) != 2:
                    raise DuelError("Both players must have registered.")
                if (
                    players[duel.challenger_id].is_bot
                    or players[duel.opponent_id].is_bot
                ):
                    raise DuelError("Bots cannot participate in PvP.")
                for player_id in (duel.challenger_id, duel.opponent_id):
                    if players[player_id].points < duel.wager:
                        raise DuelError("A Bull no longer has enough Bullrun Points.")

                for player_id in (duel.challenger_id, duel.opponent_id):
                    players[player_id].points -= duel.wager
                    session.add(
                        PointTransaction(
                            telegram_id=player_id,
                            amount=-duel.wager,
                            reason=f"duel_reserve:{duel.id}",
                        )
                    )

                accepted_time = _now()
                duel.status = "accepted"
                duel.turn_player_id = secrets.choice(
                    (duel.challenger_id, duel.opponent_id)
                )
                duel.challenger_health = STARTING_HEALTH
                duel.opponent_health = STARTING_HEALTH
                duel.challenger_guard_active = False
                duel.opponent_guard_active = False
                duel.challenger_guard_used = False
                duel.opponent_guard_used = False
                duel.accepted_at = accepted_time
                duel.last_activity_at = accepted_time

    if expired:
        raise DuelError("This challenge has expired.")

    return {
        "duel_id": duel_id,
        "wager": duel.wager,
        "status": "accepted",
        "turn_player_id": duel.turn_player_id,
        "challenger_health": STARTING_HEALTH,
        "opponent_health": STARTING_HEALTH,
    }


async def decline_duel(duel_id: int, declining_user_id: int, chat_id: int):
    if chat_id >= 0:
        raise DuelError("Challenges can only be declined in their group.")

    expired = False
    async with SessionLocal() as session:
        async with session.begin():
            duel = await session.scalar(
                select(Duel).where(Duel.id == duel_id).with_for_update()
            )
            if duel is None:
                raise DuelError("Duel not found.")
            if duel.chat_id != chat_id:
                raise DuelError("This challenge belongs to another chat.")
            if duel.status != "pending":
                if duel.status == "expired":
                    raise DuelError("This challenge has expired.")
                raise DuelError("This challenge is no longer available.")
            if declining_user_id != duel.opponent_id:
                raise DuelError("Only the challenged Bull can decline.")

            if _expired(duel.created_at, _now(), PENDING_DUEL_TIMEOUT):
                duel.status = "expired"
                duel.settled_at = _now()
                expired = True
            else:
                duel.status = "declined"
                duel.settled_at = _now()

    if expired:
        raise DuelError("This challenge has expired.")
    return {"duel_id": duel_id, "status": "declined"}


async def submit_move(
    duel_id: int,
    player_id: int,
    chat_id: int,
    expected_turn: int,
    action: str,
):
    if action not in {"attack", "guard"}:
        raise DuelError("Choose ATTACK or GUARD.")
    if chat_id >= 0:
        raise DuelError("Duels are only available in group chats.")

    expired = False
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
            last_activity = duel.last_activity_at or duel.accepted_at
            if _expired(last_activity, _now(), ACCEPTED_DUEL_TIMEOUT):
                await _refund_expired_duel(session, duel, _now())
                expired = True
            else:
                if duel.round_number != expected_turn:
                    raise DuelError("That attack button has expired.")
                if player_id not in (duel.challenger_id, duel.opponent_id):
                    raise DuelError("Only duel participants can move.")
                if player_id != duel.turn_player_id:
                    raise DuelError("It is not your turn.")

                if action == "guard":
                    if player_id == duel.challenger_id:
                        if duel.challenger_guard_used:
                            raise DuelError(
                                "You have already used your guard this battle."
                            )
                        duel.challenger_guard_used = True
                        duel.challenger_guard_active = True
                    else:
                        if duel.opponent_guard_used:
                            raise DuelError(
                                "You have already used your guard this battle."
                            )
                        duel.opponent_guard_used = True
                        duel.opponent_guard_active = True
                    target_id = (
                        duel.opponent_id
                        if player_id == duel.challenger_id
                        else duel.challenger_id
                    )
                    damage = 0
                else:
                    if player_id == duel.challenger_id:
                        target_id = duel.opponent_id
                        damage = ATTACK_DAMAGE
                        if duel.opponent_guard_active:
                            damage -= GUARD_REDUCTION
                            duel.opponent_guard_active = False
                        duel.opponent_health = max(
                            0, duel.opponent_health - damage
                        )
                    else:
                        target_id = duel.challenger_id
                        damage = ATTACK_DAMAGE
                        if duel.challenger_guard_active:
                            damage -= GUARD_REDUCTION
                            duel.challenger_guard_active = False
                        duel.challenger_health = max(
                            0, duel.challenger_health - damage
                        )

                duel.last_activity_at = _now()
                health = {
                    duel.challenger_id: duel.challenger_health,
                    duel.opponent_id: duel.opponent_health,
                }
                result = {
                    "status": "next_turn",
                    "turn": duel.round_number,
                    "turn_player_id": target_id,
                    "attacker_id": player_id,
                    "target_id": target_id,
                    "action": action,
                    "damage": damage,
                    "health": health,
                }

                if action == "attack" and health[target_id] == 0:
                    settlement = await _settle_winner(
                        session,
                        duel,
                        winner_id=player_id,
                    )
                    result.update(settlement)
                    result["health"] = health
                    result["turn"] = duel.round_number
                    result["damage"] = damage
                    result["attacker_id"] = player_id
                    result["target_id"] = target_id
                else:
                    duel.round_number += 1
                    duel.turn_player_id = target_id
                    result["turn"] = duel.round_number
                    result["turn_player_id"] = target_id

    if expired:
        raise DuelError("This battle has expired and both stakes were refunded.")
    return result


async def forfeit_duel(duel_id: int, player_id: int, chat_id: int):
    if chat_id >= 0:
        raise DuelError("Duels are only available in group chats.")

    expired = False
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
                raise DuelError("This battle is no longer active.")
            last_activity = duel.last_activity_at or duel.accepted_at
            if _expired(last_activity, _now(), ACCEPTED_DUEL_TIMEOUT):
                await _refund_expired_duel(session, duel, _now())
                expired = True
            else:
                if player_id == duel.challenger_id:
                    winner_id = duel.opponent_id
                elif player_id == duel.opponent_id:
                    winner_id = duel.challenger_id
                else:
                    raise DuelError("Only duel participants can forfeit.")

                result = await _settle_winner(session, duel, winner_id)
                result["forfeited_by"] = player_id
                result["status"] = "forfeit"
                result["challenger_health"] = duel.challenger_health
                result["opponent_health"] = duel.opponent_health

    if expired:
        raise DuelError("This battle has expired and both stakes were refunded.")
    return result


def _expired(timestamp, now, timeout):
    if timestamp is None:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return now - timestamp >= timeout


async def _refund_expired_duel(
    session: AsyncSession,
    duel: Duel,
    now: datetime,
):
    players = await _locked_players(
        session,
        (duel.challenger_id, duel.opponent_id),
    )
    if len(players) != 2:
        raise DuelError("Cannot refund this expired battle: a player is missing.")

    for player_id in (duel.challenger_id, duel.opponent_id):
        players[player_id].points += duel.wager
        session.add(
            PointTransaction(
                telegram_id=player_id,
                amount=duel.wager,
                reason=f"duel_timeout_refund:{duel.id}",
            )
        )
    duel.status = "expired"
    duel.settled_at = now


async def expire_stale_duels():
    now = _now()
    expired = []

    async with SessionLocal() as session:
        async with session.begin():
            duel_ids = list(
                await session.scalars(
                    select(Duel.id).where(Duel.status.in_(ACTIVE_DUEL_STATUSES))
                )
            )

            for duel_id in duel_ids:
                duel = await session.scalar(
                    select(Duel)
                    .where(Duel.id == duel_id)
                    .with_for_update()
                )
                if duel is None or duel.status not in ACTIVE_DUEL_STATUSES:
                    continue

                if duel.status == "pending":
                    stale = _expired(
                        duel.created_at, now, PENDING_DUEL_TIMEOUT
                    )
                    refunded = False
                else:
                    last_activity = duel.last_activity_at or duel.accepted_at
                    stale = _expired(
                        last_activity, now, ACCEPTED_DUEL_TIMEOUT
                    )
                    refunded = True

                if not stale:
                    continue

                if refunded:
                    await _refund_expired_duel(session, duel, now)
                else:
                    duel.status = "expired"
                    duel.settled_at = now
                expired.append(
                    {
                        "duel_id": duel.id,
                        "chat_id": duel.chat_id,
                        "status": "expired",
                        "refunded": refunded,
                    }
                )

    return expired
