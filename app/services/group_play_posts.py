import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup

from app.database.connection import SessionLocal
from app.models.group import TelegramGroup


async def replace_group_play_post(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> int:
    async with SessionLocal() as session:
        group = await session.get(TelegramGroup, chat_id)
        if group is None or not group.active:
            raise ValueError(f"Group {chat_id} is not registered and active.")
        previous_message_id = group.play_post_message_id

    if previous_message_id is not None:
        try:
            await bot.delete_message(chat_id, previous_message_id)
        except TelegramBadRequest as exc:
            if "message to delete not found" not in str(exc).lower():
                raise
            logging.info(
                "Previous arena post %s was already absent from group %s",
                previous_message_id,
                chat_id,
            )

    sent_message = await bot.send_message(
        chat_id,
        text,
        reply_markup=reply_markup,
        parse_mode="HTML",
    )

    async with SessionLocal() as session:
        async with session.begin():
            group = await session.get(TelegramGroup, chat_id)
            if group is None or not group.active:
                raise ValueError(
                    f"Group {chat_id} became inactive while posting."
                )
            group.play_post_message_id = sent_message.message_id

    return sent_message.message_id
