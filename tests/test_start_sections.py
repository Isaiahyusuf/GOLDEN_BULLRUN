from app.handlers import start
from app.keyboards.main_menu import main_menu


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


def test_rewards_explains_all_group_activity_without_pvp_configuration(monkeypatch):
    monkeypatch.setattr(start.settings, "pvp_group_id", None)

    text = start.get_section_text("rewards")

    assert "every group where the bot is present" in text
    assert "PvP activity bonuses are unavailable" in text


def test_support_button_opens_configured_telegram_username():
    support_buttons = [
        button
        for row in main_menu().inline_keyboard
        for button in row
        if button.text == "🆘 SUPPORT"
    ]

    assert len(support_buttons) == 1
    assert support_buttons[0].url == "https://t.me/WitheringGrass13"


def test_duel_section_explains_unconfigured_pvp(monkeypatch):
    monkeypatch.setattr(start.settings, "pvp_group_id", None)

    text = start.get_section_text("duel")

    assert "currently unavailable" in text
    assert "1,000,000 points" in text
    assert "First to 2 round wins" in text


def test_duel_section_does_not_claim_pvp_is_disabled_when_configured(monkeypatch):
    monkeypatch.setattr(start.settings, "pvp_group_id", -100123)

    assert "currently unavailable" not in start.get_section_text("duel")


def test_group_play_uses_group_pvp_and_keeps_shop_private(monkeypatch):
    monkeypatch.setattr(start.settings, "pvp_group_id", -100123)

    text = start.group_play_text(-100123)

    assert "/duel @username 1000" in text
    assert "Only that player can accept" in text
    assert "Purchases are handled privately" in text
    assert "PLAY IN PRIVATE CHAT" not in text


def test_group_play_on_non_pvp_group_does_not_redirect_gameplay_to_private(
    monkeypatch,
):
    monkeypatch.setattr(start.settings, "pvp_group_id", -100123)

    text = start.group_play_text(-100456)

    assert "configured official Telegram group" in text
    assert "register here with /start" in text
    assert "privately" not in text.lower()


def test_checkout_message_tracks_payment_configuration(monkeypatch):
    monkeypatch.setattr(start, "payments_configured", lambda: True)
    assert "Checkout is enabled" in start.get_payment_status_text()

    monkeypatch.setattr(start, "payments_configured", lambda: False)
    assert "currently unavailable" in start.get_payment_status_text()
