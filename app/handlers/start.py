from datetime import timezone
from html import escape

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.branding import TAGLINE, TOKEN_TEXT, bull_rank
from app.keyboards.main_menu import (
    CLOSE_CALLBACK,
    main_menu,
    back_menu,
    token_menu,
    shop_menu,
    private_shop_link,
    private_protection_link,
    protection_menu,
    x_authorization_menu,
)
from app.services.points_service import register_player, get_player
from app.services.leaderboard_service import get_leaderboard
from app.services.protection_service import get_protection_status
from app.services.solana_service import payments_configured
from app.services.x_oauth_service import (
    XOAuthError,
    create_x_authorization_url,
)

router = Router()


WELCOME_TEXT = (
    "🐂 <b>GOLDEN BULLRUN</b>\n"
    f"<i>“{TAGLINE}”</i>\n\n"
    "Welcome to Golden Bullrun, Bull.\n\n"
    "Enter the arena, compete against other Bulls, earn Bullrun Points and "
    "prove yourself worthy of becoming 🏆 <b>The Bull That Ran</b>.\n\n"
    "👇 Choose your next move."
)

SECTIONS = {
    "about": (
        "🐂 <b>ABOUT GOLDEN BULLRUN</b>\n"
        f"<i>“{TAGLINE}”</i>\n\n"
        "Golden Bullrun is a Telegram game where every player is a Bull. "
        "Bulls earn Bullrun Points, challenge rivals in the Bull Arena, and "
        "climb the leaderboard. Win a battle and you are crowned "
        "🏆 <b>The Bull That Ran</b>.\n\n"
        "🪙 Bullrun Points are gameplay points. Purchased credits are "
        "tracked separately and do not increase your leaderboard rank.\n"
        "🛡️ Bull Protection has permanent progression ranks and can preserve "
        "part of your Bullrun Points above the 10,000 baseline at a weekly reset.\n"
        "🥊 The Bull Arena is open in any group where the bot is present.\n"
        "Bull Missions (X post quizzes) award Bullrun Points after a correct "
        "answer and verified Like, Repost, Reply, and Follow actions.\n\n"
        "🎁 Activity counts across every group where the bot is present. Each "
        "UTC day, the top five Bulls earn 500, 350, 250, 150, or 100 Bullrun Points.\n\n"
        "Payments are verified on Solana. Never send a seed phrase or private key."
    ),
    "play": (
        "⚔️ <b>BULL ARENA</b>\n\n"
        "The Bull Arena is open in any group where the bot is present.\n\n"
        "Challenge another Bull with:\n"
        "<code>/pvp @username 100</code>\n\n"
        "Only the mentioned Bull can accept. Both wagers are reserved after "
        "they accept. If they are not registered, they can tap the Start "
        "button in the group prompt to register.\n\n"
        "Bull Missions are available with /missions in this group."
    ),
    "missions": (
        "🎯 <b>BULL MISSIONS</b>\n\n"
        "View the active X post quiz and submit your answer here in the group. "
        "A correct answer earns 200 Bullrun Points after your linked X "
        "account completes the campaign's Like, Repost, Reply, and Follow actions."
    ),
    "leaderboard": (
        "🏆 <b>TOP BULLS</b>\n\n"
        "Rankings are based on Bullrun Points balances. Purchased credits "
        "are tracked separately and do not affect your position."
    ),
    "duel": (
        "🥊 <b>BULL ARENA</b>\n\n"
        "Battles are played in any group where the bot is present, not in private chat.\n\n"
        "Challenge a registered Bull with:\n"
        "<code>/pvp @username 100</code>\n\n"
        "Both Bulls must be registered. If your opponent is not registered, "
        "the group prompt gives them a button to open the bot and tap Start. "
        "Wagers must be between 1 and 1,000,000 Bullrun Points. The challenged Bull "
        "accepts the group challenge; only that mentioned Bull can accept, "
        "and both wagers are then reserved.\n\n"
        "Each Bull starts with 100 HP. Bulls take turns attacking for "
        "20 damage or using one guard per battle to reduce the next hit by "
        "10. The first Bull to reach 0 HP loses and the winner takes both "
        "stakes and is crowned 🏆 <b>The Bull That Ran</b>; the first turn is "
        "chosen at random. The challenge expires "
        "after 60 seconds. An inactive "
        "battle expires after 15 minutes and refunds both stakes. Either "
        "Bull may forfeit during a battle.\n\n"
        "Protection does not prevent Bull Arena losses."
    ),
    "rewards": (
        "🎁 <b>DAILY ACTIVITY REWARDS</b>\n\n"
        "The five highest activity scores earn Bullrun Points at 00:00 UTC:\n"
        "🥇 1st: <b>500</b> · 🥈 2nd: <b>350</b> · 🥉 3rd: <b>250</b>\n"
        "4th: <b>150</b> · 5th: <b>100</b>\n\n"
        "Messages count across every group where the bot is present: one "
        "qualifying message every 30 seconds, up to 20 per Bull per UTC day. "
        "The score is global across groups. A completed battle adds 10 activity "
        "score per Bull and a win adds 5 more, up to 5 scored battles daily. "
        "Battles also give each Bull +25 Bullrun Points; the winner gets +50 extra, "
        "up to 5 completed battles daily. PvP works in any group where the bot "
        "is present.\n\n"
        "Only message counts and timestamps are stored, not message text.\n\n"
        "Bull Missions award 200 Bullrun Points for one correct answer per campaign. "
        "A linked X account must Like and Repost the campaign post, Reply to "
        "it, and Follow its author before the points are awarded. "
        "Weekly token reward payouts are not available yet."
    ),
    "help": (
        "📜 <b>GOLDEN BULLRUN — HOW TO PLAY</b>\n\n"
        "<b>1. Register and check your Bullrun Points</b>\n"
        "Send /start in a group with the bot or in the bot's private chat. "
        "A new Bull starts with 10,000 Bullrun Points. Use /profile "
        "to see your Bull Profile or /balance to check your points. Only Bullrun "
        "Points are used for Bull Arena stakes and rankings; purchased credits are separate.\n\n"
        "<b>2. Challenge a Bull in the group</b>\n"
        "The Bull Arena works in any active group where the bot is present. Send "
        "<code>/pvp @username amount</code>, for example "
        "<code>/pvp @player 100</code>. The amount is the stake from each "
        "Bull and must be between 1 and 1,000,000 Bullrun Points. Both Bulls need "
        "enough Bullrun Points. You cannot challenge yourself, bots, or "
        "Bulls already in another active match. If a target is not registered, "
        "the bot gives them a Start button to register.\n\n"
        "<b>3. Accept, decline, and battle</b>\n"
        "The challenge is numbered and stays open for 60 seconds. Only the "
        "mentioned opponent can accept or decline. Neither stake is taken "
        "unless the opponent accepts; then both stakes are reserved. The "
        "starting Bull is chosen at random. Each Bull starts with 100 HP "
        "and takes turns. ATTACK deals 20 damage. Each Bull can use GUARD "
        "once per battle to reduce the next incoming hit by 10. The first "
        "Bull to reach 0 HP loses; the winner receives both reserved stakes "
        "and is crowned 🏆 The Bull That Ran. "
        "Either Bull can forfeit, awarding the pot to the other. "
        "An inactive battle expires after 15 minutes and refunds both stakes.\n\n"
        "<b>4. Earn activity rewards</b>\n"
        "Activity is counted across registered groups. Qualifying messages "
        "count at most once every 30 seconds, up to 20 per Bull per UTC day. "
        "At 00:00 UTC, the top five activity scores receive 500, 350, 250, "
        "150, and 100 Bullrun Points. Completed battles can also earn both "
        "Bulls +25 Bullrun Points and the winner +50 extra, for up to five completed "
        "battles per Bull each day.\n\n"
        "<b>5. Complete Bull Missions</b>\n"
        "Use /missions to view the active X post and quiz. Read the post, tap "
        "the answer button, then reply with your answer. Before claiming, "
        "connect your X account and Like and Repost the campaign post, Reply "
        "to it, and Follow its author. After all four actions are verified, "
        "a correct answer earns 200 Bullrun Points once per campaign; "
        "you have up to three answer attempts. Use /unlinkx to disconnect. "
        "A group administrator can start a quiz with "
        "<code>/setraid https://x.com/name/status/POST_ID | question | answer</code> "
        "and stop it with /stopraid.\n\n"
        "<b>6. Shop and protect your account</b>\n"
        "Purchases and payment checkout happen in the bot's private chat, not "
        "in the group. Follow the bot's checkout instructions; payments are "
        "verified before credits are added. Bull Protection details, rank, "
        "and price are shown in the menu. Protection does not prevent Bull Arena "
        "losses. Weekly token payouts are not available yet."
    ),
}


