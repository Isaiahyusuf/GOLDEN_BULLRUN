from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


GROUP_PLAY_LORE = (
    "The throne has stayed empty long enough. Name a rival, set your stake, "
    "and see who holds the crown.",
    "The hall is open. A rival, a stake, and three rounds stand between you "
    "and the crown.",
    "Old scores fade. New ones are settled here. Call out a rival and put "
    "your points on the line.",
    "Word from the arena: someone is looking for a match. Make your challenge "
    "count.",
    "No speeches needed. Name your rival, set the stake, and let the arena "
    "decide.",
    "The crown won't claim itself. Pick your opponent and fight for the top "
    "of the leaderboard.",
)


def group_play_post(cycle: int = 0):
    lore = GROUP_PLAY_LORE[cycle % len(GROUP_PLAY_LORE)]
    return (
        f"👑 <b>TRUMPTY ROYALE</b>\n\n{lore}",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="⚔️ ENTER THE ARENA",
                    callback_data="group:play",
                )]
            ]
        ),
    )


def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚔️ PLAY NOW", callback_data="menu:play"),
                InlineKeyboardButton(text="👤 PROFILE", callback_data="menu:profile"),
            ],
            [
                InlineKeyboardButton(text="🎯 MISSIONS", callback_data="menu:missions"),
                InlineKeyboardButton(text="🏆 LEADERBOARD", callback_data="menu:leaderboard"),
            ],
            [
                InlineKeyboardButton(text="🥊 PVP ARENA", callback_data="menu:duel"),
            ],
            [
                InlineKeyboardButton(text="🪙 POINTS SHOP", callback_data="menu:shop"),
                InlineKeyboardButton(text="💎 REWARDS", callback_data="menu:rewards"),
            ],
            [
                InlineKeyboardButton(text="🛡️ POINTS PROTECTION", callback_data="menu:protect"),
            ],
            [
                InlineKeyboardButton(text="📜 HOW TO PLAY", callback_data="menu:help"),
                InlineKeyboardButton(text="ℹ️ ABOUT", callback_data="menu:about"),
            ],
            [
                InlineKeyboardButton(
                    text="🆘 SUPPORT",
                    url="https://t.me/WitheringGrass13",
                ),
            ],
        ]
    )


def back_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 MAIN MENU", callback_data="menu:home")]
        ]
    )


def shop_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Starter · 5,000 $TRUMPTY", callback_data="buy:1")],
            [InlineKeyboardButton(text="⚔️ Warrior · 10,000 $TRUMPTY", callback_data="buy:2")],
            [InlineKeyboardButton(text="🛡️ Champion · 15,000 $TRUMPTY", callback_data="buy:3")],
            [InlineKeyboardButton(text="👑 Royal · 20,000 $TRUMPTY", callback_data="buy:4")],
            [InlineKeyboardButton(text="💎 Legend · 25,000 $TRUMPTY", callback_data="buy:5")],
            [InlineKeyboardButton(text="🛡️ Points Protection · 30,000 $TRUMPTY", callback_data="menu:protect")],
            [InlineKeyboardButton(text="🏠 MAIN MENU", callback_data="menu:home")],
        ]
    )


def private_shop_link():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🪙 OPEN PRIVATE SHOP",
                url="https://t.me/TrumptyDumptybot?start=shop",
            )]
        ]
    )


def private_protection_link():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🛡️ VIEW POINTS PROTECTION",
                url="https://t.me/TrumptyDumptybot?start=protect",
            )]
        ]
    )


def protection_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🛡️ BUY / RENEW PROTECTION",
                callback_data="protect:buy",
            )],
            [InlineKeyboardButton(text="🏠 MAIN MENU", callback_data="menu:home")],
        ]
    )


def payment_unavailable_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ BACK TO SHOP", callback_data="menu:shop")],
            [InlineKeyboardButton(text="🏠 MAIN MENU", callback_data="menu:home")],
        ]
    )
