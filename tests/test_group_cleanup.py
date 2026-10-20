import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.enums import ChatMemberStatus
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.handlers.start import close_callback
from app.keyboards.main_menu import CLOSE_CALLBACK, back_menu, main_menu
from app.services import group_cleanup
from app.services.group_cleanup import DeletePreviousGroupPostMiddleware


def _send(chat_id, markup=None):
    return SendMessage(chat_id=chat_id, text="x", reply_markup=markup)


async def _post(mw, bot, method, message_id):
    async def make_request(_bot, _method):
        return SimpleNamespace(ok=True, result=SimpleNamespace(message_id=message_id))

    return await mw(make_request, bot, method)


def test_menus_have_close_button():
    for markup in (main_menu(), back_menu()):
        assert any(
            b.callback_data == CLOSE_CALLBACK
            for row in markup.inline_keyboard
            for b in row
        )


def test_deletes_previous_group_post_only():
    group_cleanup._last_message_ids.clear()
    bot = SimpleNamespace(delete_message=AsyncMock())
    mw = DeletePreviousGroupPostMiddleware()

    async def run():
        await _post(mw, bot, _send(-100), 1)
        bot.delete_message.assert_not_called()
        await _post(mw, bot, _send(-100), 2)
        bot.delete_message.assert_awaited_once_with(-100, 1)
        await _post(mw, bot, _send(555), 3)  # private chat untouched
        assert bot.delete_message.await_count == 1

    asyncio.run(run())


def test_battle_messages_are_never_deleted():
    group_cleanup._last_message_ids.clear()
    bot = SimpleNamespace(delete_message=AsyncMock())
    mw = DeletePreviousGroupPostMiddleware()
    duel = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="a", callback_data="duel:accept:1")]]
    )

    async def run():
        await _post(mw, bot, _send(-100, duel), 1)
        await _post(mw, bot, _send(-100), 2)
        bot.delete_message.assert_not_called()

    asyncio.run(run())


def _callback(chat_type, status=None):
    message = SimpleNamespace(
        chat=SimpleNamespace(type=chat_type, id=-100),
        delete=AsyncMock(),
        edit_reply_markup=AsyncMock(),
    )
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=SimpleNamespace(status=status))
    )
    return SimpleNamespace(
        message=message, bot=bot, from_user=SimpleNamespace(id=7), answer=AsyncMock()
    )


def test_close_private_deletes():
    cb = _callback("private")
    asyncio.run(close_callback(cb))
    cb.message.delete.assert_awaited_once()


def test_close_group_requires_admin():
    cb = _callback("supergroup", ChatMemberStatus.MEMBER)
    asyncio.run(close_callback(cb))
    cb.message.delete.assert_not_called()

    cb = _callback("supergroup", ChatMemberStatus.ADMINISTRATOR)
    asyncio.run(close_callback(cb))
    cb.message.delete.assert_awaited_once()
