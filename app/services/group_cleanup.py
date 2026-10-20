import logging

from aiogram import Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.exceptions import TelegramAPIError
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.methods.base import Response, TelegramType
from aiogram.types import InlineKeyboardMarkup

# Latest deletable bot message per group chat. Kept in memory: after a restart
# the one message already on screen is simply left alone.
_last_message_ids: dict[int, int] = {}


def _is_battle_message(reply_markup) -> bool:
    """Active challenge/battle posts must stay so players can still act."""
    if not isinstance(reply_markup, InlineKeyboardMarkup):
        return False
    return any(
        (button.callback_data or "").startswith("duel:")
        for row in reply_markup.inline_keyboard
        for button in row
    )


class DeletePreviousGroupPostMiddleware(BaseRequestMiddleware):
    """Whenever the bot posts in a group, delete its previous post there."""

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        response = await make_request(bot, method)

        if (
            isinstance(method, SendMessage)
            and isinstance(method.chat_id, int)
            and method.chat_id < 0
            and response.ok
            and response.result is not None
        ):
            chat_id = method.chat_id
            new_message_id = response.result.message_id
            previous_id = None
            if _is_battle_message(method.reply_markup):
                previous_id = _last_message_ids.get(chat_id)
                _last_message_ids.pop(chat_id, None)
            else:
                previous_id = _last_message_ids.get(chat_id)
                _last_message_ids[chat_id] = new_message_id

            if previous_id is not None and previous_id != new_message_id:
                try:
                    await bot.delete_message(chat_id, previous_id)
                except TelegramAPIError as exc:
                    logging.info(
                        "Previous bot post %s in group %s not deleted: %s",
                        previous_id,
                        chat_id,
                        exc,
                    )

        return response