def get_section_text(section: str) -> str:
    return SECTIONS[section]


def profile_text(player: dict) -> str:
    username = (
        f"@{escape(player['username'])}" if player["username"] else "Not set"
    )
    return (
        "🐂 <b>YOUR BULL PROFILE</b>\n\n"
        f"Bull: <b>{escape(player['name'])}</b>\n"
        f"Username: {username}\n"
        f"💰 Bullrun Points: <b>{player['points']:,}</b>\n"
        f"🎖️ Bull Rank: <b>{bull_rank(player['points'])}</b>\n"
        f"🏆 Wins as The Bull That Ran: <b>{player.get('wins', 0):,}</b>"
    )


def group_play_text() -> str:
    return (
        "⚔️ <b>BULL ARENA</b>\n\n"
        "Challenge a Bull in this group with:\n"
        "<code>/pvp @username 100</code>\n\n"
        "Replace @username with their Telegram username and 100 with the "
        "Bullrun Points you want to stake. Only that Bull can accept the challenge. "
        "If they are not registered yet, they can tap the Start button in the "
        "group prompt to register.\n\n"
        "Purchases are handled privately."
    )


def get_payment_status_text() -> str:
    if payments_configured():
        return (
            "✅ Checkout is enabled. Payments are verified on Solana before delivery."
        )
    return (
        "🔒 Checkout is currently unavailable. Do not send tokens outside the bot's checkout."
    )


