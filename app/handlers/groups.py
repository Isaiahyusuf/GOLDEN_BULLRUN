import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.database.connection import SessionLocal
from app.models.group import TelegramGroup

router = Router()
GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}


async def save_group(chat):
    async with SessionLocal() as session:
        async with session.begin():
            statement = insert(TelegramGroup).values(
                chat_id=chat.id,
                title=chat.title or "Unnamed group",
                username=chat.username,
                active=True,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[TelegramGroup.chat_id],
                set_={
                    "title": statement.excluded.title,
                    "username": statement.excluded.username,
                    "active": True,
                },
            )
            await session.execute(statement)


async def group_is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in {
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.ADMINISTRATOR,
        }
    except Exception:
        logging.exception("Could not check group administrator status")
        return False


@router.my_chat_member()
async def bot_group_membership(event: ChatMemberUpdated, bot: Bot):
    if event.chat.type not in GROUP_TYPES:
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    if new_status in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
    }:
        await save_group(event.chat)

        if old_status not in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
        }:
            try:
                await bot.send_message(
                    event.chat.id,
                    "👑 <b>TRUMPTY ROYALE connected</b>\n\n"
                    "This group has been registered.\n"
                    "Group admins can use /group_status to check setup.\n"
                    "Announcements are off until a group admin enables them.",
                    parse_mode="HTML",
                )
            except Exception:
                logging.exception(
                    "Could not send registration message to group %s",
                    event.chat.id,
                )
    elif new_status in {
        ChatMemberStatus.LEFT,
        ChatMemberStatus.KICKED,
    }:
        async with SessionLocal() as session:
            async with session.begin():
                group = await session.get(TelegramGroup, event.chat.id)
                if group:
                    group.active = False


@router.message(Command("group_status"), F.chat.type.in_(GROUP_TYPES))
async def group_status(message: Message):
    await save_group(message.chat)

    async with SessionLocal() as session:
        group = await session.get(TelegramGroup, message.chat.id)
        enabled = group.announcements_enabled if group else False
        active = group.active if group else False

    await message.answer(
        "👑 <b>TRUMPTY ROYALE — GROUP STATUS</b>\n\n"
        f"Group: <b>{message.chat.title or 'Unnamed group'}</b>\n"
        f"Registered: <b>{'Yes' if active else 'No'}</b>\n"
        f"Announcements: <b>{'On' if enabled else 'Off'}</b>\n\n"
        "Group admins can use /enable_announcements or "
        "/disable_announcements.",
        parse_mode="HTML",
    )


@router.message(Command("enable_announcements"), F.chat.type.in_(GROUP_TYPES))
async def enable_announcements(message: Message, bot: Bot):
    if not message.from_user or not await group_is_admin(
        bot, message.chat.id, message.from_user.id
    ):
        await message.answer("Only this group's administrators can enable announcements.")
        return

    await save_group(message.chat)
    async with SessionLocal() as session:
        async with session.begin():
            group = await session.get(TelegramGroup, message.chat.id)
            group.announcements_enabled = True

    await message.answer(
        "🔔 TRUMPTY ROYALE announcements are now enabled for this group."
    )


@router.message(Command("disable_announcements"), F.chat.type.in_(GROUP_TYPES))
async def disable_announcements(message: Message, bot: Bot):
    if not message.from_user or not await group_is_admin(
        bot, message.chat.id, message.from_user.id
    ):
        await message.answer("Only this group's administrators can disable announcements.")
        return

    async with SessionLocal() as session:
        async with session.begin():
            group = await session.get(TelegramGroup, message.chat.id)
            if group:
                group.announcements_enabled = False

    await message.answer("🔕 TRUMPTY ROYALE announcements are now disabled.")


@router.message(Command("groups"), F.chat.type == ChatType.PRIVATE)
async def list_groups(message: Message):
    if not message.from_user or message.from_user.id not in settings.admin_ids:
        await message.answer("You are not authorized to use this command.")
        return

    async with SessionLocal() as session:
        groups = list(
            (await session.scalars(
                select(TelegramGroup).order_by(TelegramGroup.title)
            )).all()
        )

    if not groups:
        await message.answer("No Telegram groups have been registered yet.")
        return

    lines = ["<b>REGISTERED TRUMPTY ROYALE GROUPS</b>", ""]
    for group in groups:
        status = "Active" if group.active else "Bot removed"
        announcements = "On" if group.announcements_enabled else "Off"
        lines.append(
            f"• {group.title}\n"
            f"  ID: <code>{group.chat_id}</code>\n"
            f"  Status: {status} · Announcements: {announcements}"
        )

    await message.answer("\n\n".join(lines), parse_mode="HTML")
