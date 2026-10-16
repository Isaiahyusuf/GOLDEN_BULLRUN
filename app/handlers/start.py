from datetime import timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.config import settings
from app.keyboards.main_menu import (
    main_menu,
    back_menu,
    shop_menu,
    private_shop_link,
    private_protection_link,
    private_game_link,
    protection_menu,
)
from app.services.points_service import register_player, get_player
from app.services.leaderboard_service import get_leaderboard
from app.services.protection_service import get_protection_status
from app.services.solana_service import payments_configured

router = Router()

WELCOME_TEXT = (
    "👑 <b>TRUMPTY ROYALE</b>\n"
    "<i>The battle for the throne starts here.</i>\n\n"
    "💰 Build your competitive points. Challenge rivals. Climb the rankings.\n"
    "🎯 Join X post quizzes and earn points for correct answers.\n\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "⚡ <b>Your kingdom. Your strategy. Your crown.</b>\n\n"
    "👇 Choose your next move."
)

SECTIONS = {
    "about": (
        "👑 <b>ABOUT TRUMPTY ROYALE</b>\n\n"
        "TRUMPTY ROYALE is a Telegram game where players build competitive "
        "points, challenge rivals in group duels, and climb the leaderboard.\n\n"
        "🪙 Competitive points are gameplay points. Purchased credits are "
        "tracked separately and do not increase your leaderboard rank.\n"
        "🛡️ Points Protection has permanent progression ranks and can preserve "
        "part of your points above the 10,000 baseline at a weekly reset.\n"
        "🥊 Duels use points and are limited to the configured official group.\n"
        "𝕏 X post quizzes award competitive points for correct answers in the "
        "bot. No X engagement is required.\n\n"
        "🎁 Activity counts across every group where the bot is present. Each "
        "UTC day, the top five earn 500, 350, 250, 150, or 100 points.\n\n"
        "Payments are verified on Solana. Never send a seed phrase or private key."
    ),
    "play": (
        "⚔️ <b>ROYALE ARENA</b>\n\n"
        "Build your competitive points balance and prepare to challenge rivals.\n\n"
        "🥊 PvP is available only in the configured official Telegram group.\n"
        "𝕏 Open Missions to read an active X post and answer its quiz for points."
    ),
    "missions": (
        "🎯 <b>X RAID MISSIONS</b>\n\n"
        "Open this section in the bot's private chat to view an X post quiz. "
        "Answer correctly in the bot to earn 200 competitive points; no X "
        "engagement is required."
    ),
    "leaderboard": (
        "🏆 <b>HALL OF CHAMPIONS</b>\n\n"
        "The leaderboard will show eligible competitive points and weekly standings.\n\n"
        "Buying credits will not automatically buy a leaderboard position."
    ),
    "duel": (
        "🥊 <b>PVP ARENA</b>\n\n"
        "Duels are played in the official Telegram group, not in private chat.\n\n"
        "Challenge a registered player with:\n"
        "<code>/duel @username wager</code>\n\n"
        "Both players must have opened the bot and sent /start. Wagers must be "
        "between 1 and 1,000,000 points. The challenged player accepts the "
        "posted duel; both wagers are then reserved.\n\n"
        "Each round, both players secretly choose ATTACK or DEFEND. DEFEND "
        "beats ATTACK; matching choices draw the round. First to 2 round wins "
        "takes both wagers. A tied score after 3 rounds refunds both wagers. "
        "An unanswered challenge expires after 5 minutes; an inactive accepted "
        "duel expires after 15 minutes and refunds both wagers.\n\n"
        "Protection does not prevent duel losses."
    ),
    "rewards": (
        "🎁 <b>DAILY ACTIVITY REWARDS</b>\n\n"
        "The five highest activity scores earn competitive points at 00:00 UTC:\n"
        "🥇 1st: <b>500</b> · 🥈 2nd: <b>350</b> · 🥉 3rd: <b>250</b>\n"
        "4th: <b>150</b> · 5th: <b>100</b>\n\n"
        "Messages count across every group where the bot is present: one "
        "qualifying message every 30 seconds, up to 20 per player per UTC day. "
        "The score is global across groups. A completed duel adds 10 activity "
        "score per player and a win adds 5 more, up to 5 scored duels daily. "
        "Duels also give each player +25 points; the winner gets +50 extra, "
        "up to 5 completed duels daily. PvP bonuses require PvP to be enabled "
        "in its official group.\n\n"
        "Only message counts and timestamps are stored, not message text. "
        "Purchased credits do not count as competitive points.\n\n"
        "X post quizzes award 200 points for one correct answer per campaign. "
        "No likes, reposts, replies, or follows are required. "
        "Weekly token reward payouts are not available yet."
    ),
    "help": (
        "📜 <b>HOW TO PLAY</b>\n\n"
        "1. <b>Register:</b> send /start in the bot. New profiles begin with "
        "10,000 competitive points.\n"
        "2. <b>Check your account:</b> use /profile or /balance. Competitive "
        "points and purchased credits are separate; credits do not raise rank.\n"
        "3. <b>Earn daily activity rewards:</b> be active in any group where "
        "the bot is present. Register with /start first. The global top five "
        "are awarded 500 / 350 / 250 / 150 / 100 competitive points at 00:00 UTC. "
        "Messages count once every 30 seconds, up to 20 per day. Completed "
        "duels also add activity score; both players earn +25 points and the "
        "winner gets +50 extra, for up to 5 duels per day.\n"
        "4. <b>X post quiz:</b> open Missions, read the linked post, then answer "
        "the quiz in the bot. A correct answer earns 200 points once per "
        "campaign; you have up to 3 attempts. No X engagement is required.\n"
        "5. <b>Play PvP:</b> in the configured official group, challenge with "
        "<code>/duel @username wager</code>. Both players must be registered. "
        "Use the duel buttons to choose ATTACK or DEFEND each round. PvP needs "
        "an official group configured by the bot.\n"
        "6. <b>Protect points:</b> view Points Protection for your rank, price, "
        "expiry, and weekly-reset protection. It never protects PvP losses.\n"
        "7. <b>Shop privately:</b> open the shop only in the bot's private chat. "
        "Payments are checked on Solana before credits or protection are granted.\n\n"
        "Weekly token reward payouts are not available yet. X post quizzes "
        "award 200 points for a correct answer, once per campaign."
    ),
}


