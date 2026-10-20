from sqlalchemy import func, select

from app.database.connection import SessionLocal
from app.models.duel import Duel
from app.models.user import User


async def get_leaderboard(limit=10):
    limit = max(1, min(int(limit), 50))

    async with SessionLocal() as session:
        players = (
            await session.scalars(
                select(User)
                .order_by(
                    User.points.desc(),
                    User.created_at.asc(),
                    User.telegram_id.asc(),
                )
                .limit(limit)
            )
        ).all()

        win_rows = await session.execute(
            select(Duel.winner_id, func.count(Duel.id))
            .where(
                Duel.status == "settled",
                Duel.winner_id.in_([player.telegram_id for player in players]),
            )
            .group_by(Duel.winner_id)
        )
        wins = {winner_id: count for winner_id, count in win_rows.all()}

        return [
            {
                "rank": index,
                "telegram_id": player.telegram_id,
                "name": player.full_name,
                "username": player.username,
                "points": player.points,
                "wins": wins.get(player.telegram_id, 0),
            }
            for index, player in enumerate(players, start=1)
        ]
