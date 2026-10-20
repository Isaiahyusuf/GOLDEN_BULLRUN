import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.types import BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

from app.handlers import start
from app.keyboards.main_menu import GROUP_PLAY_LORE, group_play_post, main_menu
from app.main import BOT_COMMANDS, configure_bot_commands


def test_about_and_how_to_play_are_available_from_main_menu():
    callbacks = {
        button.callback_data
        for row in main_menu().inline_keyboard
        for button in row
    }

    assert "menu:about" in callbacks
    assert "menu:help" in callbacks
    assert "<code>/pvp @username amount</code>" in start.SECTIONS["help"]
    assert "any active group where the bot is present" in start.SECTIONS["help"]
    assert "00:00 UTC" in start.SECTIONS["help"]
    assert "Bull Missions" in start.SECTIONS["help"]
    assert "The Bull That Ran" in start.SECTIONS["help"]
    assert "Like and Repost the campaign post" in start.SECTIONS["help"]
    assert "Reply to it" in start.SECTIONS["help"]
    assert "Follow its author" in start.SECTIONS["help"]
    assert "Weekly token payouts are not available yet." in start.SECTIONS["help"]


def test_about_explains_daily_rewards_across_groups():
    assert "every group where the bot is present" in start.SECTIONS["about"]
    assert "500, 350, 250, 150, or 100 Bullrun Points" in start.SECTIONS["about"]
    assert "𝕏 X" not in start.SECTIONS["about"]


def test_rewards_explains_all_group_activity_and_pvp():
    text = start.get_section_text("rewards")

    assert "every group where the bot is present" in text
    assert "PvP works in any group where the bot is present" in text
    assert "Purchased credits do not count as competitive points" not in text


def test_static_leaderboard_copy_matches_current_balance_ranking():
    text = start.SECTIONS["leaderboard"]

    assert "Bullrun Points balances" in text
    assert "Purchased credits are tracked separately" in text
    assert "weekly standings" not in text


def test_support_button_opens_configured_telegram_username():
    support_buttons = [
        button
        for row in main_menu().inline_keyboard
        for button in row
        if button.text == "🆘 SUPPORT"
    ]

    assert len(support_buttons) == 1
    assert support_buttons[0].url == "https://t.me/WitheringGrass13"


def test_protection_link_opens_private_protection_purchase_flow():
    from app.keyboards.main_menu import private_protection_link, private_shop_link

    button = private_protection_link().inline_keyboard[0][0]
    shop_button = private_shop_link().inline_keyboard[0][0]

    assert button.text == "🛡️ BUY / RENEW PROTECTION"
    assert button.url == "https://t.me/Trumpty_dumptybot?start=protect"
    assert shop_button.url == "https://t.me/Trumpty_dumptybot?start=shop"


def test_x_authorization_button_uses_clear_action_label():
    from app.keyboards.main_menu import x_authorization_menu

    button = x_authorization_menu("https://x.example/authorize").inline_keyboard[0][0]

    assert button.text == "𝕏 CONNECT ACCOUNT"
    assert button.url == "https://x.example/authorize"


def test_leaderboard_uses_real_line_breaks_and_consistent_player_blocks():
    async def run():
        callback = SimpleNamespace(
            data="menu:leaderboard",
            message=SimpleNamespace(
                chat=SimpleNamespace(type="private"),
                edit_text=AsyncMock(),
            ),
            from_user=SimpleNamespace(id=101),
            answer=AsyncMock(),
        )
        players = [
            {
                "rank": 1,
                "name": "Champion",
                "username": "champion",
                "points": 10_725,
                "wins": 3,
            },
            {
                "rank": 2,
                "name": "Runner Up",
                "username": "runnerup",
                "points": 10_000,
            },
        ]

        with patch.object(
            start,
            "get_leaderboard",
            new=AsyncMock(return_value=players),
        ):
            await start.menu_callback(callback)

        text = callback.message.edit_text.await_args.args[0]
        assert "\\n" not in text
        assert "🥇 <b>Champion (@champion)</b>\n   💰 <b>10,725</b> Bullrun Points" in text
        assert "🥈 <b>Runner Up (@runnerup)</b>\n   💰 <b>10,000</b> Bullrun Points" in text
        assert "🏆 3 wins" in text
        assert text.index("Champion") < text.index("Runner Up")
        assert "🏅 Rankings use Bullrun Points only." in text

    asyncio.run(run())


