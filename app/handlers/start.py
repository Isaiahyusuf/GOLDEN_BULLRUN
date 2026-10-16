from datetime import timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.keyboards.main_menu import (
    main_menu,
    back_menu,
    shop_menu,
    private_shop_link,
    private_protection_link,
    payment_unavailable_menu,
)
from app.services.points_service import register_player, get_player
from app.services.leaderboard_service import get_leaderboard
from app.services.protection_service import get_protection_status

router = Router()

WELCOME_TEXT = (
    "👑 <b>TRUMPTY ROYALE</b>\n"
    "<i>The battle for the throne starts here.</i>\n\n"
    "💰 Earn points. Challenge rivals. Claim glory.\n"
    "🎯 Complete missions and climb the rankings.\n\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "⚡ <b>Your kingdom. Your strategy. Your crown.</b>\n\n"
    "👇 Choose your next move."
)

PACKAGES = {
    "1": ("Starter Pack", 5_000, 10_000),
    "2": ("Warrior Pack", 10_000, 22_000),
    "3": ("Champion Pack", 15_000, 36_000),
    "4": ("Royal Pack", 20_000, 52_000),
    "5": ("Legend Pack", 25_000, 70_000),
}

SECTIONS = {
    "play": (
        "⚔️ <b>ROYALE ARENA</b>\n\n"
        "Complete missions, build your points balance and prepare to challenge rivals.\n\n"
        "🥊 PvP matches are for the designated Telegram group only."
    ),
    "missions": (
        "🎯 <b>MISSION CONTROL</b>\n\n"
        "📡 Community raids\n🧠 Project quizzes\n🔥 Daily challenges\n\n"
        "Mission rewards will become claimable when the mission system is enabled."
    ),
    "leaderboard": (
        "🏆 <b>HALL OF CHAMPIONS</b>\n\n"
        "The leaderboard will show eligible competitive points and weekly standings.\n\n"
        "Buying credits will not automatically buy a leaderboard position."
    ),
    "duel": (
        "🥊 <b>PVP ARENA</b>\n\n"
        "PvP is played in the official TRUMPTY ROYALE group, not in private chat.\n\n"
        "Open the group and use the duel options there. Wagers will only be enabled once the group and duel rules are configured."
    ),
    "rewards": (
        "💎 <b>ROYAL REWARDS</b>\n\n"
        "Weekly rewards are planned for eligible top players.\n"
        "Final eligibility and payout rules will be published before rewards go live."
    ),
    "help": (
        "📜 <b>HOW TO PLAY</b>\n\n"
        "👑 Register to create your profile.\n"
        "🎯 Complete eligible missions.\n"
        "🥊 Play PvP in the designated group.\n"
        "🏆 Compete for eligible weekly rewards.\n"
        "🪙 Make purchases only through the bot's private chat."
    ),
}

SHOP_TEXT = (
    "🪙 <b>TRUMPTY ROYALE — POINTS SHOP</b>\n\n"
    "Choose a package to see its details.\n"
    "Credits and competitive points are tracked separately.\n\n"
    "⚡ <b>Starter:</b> 10,000 credits · 5,000 $TRUMPTY\n"
    "⚔️ <b>Warrior:</b> 22,000 credits · 10,000 $TRUMPTY\n"
    "🛡️ <b>Champion:</b> 36,000 credits · 15,000 $TRUMPTY\n"
    "👑 <b>Royal:</b> 52,000 credits · 20,000 $TRUMPTY\n"
    "💎 <b>Legend:</b> 70,000 credits · 25,000 $TRUMPTY\n\n"
    "🛡️ <b>Points Protection:</b> 30,000 $TRUMPTY for 7 days.\n"
    "<i>Protection is intended to preserve eligible points through the weekly reset, not prevent duel losses.</i>\n\n"
    "Select an option below. Payments are not active yet."
)

PROTECTION_TEXT = (
    "🛡️ <b>POINTS PROTECTION</b>\n\n"
    "Keep your eligible points balance through the weekly reset.\n\n"
    "💎 Price: <b>30,000 $TRUMPTY</b>\n"
    "⏳ Duration: <b>7 days</b>\n\n"
    "Protection does not cover points lost in PvP or override other game rules.\n"
    "It must be renewed after expiry.\n\n"
    "<i>Purchases are not active yet. No payment has been requested.</i>"
)


async def show_home(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=main_menu(), parse_mode="HTML")


async def send_protection_screen(target, telegram_id: int, edit: bool = False):
    status = await get_protection_status(telegram_id)

    if status is None:
        text = (
            PROTECTION_TEXT
            + "\n\nSend /start in the bot's private chat to register first."
        )
    elif status["active"]:
        expiry = status["expires_at"]
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        expiry_text = expiry.strftime("%d %b %Y, %H:%M UTC")
        text = (
            "🛡️ <b>POINTS PROTECTION</b>\n\n"
            "🟢 <b>Status: ACTIVE</b>\n"
            f"⏳ Expires: <b>{expiry_text}</b>\n\n"
            "Your eligible balance is protected at the weekly reset while this remains active.\n"
            "PvP losses are not protected."
        )
    else:
        text = (
            PROTECTION_TEXT
            + "\n\n🔴 <b>Status: INACTIVE</b>"
        )

    if edit:
        await target.edit_text(
            text,
            reply_markup=payment_unavailable_menu(),
            parse_mode="HTML",
        )
    else:
        await target.answer(
            text,
            reply_markup=payment_unavailable_menu(),
            parse_mode="HTML",
        )