def get_section_text(section: str) -> str:
    if section == "duel" and settings.pvp_group_id is None:
        return (
            SECTIONS[section]
            + "\n\n🔴 <b>PvP is currently unavailable.</b>\n"
            "The official group has not been configured for the bot yet."
        )
    if section == "rewards" and settings.pvp_group_id is None:
        return (
            SECTIONS[section]
            + "\n\nGroup messages count in any group where the bot is present. "
            "PvP activity bonuses are unavailable until the official PvP group "
            "is configured."
        )
    return SECTIONS[section]


def get_payment_status_text() -> str:
    if payments_configured():
        return (
            "✅ Checkout is enabled. Payments are verified on Solana before delivery."
        )
    return (
        "🔒 Checkout is currently unavailable. Do not send tokens outside the bot's checkout."
    )


SHOP_TEXT = (
    "🪙 <b>TRUMPTY ROYALE — POINTS SHOP</b>\n\n"
    "Choose a package to see its details.\n"
    "Credits and competitive points are tracked separately.\n\n"
    "⚡ <b>Starter:</b> 10,000 credits · 5,000 $TRUMPTY\n"
    "⚔️ <b>Warrior:</b> 22,000 credits · 10,000 $TRUMPTY\n"
    "🛡️ <b>Champion:</b> 36,000 credits · 15,000 $TRUMPTY\n"
    "👑 <b>Royal:</b> 52,000 credits · 20,000 $TRUMPTY\n"
    "💎 <b>Legend:</b> 70,000 credits · 25,000 $TRUMPTY\n\n"
    "🛡️ <b>Points Protection:</b> starting at 30,000 $TRUMPTY for 7 days.\n"
    "<i>Price and points preserved rise with permanent protection rank (max rank 5; 150,000 $TRUMPTY). It never prevents duel losses.</i>\n\n"
    "Select an option below."
)

