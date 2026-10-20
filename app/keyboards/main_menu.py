from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.branding import LINKS


GROUP_PLAY_LORE = (
    "The gold is on the line. Name a rival Bull, set your stake, and see "
    "who runs the arena.",
    "The Bull Arena is open. A rival, a stake, and a battle stand between "
    "you and the title.",
    "Every Bull wants to be The Bull That Ran. Call out a rival and put your "
    "Bullrun Points on the line.",
    "Word from the arena: a Bull is looking for a match. Make your challenge "
    "count.",
    "No speeches needed. Name your rival, set the stake, and let the arena "
    "decide.",
    "…which coin will lead the way? Pick your opponent and climb the Top "
    "Bulls leaderboard.",
)


def group_play_post(cycle: int = 0):
    lore = GROUP_PLAY_LORE[cycle % len(GROUP_PLAY_LORE)]
    return (
        f"🐂 <b>GOLDEN BULLRUN</b>\n\n{lore}",
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
                InlineKeyboardButton(text="⚔️ PLAY", callback_data="menu:play"),
                InlineKeyboardButton(text="🐂 MY BULL PROFILE", callback_data="menu:profile"),
            ],
            [
                InlineKeyboardButton(text="🎯 BULL MISSIONS", callback_data="menu:missions"),
                InlineKeyboardButton(text="🏆 LEADERBOARD", callback_data="menu:leaderboard"),
            ],
            [
                InlineKeyboardButton(text="🥊 BULL ARENA", callback_data="menu:duel"),
            ],
            [
                InlineKeyboardButton(text="🪙 BULLRUN SHOP", callback_data="menu:shop"),
                InlineKeyboardButton(text="💎 REWARDS", callback_data="menu:rewards"),
            ],
            [
                InlineKeyboardButton(text="🛡️ BULL PROTECTION", callback_data="menu:protect"),
                InlineKeyboardButton(text="🪙 $GOLD TOKEN", callback_data="menu:token"),
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


def token_menu():
    buttons = [
        InlineKeyboardButton(text=label, url=url) for label, url in LINKS.items()
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append(
        [InlineKeyboardButton(text="🏠 MAIN MENU", callback_data="menu:home")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shop_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Starter · 5,000 $GOLD", callback_data="buy:1")],
            [InlineKeyboardButton(text="⚔️ Warrior · 10,000 $GOLD", callback_data="buy:2")],
            [InlineKeyboardButton(text="🛡️ Champion · 15,000 $GOLD", callback_data="buy:3")],
            [InlineKeyboardButton(text="👑 Royal · 20,000 $GOLD", callback_data="buy:4")],
            [InlineKeyboardButton(text="💎 Legend · 25,000 $GOLD", callback_data="buy:5")],
            [InlineKeyboardButton(text="🛡️ Bull Protection · 30,000 $GOLD", callback_data="menu:protect")],
            [InlineKeyboardButton(text="🏠 MAIN MENU", callback_data="menu:home")],
        ]
    )


def private_shop_link():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🪙 OPEN PRIVATE SHOP",
                url="https://t.me/Trumpty_dumptybot?start=shop",
            )]
        ]
    )


def private_protection_link():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🛡️ BUY / RENEW PROTECTION",
                url="https://t.me/Trumpty_dumptybot?start=protect",
            )]
        ]
    )


def private_x_connect_link():
    return "https://t.me/Trumpty_dumptybot?start=connectx"


def x_authorization_menu(authorization_url: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="𝕏 CONNECT ACCOUNT",
                url=authorization_url,
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
