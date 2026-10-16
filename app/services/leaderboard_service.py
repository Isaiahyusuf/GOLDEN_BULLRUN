from sqlalchemy import select

from app.database.connection import SessionLocal
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

        return [
            {
                "rank": index,
                "telegram_id": player.telegram_id,
                "name": player.full_name,
                "username": player.username,
                "points": player.points,
            }
            for index, player in enumerate(players, start=1)
        ]