PROTECTION_TEXT = (
    "🛡️ <b>POINTS PROTECTION</b>\n\n"
    "Build a permanent protection rank to preserve more points at the weekly reset.\n\n"
    "💎 Starting price: <b>30,000 $TRUMPTY</b>; each rank costs more, capped at <b>150,000 $TRUMPTY</b>.\n"
    "⏳ Each activation lasts <b>7 days</b>; maximum rank: <b>5</b>.\n\n"
    "Protection does not cover points lost in PvP or override other game rules.\n"
    "It must be renewed after expiry."
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
            f"🛡️ Rank: <b>{status['rank']}/5</b> · "
            f"weekly points preserved: <b>{status['protected_percentage']}%</b> "
            "above 10,000\n"
            f"💎 Next activation: <b>{status['price']:,} $TRUMPTY</b>\n"
            f"⏳ Expires: <b>{expiry_text}</b>\n\n"
            "The protected share is based on points above the 10,000 baseline.\n"
            "PvP losses are not protected."
        )
    else:
        text = (
            PROTECTION_TEXT
            + "\n\n"
            + f"🔴 <b>Status: INACTIVE</b>\n"
            f"🛡️ Permanent rank: <b>{status['rank']}/5</b>\n"
            f"💎 Next activation: <b>{status['price']:,} $TRUMPTY</b>"
        )

    text += f"\n\n{get_payment_status_text()}"

    if edit:
        await target.edit_text(
            text,
            reply_markup=protection_menu(),
            parse_mode="HTML",
        )
    else:
        await target.answer(
            text,
            reply_markup=protection_menu(),
            parse_mode="HTML",
        )


@router.message(CommandStart())
async def start_command(message: Message):
    args = (message.text or "").split(maxsplit=1)
    start_arg = args[1].strip().lower() if len(args) > 1 else ""

    if message.chat.type != "private":
        await message.answer(
            "👑 Ready to play TRUMPTY ROYALE?\n\n"
            "Open the bot privately to register, view your balance, join X raids, "
            "and use your game controls.",
            reply_markup=private_game_link(
                "missions" if start_arg == "missions" else "play"
            ),
        )
        return

    player = await register_player(message.from_user)

    if start_arg == "shop":
        await message.answer(
            f"{SHOP_TEXT}\n\n{get_payment_status_text()}",
            reply_markup=shop_menu(),
            parse_mode="HTML",
        )
        return

    if start_arg == "protect":
        await send_protection_screen(message, message.from_user.id)
        return

    if start_arg == "missions":
        from app.handlers.raids import send_raid_screen

        await send_raid_screen(message, message.from_user.id)
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
    if message.chat.type != "private":
        await message.answer(
            "👑 Ready to play TRUMPTY ROYALE? Open the bot privately to "
            "register and access your game controls.",
            reply_markup=private_game_link(),
        )
        return
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
    await message.answer(
        get_section_text("help"),
        reply_markup=back_menu(),
        parse_mode="HTML",
    )


@router.message(Command("about"))
async def about_command(message: Message):
    await message.answer(
        SECTIONS["about"],
        reply_markup=back_menu(),
        parse_mode="HTML",
    )


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

    if section in {"play", "missions"} and chat_type != "private":
        await callback.message.answer(
            "👑 Ready to play? Open TRUMPTY ROYALE privately to register, "
            "check your balance, and join the active raids.",
            reply_markup=private_game_link(
                "missions" if section == "missions" else "play"
            ),
        )
        await callback.answer()
        return

    if section == "home":
        if chat_type != "private":
            await callback.message.edit_text(
                "👑 Ready to play TRUMPTY ROYALE? Open the bot privately to "
                "register and access your game controls.",
                reply_markup=private_game_link(),
            )
        else:
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
            f"{SHOP_TEXT}\n\n{get_payment_status_text()}",
            reply_markup=shop_menu(),
            parse_mode="HTML",
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
    elif section == "missions":
        from app.handlers.raids import send_raid_screen

        await send_raid_screen(
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
            get_section_text(section),
            reply_markup=back_menu(),
            parse_mode="HTML",
        )
    else:
        await callback.answer("That section isn't available yet.")
        return

    await callback.answer()