SHOP_TEXT = (
    "🪙 <b>GOLDEN BULLRUN — BULLRUN SHOP</b>\n\n"
    "Choose a package to see its details.\n"
    "Credits and Bullrun Points are tracked separately.\n\n"
    "⚡ <b>Starter:</b> 10,000 credits · 5,000 $GOLD\n"
    "⚔️ <b>Warrior:</b> 22,000 credits · 10,000 $GOLD\n"
    "🛡️ <b>Champion:</b> 36,000 credits · 15,000 $GOLD\n"
    "👑 <b>Royal:</b> 52,000 credits · 20,000 $GOLD\n"
    "💎 <b>Legend:</b> 70,000 credits · 25,000 $GOLD\n\n"
    "🛡️ <b>Bull Protection:</b> starting at 30,000 $GOLD for 7 days.\n"
    "<i>Price and Bullrun Points preserved rise with permanent protection rank (max rank 5; 150,000 $GOLD). It never prevents Bull Arena losses.</i>\n\n"
    "Select an option below."
)

PROTECTION_TEXT = (
    "🛡️ <b>BULL PROTECTION</b>\n\n"
    "Build a permanent protection rank to preserve more Bullrun Points at the weekly reset.\n\n"
    "💎 Starting price: <b>30,000 $GOLD</b>; each rank costs more, capped at <b>150,000 $GOLD</b>.\n"
    "⏳ Each activation lasts <b>7 days</b>; maximum rank: <b>5</b>.\n\n"
    "Protection does not cover Bullrun Points lost in the Bull Arena or override other game rules.\n"
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
            "🛡️ <b>BULL PROTECTION</b>\n\n"
            "🟢 <b>Status: ACTIVE</b>\n"
            f"🛡️ Rank: <b>{status['rank']}/5</b> · "
            f"weekly Bullrun Points preserved: <b>{status['protected_percentage']}%</b> "
            "above 10,000\n"
            f"💎 Next activation: <b>{status['price']:,} $GOLD</b>\n"
            f"⏳ Expires: <b>{expiry_text}</b>\n\n"
            "The protected share is based on Bullrun Points above the 10,000 baseline.\n"
            "Bull Arena losses are not protected."
        )
    else:
        text = (
            PROTECTION_TEXT
            + "\n\n"
            + f"🔴 <b>Status: INACTIVE</b>\n"
            f"🛡️ Permanent rank: <b>{status['rank']}/5</b>\n"
            f"💎 Next activation: <b>{status['price']:,} $GOLD</b>"
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
        if message.from_user is None:
            await message.answer("Use /start in a group chat to register.")
            return
        player = await register_player(message.from_user)
        text = (
            f"🐂 <b>Welcome back, {escape(player['name'])}</b>\n"
            f"💰 Your Bullrun Points: <b>{player['points']:,}</b>\n\n"
            f"{group_play_text()}"
        )
        await message.answer(
            text,
            reply_markup=private_shop_link(),
            parse_mode="HTML",
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

    if start_arg == "connectx":
        try:
            authorization_url = await create_x_authorization_url(
                message.from_user.id
            )
        except XOAuthError as exc:
            await message.answer(str(exc))
            return
        await message.answer(
            "🔗 <b>Connect your X account</b>\n\n"
            "Authorize Golden Bullrun to read your liked posts, reposts, "
            "replies, follows, and public profile. The bot will never post "
            "or follow on your behalf.",
            reply_markup=x_authorization_menu(authorization_url),
            parse_mode="HTML",
        )
        return

    if start_arg == "missions":
        from app.handlers.raids import send_raid_screen

        await send_raid_screen(message, message.from_user.id)
        return

    await message.answer(
        f"🐂 <b>GOLDEN BULLRUN</b>\n<i>“{TAGLINE}”</i>\n\n"
        f"Welcome to Golden Bullrun, {escape(player['name'])}.\n"
        f"💰 Your Bullrun Points: <b>{player['points']:,}</b>\n\n"
        "👇 Choose your next move.",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


@router.message(Command("menu"))
async def menu_command(message: Message):
    if message.chat.type != "private":
        if message.from_user:
            await register_player(message.from_user)
        await message.answer(
            group_play_text(),
            reply_markup=private_shop_link(),
            parse_mode="HTML",
        )
        return
    await show_home(message)


@router.message(Command("profile"))
async def profile_command(message: Message):
    player = await get_player(message.from_user.id)
    if player is None:
        await message.answer("Send /start first to register.")
        return

    await message.answer(
        profile_text(player),
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
        f"💰 <b>Your Bullrun Points:</b> {player['points']:,}",
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


@router.message(Command("gold", "token"))
async def token_command(message: Message):
    await message.answer(
        TOKEN_TEXT,
        reply_markup=token_menu(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(Command("about"))
async def about_command(message: Message):
    await message.answer(
        SECTIONS["about"],
        reply_markup=back_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == CLOSE_CALLBACK)
async def close_callback(callback: CallbackQuery):
    message = callback.message
    if message is None:
        await callback.answer()
        return

    if message.chat.type != "private":
        try:
            member = await callback.bot.get_chat_member(
                message.chat.id, callback.from_user.id
            )
        except TelegramAPIError:
            await callback.answer("Could not verify your permissions.", show_alert=True)
            return
        if member.status not in {
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.ADMINISTRATOR,
        }:
            await callback.answer(
                "Only group admins can close this message.", show_alert=True
            )
            return

    try:
        await message.delete()
    except TelegramAPIError:
        try:
            await message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
    await callback.answer("Closed.")


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
                "🛡️ View Bull Protection privately in the bot.",
                reply_markup=private_protection_link(),
            )
        await callback.answer()
        return

    if section == "play" and chat_type != "private":
        if callback.from_user:
            await register_player(callback.from_user)
        await callback.message.answer(
            group_play_text(),
            reply_markup=private_shop_link(),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    if section == "home":
        if chat_type != "private":
            if callback.from_user:
                await register_player(callback.from_user)
            await callback.message.edit_text(
                group_play_text(),
                reply_markup=private_shop_link(),
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(
                WELCOME_TEXT, reply_markup=main_menu(), parse_mode="HTML"
            )
    elif section == "profile":
        player = await get_player(callback.from_user.id)
        if player is None:
            await callback.answer(
                "Send /start in this group or the bot first.",
                show_alert=True,
            )
            return

        await callback.message.edit_text(
            profile_text(player),
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
                "Open Bull Protection in the bot's private chat.",
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
                "🏆 <b>TOP BULLS</b>\n\n"
                "No Bulls are registered yet. Send /start to join."
            )
        else:
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            lines = [
                "🏆 <b>TOP BULLS</b>",
                "",
                "Ranked by Bullrun Points:",
                "",
            ]
            entries = []

            for player in players:
                rank = player["rank"]
                marker = medals.get(rank, f"{rank}.")
                name = escape(player["name"] or "Bull")
                if player["username"]:
                    display_name = f"{name} (@{escape(player['username'])})"
                else:
                    display_name = name

                entries.append(
                    f"{marker} <b>{display_name}</b>\n"
                    f"   💰 <b>{player['points']:,}</b> Bullrun Points"
                    f" · 🏆 {player.get('wins', 0):,} wins"
                )

            leaderboard_text = (
                "\n".join(lines)
                + "\n\n"
                + "\n\n".join(entries)
                + "\n\n━━━━━━━━━━━━━━━━━━\n"
                "🏅 Rankings use Bullrun Points only.\n"
                "🪙 Purchased credits do not increase your rank."
            )

        await callback.message.edit_text(
            leaderboard_text,
            reply_markup=back_menu(),
            parse_mode="HTML",
        )
    elif section == "token":
        await callback.message.edit_text(
            TOKEN_TEXT,
            reply_markup=token_menu(),
            parse_mode="HTML",
            disable_web_page_preview=True,
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


@router.callback_query(F.data == "group:play")
async def group_play_callback(callback: CallbackQuery):
    if callback.message is None:
        await callback.answer("This game post is unavailable.", show_alert=True)
        return
    if callback.message.chat.type == "private":
        await callback.answer("Use /pvp in the game group to challenge a Bull.")
        return

    player = await register_player(callback.from_user)
    await callback.message.answer(
        f"⚔️ <b>THE ARENA IS OPEN, {escape(player['name'])}</b>\n\n"
        "Challenge a rival Bull here:\n"
        "<code>/pvp @username 100</code>\n\n"
        "Replace the username and stake with your opponent and wager. "
        "Only the mentioned Bull can accept. Both Bulls need to register "
        "with /start in a group or in the bot.",
        reply_markup=private_shop_link(),
        parse_mode="HTML",
    )
    await callback.answer()
