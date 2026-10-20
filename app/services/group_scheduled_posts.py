import logging
from html import escape
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select

from app.keyboards.main_menu import private_protection_link
from app.database.connection import SessionLocal
from app.models.group import TelegramGroup
from app.services.x_raid_service import get_active_campaign


RAID_ADMIN_REMINDER_SECONDS = 15 * 60
HOW_TO_PLAY_POST_SECONDS = 60 * 60
PROTECTION_RESET_REMINDER_SECONDS = 24 * 60 * 60
RAID_REMINDER_TEXT = (
    "🎯 <b>Bull Mission reminder</b>\n\n"
    "Group admins: no Bull Mission is active. Start one for the group with:\n"
    "<code>/setraid https://x.com/name/status/POST_ID | "
    "Question about the post? | correct answer</code>\n"
    "Stop the active quiz any time with /stopraid."
)


def due_protection_reset_week(now=None) -> str | None:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    current_week_start = (
        now.replace(hour=0, minute=0, second=0, microsecond=0)
        - timedelta(days=now.weekday())
    )
    next_reset = current_week_start + timedelta(days=7)
    reminder_at = next_reset - timedelta(
        seconds=PROTECTION_RESET_REMINDER_SECONDS
    )
    if reminder_at <= now < next_reset:
        return (next_reset - timedelta(days=1)).strftime("%G-W%V")
    return None


async def _active_group_ids() -> list[int]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(TelegramGroup.chat_id).where(
                        TelegramGroup.active.is_(True)
                    )
                )
            ).all()
        )


async def remind_group_admins_to_start_raids(bot: Bot) -> int:
    if await get_active_campaign() is not None:
        return 0

    reminders_sent = 0
    for chat_id in await _active_group_ids():
        try:
            administrators = await bot.get_chat_administrators(chat_id)
        except TelegramAPIError:
            logging.exception(
                "Could not list admins for raid reminder in group %s",
                chat_id,
            )
            continue

        mentions = [
            (
                f'<a href="tg://user?id={member.user.id}">'
                f"{escape(member.user.full_name)}</a>"
            )
            for member in administrators
            if (
                not member.user.is_bot
                and member.status
                in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}
            )
        ]
        if not mentions:
            continue

        try:
            async with SessionLocal() as session:
                async with session.begin():
                    group = await session.scalar(
                        select(TelegramGroup)
                        .where(
                            TelegramGroup.chat_id == chat_id,
                            TelegramGroup.active.is_(True),
                        )
                        .with_for_update()
                    )
                    if group is None:
                        continue

                    sent_message = await bot.send_message(
                        chat_id,
                        f"{', '.join(mentions)}\n\n{RAID_REMINDER_TEXT}",
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    previous_message_id = (
                        group.raid_admin_reminder_message_id
                    )
                    if previous_message_id is not None:
                        try:
                            await bot.delete_message(
                                chat_id,
                                previous_message_id,
                            )
                        except TelegramAPIError:
                            logging.exception(
                                "Could not delete previous raid-admin "
                                "reminder %s in group %s",
                                previous_message_id,
                                chat_id,
                            )

                    group.raid_admin_reminder_message_id = (
                        sent_message.message_id
                    )
            reminders_sent += 1
        except TelegramAPIError:
            logging.exception(
                "Could not send raid reminder in group %s",
                chat_id,
            )

    return reminders_sent


async def post_hourly_how_to_play(bot: Bot, help_text: str) -> int:
    posts_sent = 0
    for chat_id in await _active_group_ids():
        try:
            await bot.send_message(
                chat_id,
                help_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            posts_sent += 1
        except TelegramAPIError:
            logging.exception(
                "Could not post hourly How to Play in group %s",
                chat_id,
            )

    return posts_sent


async def post_protection_reset_reminders(bot: Bot, week_key: str) -> int:
    reminders_sent = 0
    for chat_id in await _active_group_ids():
        try:
            async with SessionLocal() as session:
                async with session.begin():
                    group = await session.scalar(
                        select(TelegramGroup)
                        .where(
                            TelegramGroup.chat_id == chat_id,
                            TelegramGroup.active.is_(True),
                        )
                        .with_for_update()
                    )
                    if (
                        group is None
                        or group.protection_reminder_week == week_key
                    ):
                        continue

                    await bot.send_message(
                        chat_id,
                        "🛡️ <b>WEEKLY POINT RESET — 24 HOURS</b>\n\n"
                        "The weekly point reset is scheduled for "
                        "<b>00:00 UTC Monday</b>. Activate or renew Bull "
                        "Protection before the reset to preserve a portion "
                        "of your Bullrun Points above 10,000, based on your protection "
                        "rank.\n\n"
                        "Protection lasts 7 days and does not cover Bull Arena losses. "
                        "Purchases are completed privately in the bot.",
                        reply_markup=private_protection_link(),
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    group.protection_reminder_week = week_key
            reminders_sent += 1
        except TelegramAPIError:
            logging.exception(
                "Could not post weekly protection reminder in group %s",
                chat_id,
            )

    return reminders_sent
