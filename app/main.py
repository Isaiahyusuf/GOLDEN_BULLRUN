import asyncio
import logging
import os
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)
from sqlalchemy import select
from aiohttp import web

from app.config import settings
from app.database.connection import SessionLocal, engine, init_db
from app.handlers.payments import router as payments_router
from app.handlers.start import SECTIONS, router
from app.handlers.duels import router as duels_router
from app.handlers.groups import router as groups_router
from app.handlers.raids import router as raids_router
from app.keyboards.main_menu import group_play_post
from app.models.group import TelegramGroup
from app.services.duel_service import expire_stale_duels
from app.services.daily_rewards import settle_completed_daily_rewards
from app.services.group_play_posts import replace_group_play_post
from app.services.group_scheduled_posts import (
    HOW_TO_PLAY_POST_SECONDS,
    RAID_ADMIN_REMINDER_SECONDS,
    post_hourly_how_to_play,
    post_protection_reset_reminders,
    due_protection_reset_week,
    remind_group_admins_to_start_raids,
)
from app.services.protection_service import recover_weekly_resets
from app.services.weekly_rewards import get_completed_week_key
from app.services.x_oauth_service import (
    create_x_oauth_web_app,
    x_oauth_configured,
)


GROUP_PLAY_POST_INTERVAL_SECONDS = 600
BOT_COMMANDS = [
    BotCommand(command="start", description="Register and open the game"),
    BotCommand(command="menu", description="Show game menu"),
    BotCommand(command="pvp", description="Challenge: /pvp @username 100"),
    BotCommand(command="profile", description="View your player profile"),
    BotCommand(command="balance", description="Check your points"),
    BotCommand(command="missions", description="View and answer the active X quiz"),
    BotCommand(command="unlinkx", description="Disconnect your X account"),
    BotCommand(command="group_status", description="Check this group's bot setup"),
    BotCommand(command="enable_announcements", description="Enable group announcements"),
    BotCommand(command="disable_announcements", description="Disable group announcements"),
    BotCommand(command="setraid", description="Start an X post quiz (admins)"),
    BotCommand(command="stopraid", description="Stop the active X quiz (admins)"),
    BotCommand(command="groups", description="List bot groups (bot admins)"),
    BotCommand(command="help", description="How to play"),
    BotCommand(command="about", description="About TRUMPTY ROYALE"),
    BotCommand(command="cancel", description="Cancel the current quiz answer"),
]


async def configure_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        BOT_COMMANDS,
        scope=BotCommandScopeAllGroupChats(),
    )
    await bot.set_my_commands(
        BOT_COMMANDS,
        scope=BotCommandScopeAllPrivateChats(),
    )


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
                    await replace_group_play_post(
                        bot,
                        group_id,
                        text,
                        reply_markup,
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


async def raid_admin_reminders_loop(bot):
    while True:
        await asyncio.sleep(RAID_ADMIN_REMINDER_SECONDS)
        try:
            sent = await remind_group_admins_to_start_raids(bot)
            logging.info("Sent %s group raid-admin reminders", sent)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Raid-admin reminder cycle failed")


async def hourly_how_to_play_loop(bot):
    while True:
        await asyncio.sleep(HOW_TO_PLAY_POST_SECONDS)
        try:
            sent = await post_hourly_how_to_play(bot, SECTIONS["help"])
            logging.info("Posted hourly How to Play in %s groups", sent)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Hourly How to Play post cycle failed")


async def protection_reset_reminders_loop(bot):
    while True:
        try:
            week_key = due_protection_reset_week()
            if week_key is not None:
                sent = await post_protection_reset_reminders(bot, week_key)
                if sent:
                    logging.info(
                        "Posted %s protection reset reminders for %s",
                        sent,
                        week_key,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Protection reset reminder cycle failed")

        await asyncio.sleep(60)


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
                        "The challenge was not accepted within 60 seconds."
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
    oauth_runner = None
    background_tasks = []

    try:
        await init_db()

        bot = Bot(token=settings.bot_token)
        x_config_values = (
            settings.x_api_client_id,
            settings.x_api_redirect_uri,
            settings.x_api_token_encryption_key,
            settings.x_api_client_secret,
        )
        if any(x_config_values) and not x_oauth_configured():
            logging.error(
                "X OAuth configuration is incomplete; X quiz claims remain disabled."
            )
        elif x_oauth_configured():
            oauth_runner = web.AppRunner(create_x_oauth_web_app(bot))
            await oauth_runner.setup()
            site = web.TCPSite(
                oauth_runner,
                host="0.0.0.0",
                port=int(os.getenv("PORT", "8080")),
            )
            await site.start()
            logging.info("X OAuth callback server started")

        await configure_bot_commands(bot)
        dp = Dispatcher()
        dp.include_router(payments_router)
        dp.include_router(raids_router)
        dp.include_router(router)
        dp.include_router(groups_router)
        dp.include_router(duels_router)

        background_tasks = [
            asyncio.create_task(group_play_posts_loop(bot)),
            asyncio.create_task(raid_admin_reminders_loop(bot)),
            asyncio.create_task(hourly_how_to_play_loop(bot)),
            asyncio.create_task(protection_reset_reminders_loop(bot)),
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
            if oauth_runner is not None:
                await oauth_runner.cleanup()
            if bot is not None:
                await bot.session.close()
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
