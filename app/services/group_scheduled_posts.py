import logging
from html import escape

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select

from app.database.connection import SessionLocal
from app.models.group import TelegramGroup
from app.services.x_raid_service import get_active_campaign


RAID_ADMIN_REMINDER_SECONDS = 15 * 60
HOW_TO_PLAY_POST_SECONDS = 60 * 60
RAID_REMINDER_TEXT = (
    "🎯 <b>Raid reminder</b>\n\n"
    "Group admins: no X post quiz is active. Start one for the group with:\n"
    "<code>/setraid https://x.com/name/status/POST_ID | "
    "Question about the post? | correct answer</code>\n"
    "Stop the active quiz any time with /stopraid."
)
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
            await bot.send_message(
                chat_id,
                f"{', '.join(mentions)}\n\n{RAID_REMINDER_TEXT}",
                parse_mode="HTML",
                disable_web_page_preview=True,
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
