from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.connection import SessionLocal
from app.models.daily_reward import DailyActivity, DailyRewardSettlement
from app.models.transaction import PointTransaction
from app.models.user import User


DAILY_REWARD_LADDER = (500, 350, 250, 150, 100)
MESSAGE_DAILY_CAP = 20
MESSAGE_COOLDOWN = timedelta(seconds=30)
DUEL_DAILY_CAP = 5
DUEL_PARTICIPATION_POINTS = 25
DUEL_WIN_BONUS_POINTS = 50


def activity_score(
    message_count: int,
    scored_duels: int,
    scored_duel_wins: int,
) -> int:
    return (
        min(message_count, MESSAGE_DAILY_CAP)
        + scored_duels * 10
        + scored_duel_wins * 5
    )


async def record_group_message(telegram_id: int, now: datetime | None = None) -> bool:
    if settings.pvp_group_id is None:
        return False

    now = now or datetime.now(timezone.utc)
    day_key = now.date()

    async with SessionLocal() as session:
        async with session.begin():
            registered = await session.scalar(
                select(User.telegram_id).where(User.telegram_id == telegram_id)
            )
            if registered is None:
                return False

            statement = insert(DailyActivity).values(
                day_key=day_key,
                telegram_id=telegram_id,
                message_count=1,
                first_activity_at=now,
                last_message_at=now,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[
                    DailyActivity.day_key,
                    DailyActivity.telegram_id,
                ],
                set_={
                    "message_count": DailyActivity.message_count + 1,
                    "last_message_at": now,
                },
                where=and_(
                    DailyActivity.message_count < MESSAGE_DAILY_CAP,
                    or_(
                        DailyActivity.last_message_at.is_(None),
                        DailyActivity.last_message_at
                        <= now - MESSAGE_COOLDOWN,
                    ),
                ),
            ).returning(DailyActivity.telegram_id)
            return (await session.scalar(statement)) is not None


async def record_completed_duel(
    session: AsyncSession,
    duel_id: int,
    challenger_id: int,
    opponent_id: int,
    winner_id: int | None,
    now: datetime | None = None,
) -> dict[int, int]:
    now = now or datetime.now(timezone.utc)
    day_key = now.date()
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
    if len(by_id) != 2:
        raise ValueError("Both duel participants must still be registered.")

    activity_points = {}
    for telegram_id in ids:
        statement = insert(DailyActivity).values(
            day_key=day_key,
            telegram_id=telegram_id,
            completed_duels=1,
            scored_duels=1,
            scored_duel_wins=1 if telegram_id == winner_id else 0,
            first_activity_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[DailyActivity.day_key, DailyActivity.telegram_id],
            set_={
                "completed_duels": DailyActivity.completed_duels + 1,
                "scored_duels": case(
                    (DailyActivity.scored_duels < DUEL_DAILY_CAP,
                     DailyActivity.scored_duels + 1),
                    else_=DailyActivity.scored_duels,
                ),
                "scored_duel_wins": case(
                    (
                        and_(
                            DailyActivity.scored_duels < DUEL_DAILY_CAP,
                            telegram_id == winner_id,
                        ),
                        DailyActivity.scored_duel_wins + 1,
                    ),
                    else_=DailyActivity.scored_duel_wins,
                ),
                "first_activity_at": func.least(
                    DailyActivity.first_activity_at, now
                ),
            },
        ).returning(DailyActivity.completed_duels)
        completed_count = await session.scalar(statement)

        bonus = 0
        if completed_count <= DUEL_DAILY_CAP:
            bonus = DUEL_PARTICIPATION_POINTS
            if telegram_id == winner_id:
                bonus += DUEL_WIN_BONUS_POINTS
            by_id[telegram_id].points += bonus
            session.add(
                PointTransaction(
                    telegram_id=telegram_id,
                    amount=bonus,
                    reason=f"duel_activity:{duel_id}:{telegram_id}",
                )
            )
        activity_points[telegram_id] = bonus

    return activity_points


async def settle_daily_rewards(day_key: date) -> dict:
    async with SessionLocal() as session:
        async with session.begin():
            claim = insert(DailyRewardSettlement).values(
                day_key=day_key,
                winners=[],
            ).on_conflict_do_nothing(
                index_elements=[DailyRewardSettlement.day_key]
            )
            result = await session.execute(claim)
            if result.rowcount == 0:
                return {"day_key": day_key, "already_settled": True, "winners": []}

            score = (
                DailyActivity.message_count
                + DailyActivity.scored_duels * 10
                + DailyActivity.scored_duel_wins * 5
            )
            activity = (
                await session.execute(
                    select(
                        DailyActivity.telegram_id,
                        score.label("score"),
                        DailyActivity.first_activity_at,
                    )
                    .join(User, User.telegram_id == DailyActivity.telegram_id)
                    .where(
                        DailyActivity.day_key == day_key,
                        score > 0,
                    )
                    .order_by(
                        score.desc(),
                        DailyActivity.first_activity_at.asc(),
                        DailyActivity.telegram_id.asc(),
                    )
                    .limit(len(DAILY_REWARD_LADDER))
                )
            ).all()
            user_ids = [row.telegram_id for row in activity]
            users = (
                await session.scalars(
                    select(User)
                    .where(User.telegram_id.in_(user_ids))
                    .order_by(User.telegram_id)
                    .with_for_update()
                )
            ).all() if user_ids else []
            by_id = {player.telegram_id: player for player in users}

            winners = []
            for rank, row in enumerate(activity, start=1):
                player = by_id.get(row.telegram_id)
                if player is None:
                    continue

                amount = DAILY_REWARD_LADDER[rank - 1]
                player.points += amount
                session.add(
                    PointTransaction(
                        telegram_id=player.telegram_id,
                        amount=amount,
                        reason=f"daily_reward:{day_key.isoformat()}:{rank}",
                    )
                )
                winners.append({
                    "rank": rank,
                    "telegram_id": player.telegram_id,
                    "name": player.full_name,
                    "username": player.username,
                    "score": row.score,
                    "points": amount,
                })

            settlement = await session.get(
                DailyRewardSettlement, day_key
            )
            settlement.winners = winners
            settlement.settled_at = datetime.now(timezone.utc)

    return {"day_key": day_key, "already_settled": False, "winners": winners}


async def settle_completed_daily_rewards(
    now: datetime | None = None,
) -> list[dict]:
    today = (now or datetime.now(timezone.utc)).date()
    async with SessionLocal() as session:
        pending_days = list(
            (
                await session.scalars(
                    select(DailyActivity.day_key)
                    .distinct()
                    .outerjoin(
                        DailyRewardSettlement,
                        DailyRewardSettlement.day_key == DailyActivity.day_key,
                    )
                    .where(
                        DailyActivity.day_key < today,
                        DailyRewardSettlement.day_key.is_(None),
                    )
                    .order_by(DailyActivity.day_key)
                )
            ).all()
        )

    results = []
    for day_key in pending_days:
        results.append(await settle_daily_rewards(day_key))
    return results