def test_duel_section_explains_group_pvp():
    text = start.get_section_text("duel")

    assert "any group where the bot is present" in text
    assert "1,000,000 Bullrun Points" in text
    assert "100 HP" in text
    assert "20 damage" in text
    assert "one guard per battle" in text
    assert "60 seconds" in text


def test_group_play_uses_local_group_pvp_and_keeps_shop_private():
    text = start.group_play_text()

    assert "/pvp @username 100" in text
    assert "Only that Bull can accept" in text
    assert "Purchases are handled privately" in text
    assert "PLAY IN PRIVATE CHAT" not in text


def test_group_play_posts_rotate_lore_with_arena_button():
    first_text, first_keyboard = group_play_post(0)
    second_text, second_keyboard = group_play_post(1)
    first_button = first_keyboard.inline_keyboard[0][0]
    second_button = second_keyboard.inline_keyboard[0][0]

    assert len(GROUP_PLAY_LORE) >= 4
    assert first_text != second_text
    assert first_button.callback_data == "group:play"
    assert second_button.callback_data == "group:play"
    assert first_button.text == "⚔️ ENTER THE ARENA"
    assert second_button.text == first_button.text
    from app.main import GROUP_PLAY_POST_INTERVAL_SECONDS

    assert GROUP_PLAY_POST_INTERVAL_SECONDS == 600


def test_telegram_group_and_private_command_menus_include_game_commands():
    class FakeBot:
        def __init__(self):
            self.command_sets = []

        async def set_my_commands(self, commands, scope):
            self.command_sets.append((commands, scope))

    async def run():
        bot = FakeBot()
        await configure_bot_commands(bot)
        return bot.command_sets

    command_sets = asyncio.run(run())
    expected_commands = {
        "start",
        "menu",
        "pvp",
        "profile",
        "balance",
        "missions",
        "unlinkx",
    }

    assert len(command_sets) == 2
    for commands, _ in command_sets:
        assert expected_commands <= {command.command for command in commands}
        assert "duel" not in {command.command for command in commands}
    assert isinstance(command_sets[0][1], BotCommandScopeAllGroupChats)
    assert isinstance(command_sets[1][1], BotCommandScopeAllPrivateChats)


def test_checkout_message_tracks_payment_configuration(monkeypatch):
    monkeypatch.setattr(start, "payments_configured", lambda: True)
    assert "Checkout is enabled" in start.get_payment_status_text()

    monkeypatch.setattr(start, "payments_configured", lambda: False)
    assert "currently unavailable" in start.get_payment_status_text()


def test_gold_token_section_and_bull_rank():
    from app.branding import TOKEN_ADDRESS, bull_rank
    from app.keyboards.main_menu import token_menu

    assert TOKEN_ADDRESS == "HHegCiT5d2i6oUnvBoxPP9dsYjJt1dKoxWw3rWegpump"
    assert f"<code>{TOKEN_ADDRESS}</code>" in __import__(
        "app.branding", fromlist=["TOKEN_TEXT"]
    ).TOKEN_TEXT
    urls = [b.url for row in token_menu().inline_keyboard for b in row if b.url]
    assert "https://goldenbullrun.org" in urls
    assert "menu:token" in [
        b.callback_data
        for row in start.main_menu().inline_keyboard
        for b in row
    ]
    assert bull_rank(0) == "🐄 Calf"
    assert bull_rank(10_000) == "🐂 Bull"
    assert bull_rank(60_000) == "🏆 Bull Market Legend"
    assert "Bull Rank" in start.profile_text(
        {"name": "A", "username": None, "points": 20_000, "wins": 0}
    )
