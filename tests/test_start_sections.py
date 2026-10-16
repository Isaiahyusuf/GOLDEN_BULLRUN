from app.handlers import start
from app.keyboards.main_menu import GROUP_PLAY_LORE, group_play_post, main_menu


def test_about_and_how_to_play_are_available_from_main_menu():
    callbacks = {
        button.callback_data
        for row in main_menu().inline_keyboard
        for button in row
    }

    assert "menu:about" in callbacks
    assert "menu:help" in callbacks
    assert "<code>/duel @username 1000</code>" in start.SECTIONS["help"]
    assert "any group where the bot is present" in start.SECTIONS["help"]
    assert "00:00 UTC" in start.SECTIONS["help"]
    assert "X post quiz" in start.SECTIONS["help"]
    assert "No X engagement is required" in start.SECTIONS["help"]
    assert "Weekly token reward payouts are not available yet." in (
        start.SECTIONS["help"]
    )


def test_about_explains_daily_rewards_across_groups():
    assert "every group where the bot is present" in start.SECTIONS["about"]
    assert "500, 350, 250, 150, or 100 points" in start.SECTIONS["about"]


def test_rewards_explains_all_group_activity_and_pvp():
    text = start.get_section_text("rewards")

    assert "every group where the bot is present" in text
    assert "PvP works in any group where the bot is present" in text


def test_support_button_opens_configured_telegram_username():
    support_buttons = [
        button
        for row in main_menu().inline_keyboard
        for button in row
        if button.text == "🆘 SUPPORT"
    ]

    assert len(support_buttons) == 1
    assert support_buttons[0].url == "https://t.me/WitheringGrass13"


def test_duel_section_explains_group_pvp():
    text = start.get_section_text("duel")

    assert "any group where the bot is present" in text
    assert "1,000,000 points" in text
    assert "First to 2 round wins" in text


def test_group_play_uses_local_group_pvp_and_keeps_shop_private():
    text = start.group_play_text()

    assert "/duel @username 1000" in text
    assert "Only that player can accept" in text
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


def test_checkout_message_tracks_payment_configuration(monkeypatch):
    monkeypatch.setattr(start, "payments_configured", lambda: True)
    assert "Checkout is enabled" in start.get_payment_status_text()

    monkeypatch.setattr(start, "payments_configured", lambda: False)
    assert "currently unavailable" in start.get_payment_status_text()
