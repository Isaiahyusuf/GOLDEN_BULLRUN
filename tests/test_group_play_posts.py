import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage
from aiogram.types import InlineKeyboardMarkup

from app.services.group_play_posts import replace_group_play_post


CHAT_ID = -1001234567890


def database_context(group):
    session = MagicMock()
    session.get = AsyncMock(return_value=group)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    context.begin = MagicMock(return_value=context)
    return context, session


def test_replacing_arena_post_deletes_old_post_and_saves_new_id():
    async def run():
        group = SimpleNamespace(
            active=True,
            play_post_message_id=123,
        )
        old_context, _ = database_context(group)
        new_context, _ = database_context(group)
        bot = MagicMock()
        bot.delete_message = AsyncMock()
        bot.send_message = AsyncMock(
            return_value=SimpleNamespace(message_id=456)
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])

        with patch(
            "app.services.group_play_posts.SessionLocal",
            side_effect=[old_context, new_context],
        ):
            message_id = await replace_group_play_post(
                bot,
                CHAT_ID,
                "Arena is open",
                keyboard,
            )

        assert message_id == 456
        bot.delete_message.assert_awaited_once_with(CHAT_ID, 123)
        bot.send_message.assert_awaited_once_with(
            CHAT_ID,
            "Arena is open",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        assert group.play_post_message_id == 456

    asyncio.run(run())


def test_failed_delete_does_not_create_another_arena_post():
    async def run():
        group = SimpleNamespace(
            active=True,
            play_post_message_id=123,
        )
        old_context, _ = database_context(group)
        bot = MagicMock()
        bot.delete_message = AsyncMock(
            side_effect=TelegramBadRequest(
                method=DeleteMessage(chat_id=CHAT_ID, message_id=123),
                message="not enough rights to delete messages",
            )
        )
        bot.send_message = AsyncMock()

        with patch(
            "app.services.group_play_posts.SessionLocal",
            return_value=old_context,
        ):
            with pytest.raises(TelegramBadRequest):
                await replace_group_play_post(
                    bot,
                    CHAT_ID,
                    "Arena is open",
                    InlineKeyboardMarkup(inline_keyboard=[]),
                )

        bot.send_message.assert_not_awaited()

    asyncio.run(run())
