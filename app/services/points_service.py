from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.database.connection import SessionLocal
from app.models.user import User
from app.models.transaction import PointTransaction
async def register_player(telegram_user):
    async with SessionLocal() as session:
        statement = (
            insert(User)
            .values(
                telegram_id=telegram_user.id,
                username=telegram_user.username,
                full_name=telegram_user.full_name,
                points=10_000,
            )
            .on_conflict_do_nothing(index_elements=[User.telegram_id])
            .returning(User.telegram_id)
        )
        result = await session.execute(statement)
        is_new = result.scalar_one_or_none() is not None
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_user.id)
        )
        player = result.scalar_one()
        player.username = telegram_user.username
        player.full_name = telegram_user.full_name
        if is_new:
            session.add(
                PointTransaction(
                    telegram_id=player.telegram_id,
                    amount=10_000,
                    reason="welcome_bonus",
                )
            )
        await session.commit()
        return {
            "name": player.full_name,
            "username": player.username,
            "points": player.points,
        }
async def get_player(telegram_id):
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        player = result.scalar_one_or_none()
        if player is None:
            return None
        return {
            "name": player.full_name,
            "username": player.username,
            "points": player.points,
        }