@router.message(CommandStart())
async def start_command(message: Message):
    args = (message.text or "").split(maxsplit=1)
    start_arg = args[1].strip().lower() if len(args) > 1 else ""

    player = await register_player(message.from_user)

    if start_arg == "shop":
        await message.answer(SHOP_TEXT, reply_markup=shop_menu(), parse_mode="HTML")
        return

    if start_arg == "protect":
        await send_protection_screen(message, message.from_user.id)
        return

    await message.answer(
        f"👑 <b>Welcome to TRUMPTY ROYALE, {player['name']}</b>\n\n"
        f"💰 Balance: <b>{player['points']:,} points</b>\n\n"
        "👇 Choose your next move.",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


@router.message(Command("menu"))
async def menu_command(message: Message):
    await show_home(message)


@router.message(Command("profile"))
async def profile_command(message: Message):
    player = await get_player(message.from_user.id)
    if player is None:
        await message.answer("Send /start first to register.")
        return

    username = f"@{player['username']}" if player["username"] else "Not set"
    await message.answer(
        "👤 <b>PLAYER PROFILE</b>\n\n"
        f"Name: <b>{player['name']}</b>\n"
        f"Username: {username}\n"
        f"💰 Balance: <b>{player['points']:,} points</b>",
        reply_markup=back_menu(),
        parse_mode="HTML",
    )


@router.message(Command("balance"))
async def balance_command(message: Message):
    player = await get_player(message.from_user.id)
    if player is None:
        await message.answer("Send /start first to register.")
        return

    await message.answer(
        f"💰 <b>Your balance:</b> {player['points']:,} points",
        reply_markup=back_menu(),
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def help_command(message: Message):
    await message.answer(SECTIONS["help"], reply_markup=back_menu(), parse_mode="HTML")


@router.callback_query(F.data.startswith("buy:"))
async def buy_package_callback(callback: CallbackQuery):
    if callback.message.chat.type != "private":
        await callback.answer("Open the shop in the bot's private chat.", show_alert=True)
        return

    package_id = callback.data.split(":", 1)[1]
    package = PACKAGES.get(package_id)

    if package is None:
        await callback.answer("Package not found.", show_alert=True)
        return

    name, price, credits = package
    await callback.message.edit_text(
        f"🪙 <b>{name}</b>\n\n"
        f"Price: <b>{price:,} $TRUMPTY</b>\n"
        f"Credits: <b>{credits:,}</b>\n\n"
        "🔒 <b>Checkout is not enabled yet.</b>\n"
        "Do not send tokens until the official receiving wallet and on-chain verification are configured.",
        reply_markup=payment_unavailable_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("menu:"))
async def menu_callback(callback: CallbackQuery):
    section = callback.data.split(":", 1)[1]
    chat_type = callback.message.chat.type

    if section in {"shop", "protect"} and chat_type != "private":
        if section == "shop":
            await callback.message.answer(
                "🪙 Purchases are handled privately. Tap below to open the bot's shop.",
                reply_markup=private_shop_link(),
            )
        else:
            await callback.message.answer(
                "🛡️ View Points Protection privately in the bot.",
                reply_markup=private_protection_link(),
            )
        await callback.answer()
        return

    if section == "home":
        await callback.message.edit_text(
            WELCOME_TEXT, reply_markup=main_menu(), parse_mode="HTML"
        )
    elif section == "profile":
        player = await get_player(callback.from_user.id)
        if player is None:
            await callback.answer("Send /start in the bot's private chat first.", show_alert=True)
            return

        username = f"@{player['username']}" if player["username"] else "Not set"
        await callback.message.edit_text(
            "👤 <b>PLAYER PROFILE</b>\n\n"
            f"Name: <b>{player['name']}</b>\n"
            f"Username: {username}\n"
            f"💰 Balance: <b>{player['points']:,} points</b>",
            reply_markup=back_menu(),
            parse_mode="HTML",
        )
    elif section == "shop":
        await callback.message.edit_text(
            SHOP_TEXT, reply_markup=shop_menu(), parse_mode="HTML"
        )
    elif section == "protect":
        if callback.message.chat.type != "private":
            await callback.answer(
                "Open Points Protection in the bot's private chat.",
                show_alert=True,
            )
            return
        await send_protection_screen(
            callback.message,
            callback.from_user.id,
            edit=True,
        )
    elif section == "leaderboard":
        from html import escape

        players = await get_leaderboard(10)

        if not players:
            leaderboard_text = (
                "🏆 <b>HALL OF CHAMPIONS</b>\\n\\n"
                "No players are registered yet. Send /start to join."
            )
        else:
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            lines = [
                "🏆 <b>HALL OF CHAMPIONS</b>",
                "",
                "Top players by competitive points:",
                "",
            ]

            for player in players:
                rank = player["rank"]
                marker = medals.get(rank, f"{rank}.")
                name = escape(player["name"] or "Player")
                if player["username"]:
                    display_name = f"{name} (@{escape(player['username'])})"
                else:
                    display_name = name

                lines.append(
                    f"{marker} <b>{display_name}</b>\\n"
                    f"   💰 {player['points']:,} points"
                )

            lines.extend([
                "",
                "━━━━━━━━━━━━━━━━━━",
                "🏅 Rankings use competitive points only.",
                "🪙 Purchased credits do not increase your rank.",
            ])
            leaderboard_text = "\\n".join(lines)

        await callback.message.edit_text(
            leaderboard_text,
            reply_markup=back_menu(),
            parse_mode="HTML",
        )
    elif section in SECTIONS:
        await callback.message.edit_text(
            SECTIONS[section], reply_markup=back_menu(), parse_mode="HTML"
        )
    else:
        await callback.answer("That section isn't available yet.")
        return

    await callback.answer()
