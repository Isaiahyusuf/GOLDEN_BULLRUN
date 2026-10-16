import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher
from sqlalchemy import select

from app.config import settings
from app.database.connection import SessionLocal, engine, init_db
from app.handlers.payments import router as payments_router
from app.handlers.start import router
from app.handlers.duels import router as duels_router
from app.handlers.groups import router as groups_router
from app.handlers.raids import router as raids_router
from app.keyboards.main_menu import group_play_post
from app.models.group import TelegramGroup
from app.services.duel_service import expire_stale_duels
from app.services.daily_rewards import settle_completed_daily_rewards
from app.services.protection_service import recover_weekly_resets
from app.services.weekly_rewards import get_completed_week_key


GROUP_PLAY_POST_INTERVAL_SECONDS = 600


async def group_play_posts_loop(bot):
    cycle = 0
    while True:
        try:
            async with SessionLocal() as session:
                group_ids = list(
                    (
                        await session.scalars(
                            select(TelegramGroup.chat_id).where(
                                TelegramGroup.active.is_(True)
                            )
                        )
                    ).all()
                )

            text, reply_markup = group_play_post(cycle)
            for group_id in group_ids:
                try:
                    await bot.send_message(
                        group_id,
                        text,
                        reply_markup=reply_markup,
                        parse_mode="HTML",
                    )
                except Exception:
                    logging.exception(
                        "Could not post the group play prompt in group %s",
                        group_id,
                    )
            cycle += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Group play prompt cycle failed")

        await asyncio.sleep(GROUP_PLAY_POST_INTERVAL_SECONDS)


async def expire_duels_loop(bot):
    while True:
        await asyncio.sleep(30)
        try:
            expired = await expire_stale_duels()

            for duel in expired:
                chat_id = duel["chat_id"]
                if chat_id is None:
                    continue

                if duel["refunded"]:
                    message = (
                        f"⌛ DUEL #{duel['duel_id']} EXPIRED\n\n"
                        "The battle timed out. Both wagers have been refunded."
                    )
                else:
                    message = (
                        f"⌛ DUEL #{duel['duel_id']} EXPIRED\n\n"
                        "The challenge was not accepted within 5 minutes."
                    )

                try:
                    await bot.send_message(chat_id, message)
                except Exception:
                    logging.exception(
                        "Could not announce expiry for duel %s",
                        duel["duel_id"],
                    )

        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Duel expiry check failed")


async def weekly_reset_loop():
    processed_week = None

    while True:
        try:
            now = datetime.now(timezone.utc)
            week_key = get_completed_week_key(now)

            if week_key != processed_week:
                result = await recover_weekly_resets(now=now)

                if result.get("already_done"):
                    processed_week = week_key
                    logging.info(
                        "Weekly reset %s was already completed",
                        week_key,
                    )
                elif result.get("blocked"):
                    logging.error(
                        "Weekly reset %s was blocked: %s",
                        week_key,
                        result.get("reason"),
                    )
                else:
                    processed_week = week_key
                    logging.info(
                        "Weekly reset %s finished: reset=%s, protected=%s",
                        week_key,
                        result.get("reset", 0),
                        result.get("skipped", 0),
                    )

        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Weekly reset check failed")

        await asyncio.sleep(60)


async def daily_rewards_loop(bot):
    while True:
        try:
            settled = await settle_completed_daily_rewards()
            for result in settled:
                if not result["winners"]:
                    continue

                lines = [
                    f"👑 DAILY ACTIVITY REWARDS — {result['day_key'].isoformat()}",
                    "",
                ]
                for winner in result["winners"]:
                    display_name = winner["name"] or "Player"
                    if winner["username"]:
                        display_name += f" (@{winner['username']})"
                    lines.append(
                        f"{winner['rank']}. {display_name} — "
                        f"{winner['points']:,} points"
                    )

                async with SessionLocal() as session:
                    group_ids = list(
                        (
                            await session.scalars(
                                select(TelegramGroup.chat_id).where(
                                    TelegramGroup.active.is_(True)
                                )
                            )
                        ).all()
                    )

                for group_id in group_ids:
                    try:
                        await bot.send_message(group_id, "\n".join(lines))
                    except Exception:
                        logging.exception(
                            "Could not announce daily rewards in group %s for %s",
                            group_id,
                            result["day_key"],
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Daily rewards settlement failed")

        await asyncio.sleep(60)


async def main():
    logging.basicConfig(level=logging.INFO)

    bot = None
    background_tasks = []

    try:
        await init_db()

        bot = Bot(token=settings.bot_token)
        dp = Dispatcher()
        dp.include_router(payments_router)
        dp.include_router(raids_router)
        dp.include_router(router)
        dp.include_router(groups_router)
        dp.include_router(duels_router)

        background_tasks = [
            asyncio.create_task(group_play_posts_loop(bot)),
            asyncio.create_task(expire_duels_loop(bot)),
            asyncio.create_task(daily_rewards_loop(bot)),
            asyncio.create_task(weekly_reset_loop()),
        ]

        me = await bot.get_me()
        logging.info("Starting as @%s", me.username)
        await dp.start_polling(bot)
    finally:
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        try:
            if bot is not None:
                await bot.session.close()
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
