import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.enums import ChatMemberStatus

from app.handlers.start import SECTIONS
from app.services import group_scheduled_posts
from app.services.group_scheduled_posts import (
    HOW_TO_PLAY_POST_SECONDS,
    RAID_ADMIN_REMINDER_SECONDS,
)


GROUP_ID = -1001234567890


def test_scheduled_group_post_intervals():
    assert RAID_ADMIN_REMINDER_SECONDS == 15 * 60
    assert HOW_TO_PLAY_POST_SECONDS == 60 * 60


def fake_session_context():
    session = MagicMock()
    session.scalars = AsyncMock(
        return_value=SimpleNamespace(all=lambda: [GROUP_ID])
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


def test_raid_admin_reminder_mentions_group_admins_only_if_no_quiz_active():
    async def run():
        context = fake_session_context()
        bot = MagicMock()
        bot.get_chat_administrators = AsyncMock(
            return_value=[
                SimpleNamespace(
                    user=SimpleNamespace(
                        id=101,
                        is_bot=False,
                        full_name="Group Admin",
                    ),
                    status=ChatMemberStatus.ADMINISTRATOR,
                ),
                SimpleNamespace(
                    user=SimpleNamespace(id=102, is_bot=False, full_name="Player"),
                    status=ChatMemberStatus.MEMBER,
                ),
                SimpleNamespace(
                    user=SimpleNamespace(id=103, is_bot=True, full_name="Bot"),
                    status=ChatMemberStatus.ADMINISTRATOR,
                ),
            ]
        )
        bot.send_message = AsyncMock()
        with (
            patch(
                "app.services.group_scheduled_posts.get_active_campaign",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.group_scheduled_posts.SessionLocal",
                return_value=context,
            ),
        ):
            sent = await group_scheduled_posts.remind_group_admins_to_start_raids(
                bot
            )

        assert sent == 1
        bot.get_chat_administrators.assert_awaited_once_with(GROUP_ID)
        bot.send_message.assert_awaited_once()
        args, kwargs = bot.send_message.await_args
        assert args[0] == GROUP_ID
        assert 'tg://user?id=101">Group Admin</a>' in args[1]
        assert "tg://user?id=102" not in args[1]
        assert "tg://user?id=103" not in args[1]
        assert "/setraid" in args[1]
        assert kwargs["parse_mode"] == "HTML"

    asyncio.run(run())


def test_raid_admin_reminders_pause_while_campaign_is_active():
    async def run():
        bot = MagicMock()
        bot.get_chat_administrators = AsyncMock()
        bot.send_message = AsyncMock()
        with patch(
            "app.services.group_scheduled_posts.get_active_campaign",
            new=AsyncMock(return_value=object()),
        ):
            sent = await group_scheduled_posts.remind_group_admins_to_start_raids(
                bot
            )

        assert sent == 0
        bot.get_chat_administrators.assert_not_awaited()
        bot.send_message.assert_not_awaited()

    asyncio.run(run())


def test_hourly_how_to_play_posts_detailed_instructions_to_active_groups():
    async def run():
        context = fake_session_context()
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch(
            "app.services.group_scheduled_posts.SessionLocal",
            return_value=context,
        ):
            sent = await group_scheduled_posts.post_hourly_how_to_play(
                bot,
                SECTIONS["help"],
            )

        assert sent == 1
        args, kwargs = bot.send_message.await_args
        assert args[0] == GROUP_ID
        assert "TRUMPTY ROYALE — HOW TO PLAY" in args[1]
        assert "/pvp @username amount" in args[1]
        assert "/missions" in args[1]
        assert "/setraid" in args[1]
        assert "GUARD once" in args[1]
        assert kwargs["parse_mode"] == "HTML"

    asyncio.run(run())
