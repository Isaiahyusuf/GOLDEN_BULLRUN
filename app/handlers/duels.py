import logging
import re

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMemberRestricted,
    Message,
)
from sqlalchemy import func, select

from app.database.connection import SessionLocal
from app.models.user import User
from app.services.duel_service import (
    ATTACK_DAMAGE,
    GUARD_REDUCTION,
    DuelError,
    accept_duel,
    create_duel,
    decline_duel,
    forfeit_duel,
    submit_move,
)

router = Router()
GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}
USERNAME_PATTERN = re.compile(r"@[A-Za-z][A-Za-z0-9_]{4,31}\Z")


def registration_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 TAP START TO REGISTER",
                    url="https://t.me/TrumptyDumptybot?start=register",
                )
            ]
        ]
    )


def challenge_keyboard(duel_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚔️ ACCEPT",
                    callback_data=f"duel:accept:{duel_id}",
                ),
                InlineKeyboardButton(
                    text="❌ DECLINE",
                    callback_data=f"duel:decline:{duel_id}",
                ),
            ]
        ]
    )


def battle_keyboard(duel_id: int, turn_number: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚔️ ATTACK",
                    callback_data=f"duel:move:{duel_id}:{turn_number}:attack",
                ),
                InlineKeyboardButton(
                    text="🛡 GUARD (ONCE)",
                    callback_data=f"duel:move:{duel_id}:{turn_number}:guard",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏳️ FORFEIT",
                    callback_data=f"duel:forfeit:{duel_id}",
                ),
            ]
        ]
    )


def challenge_text(
    duel_id: int,
    challenger_name: str,
    opponent_name: str,
    wager: int,
) -> str:
    return (
        f"⚔️ TRUMPTY ROYALE — DUEL #{duel_id}\n\n"
        "DUEL CHALLENGE\n\n"
        f"Challenger: {challenger_name}\n"
        f"Opponent: {opponent_name}\n"
        f"Stake: {wager:,} points each\n"
        "Battle mode: Turn-based (100 HP, 20 damage per attack; one guard "
        "reduces a hit by 10)\n"
        "Expires: 60 seconds\n\n"
        f"Only {opponent_name} can accept or decline."
    )


async def player_name(player_id: int) -> str:
    async with SessionLocal() as session:
        player = await session.get(User, player_id)
        if player is None:
            return str(player_id)
        return f"@{player.username}" if player.username else player.full_name


@router.message(Command("pvp"))
async def start_duel(message: Message, bot: Bot):
    if message.chat.type not in GROUP_TYPES:
        await message.answer(
            "Start PvP challenges in a registered group where the bot is present."
        )
        return

    if message.from_user is None or message.from_user.is_bot:
        await message.answer("Bots cannot start PvP challenges.")
        return

    parts = (message.text or "").split()
    if (
        len(parts) != 3
        or not USERNAME_PATTERN.fullmatch(parts[1])
        or not parts[2].isascii()
        or not parts[2].isdecimal()
    ):
        await message.answer(
            "Use: /pvp @username amount\n"
            "Example: /pvp @player 100"
        )
        return

    username = parts[1][1:].lower()
    wager = int(parts[2])
    async with SessionLocal() as session:
        opponent = await session.scalar(
            select(User).where(func.lower(User.username) == username)
        )

    if opponent is None:
        await message.answer(
            "That player isn't registered yet. Ask them to tap Start below to "
            "register, then you can challenge them.",
            reply_markup=registration_keyboard(),
        )
        return

    try:
        group_member = await bot.get_chat_member(
            message.chat.id,
            opponent.telegram_id,
        )
    except TelegramAPIError:
        logging.exception(
            "Could not verify PvP target %s in group %s",
            opponent.telegram_id,
            message.chat.id,
        )
        await message.answer(
            "I couldn't verify that player's current Telegram username in this "
            "group. Please try again later or ask a group admin to check that "
            "the bot can view group members."
        )
        return

    if (
        group_member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}
        or (
            isinstance(group_member, ChatMemberRestricted)
            and not group_member.is_member
        )
    ):
        await message.answer("That player must be a member of this group to play.")
        return
    if group_member.user.is_bot or opponent.is_bot:
        await message.answer("Bots cannot participate in PvP.")
        return
    current_username = group_member.user.username
    if current_username is None or current_username.casefold() != username:
        await message.answer(
            "I couldn't verify that username belongs to the registered player. "
            "Ask them to send /start again after updating their username.",
            reply_markup=registration_keyboard(),
        )
        return
    if opponent.telegram_id == message.from_user.id:
        await message.answer("You can't challenge yourself.")
        return

    try:
        duel_id = await create_duel(
            challenger_id=message.from_user.id,
            opponent_id=opponent.telegram_id,
            wager=wager,
            chat_id=message.chat.id,
        )
    except DuelError as exc:
        await message.answer(str(exc))
        return

    challenger_name = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else message.from_user.full_name
    )
    opponent_name = f"@{opponent.username}" if opponent.username else opponent.full_name
    await message.answer(
        challenge_text(
            duel_id,
            challenger_name,
            opponent_name,
            wager,
        ),
        reply_markup=challenge_keyboard(duel_id),
    )


@router.callback_query(F.data.startswith("duel:accept:"))
async def accept_duel_button(callback: CallbackQuery):
    if callback.message is None or callback.data is None:
        await callback.answer("This challenge is unavailable.", show_alert=True)
        return

    try:
        duel_id = int(callback.data.split(":")[2])
        result = await accept_duel(
            duel_id=duel_id,
            accepting_user_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
        )
    except (ValueError, IndexError):
        await callback.answer("Invalid challenge button.", show_alert=True)
        return
    except DuelError as exc:
        if str(exc) == "This challenge has expired." and callback.message:
            await callback.message.edit_text(f"Challenge #{duel_id} has expired.")
        await callback.answer(str(exc), show_alert=True)
        return

    challenger_id, opponent_id = await duel_player_ids(duel_id)
    challenger = await player_name(challenger_id)
    opponent = await player_name(opponent_id)
    first_player = await player_name(result["turn_player_id"])
    await callback.message.edit_text(
        f"⚔️ DUEL #{duel_id} — BATTLE STARTED\n\n"
        f"{challenger}: {result['challenger_health']} HP\n"
        f"{opponent}: {result['opponent_health']} HP\n\n"
        f"{first_player} goes first. Attack deals {ATTACK_DAMAGE} damage; each "
        f"player may guard once to reduce the next hit by {GUARD_REDUCTION}.\n"
        "Each player takes a turn. First to 0 HP loses.",
        reply_markup=battle_keyboard(duel_id, 1),
    )
    await callback.answer("Battle started!")


@router.callback_query(F.data.startswith("duel:decline:"))
async def decline_duel_button(callback: CallbackQuery):
    if callback.message is None or callback.data is None:
        await callback.answer("This challenge is unavailable.", show_alert=True)
        return

    try:
        duel_id = int(callback.data.split(":")[2])
        await decline_duel(
            duel_id=duel_id,
            declining_user_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
        )
    except (ValueError, IndexError):
        await callback.answer("Invalid challenge button.", show_alert=True)
        return
    except DuelError as exc:
        if str(exc) == "This challenge has expired." and callback.message:
            await callback.message.edit_text(f"Challenge #{duel_id} has expired.")
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.message.edit_text(f"Challenge #{duel_id} was declined.")
    await callback.answer("Challenge declined.")


@router.callback_query(F.data.startswith("duel:move:"))
async def move_button(callback: CallbackQuery):
    if callback.message is None or callback.data is None:
        await callback.answer("This battle message is unavailable.", show_alert=True)
        return

    try:
        _, _, duel_id_text, turn_text, action = callback.data.split(":")
        duel_id = int(duel_id_text)
        result = await submit_move(
            duel_id=duel_id,
            player_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
            expected_turn=int(turn_text),
            action=action,
        )
    except (ValueError, IndexError):
        await callback.answer("Invalid battle button.", show_alert=True)
        return
    except DuelError as exc:
        if (
            str(exc).startswith("This battle has expired")
            and callback.message
        ):
            await callback.message.edit_text(
                "This battle expired after inactivity. Both stakes were refunded."
            )
        await callback.answer(str(exc), show_alert=True)
        return

    challenger_id, opponent_id = await duel_player_ids(duel_id)
    challenger = await player_name(challenger_id)
    opponent = await player_name(opponent_id)
    health = result["health"]

    if result["status"] == "settled":
        winner = await player_name(result["winner_id"])
        await callback.message.edit_text(
            f"🏆 DUEL #{duel_id} — {winner} WINS!\n\n"
            f"{challenger}: {health[challenger_id]} HP\n"
            f"{opponent}: {health[opponent_id]} HP\n"
            f"Prize: {result['prize']:,} points."
        )
        await callback.answer("Battle complete!")
        return

    next_player = await player_name(result["turn_player_id"])
    if result["action"] == "guard":
        action_text = f"{next_player}, it's your turn."
    else:
        action_text = (
            f"{result['damage']} damage dealt. {next_player}, it's your turn."
        )
    await callback.message.edit_text(
        f"⚔️ DUEL #{duel_id} — TURN {result['turn']}\n\n"
        f"{challenger}: {health[challenger_id]} HP\n"
        f"{opponent}: {health[opponent_id]} HP\n\n"
        f"{action_text} Attack deals {ATTACK_DAMAGE}; guard once to reduce a hit by "
        f"{GUARD_REDUCTION}.",
        reply_markup=battle_keyboard(duel_id, result["turn"]),
    )
    if result["action"] == "guard":
        await callback.answer("Guard raised; next hit reduced by 10.")
    else:
        await callback.answer(f"Attack landed for {result['damage']} damage.")


@router.callback_query(F.data.startswith("duel:forfeit:"))
async def forfeit_button(callback: CallbackQuery):
    if callback.message is None or callback.data is None:
        await callback.answer("This battle message is unavailable.", show_alert=True)
        return

    try:
        duel_id = int(callback.data.split(":")[2])
        result = await forfeit_duel(
            duel_id=duel_id,
            player_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
        )
    except (ValueError, IndexError):
        await callback.answer("Invalid forfeit button.", show_alert=True)
        return
    except DuelError as exc:
        if (
            str(exc).startswith("This battle has expired")
            and callback.message
        ):
            await callback.message.edit_text(
                "This battle expired after inactivity. Both stakes were refunded."
            )
        await callback.answer(str(exc), show_alert=True)
        return

    winner = await player_name(result["winner_id"])
    challenger_id, opponent_id = await duel_player_ids(duel_id)
    challenger = await player_name(challenger_id)
    opponent = await player_name(opponent_id)
    await callback.message.edit_text(
        f"🏳️ DUEL #{duel_id} — FORFEIT\n\n"
        f"{challenger}: {result['challenger_health']} HP\n"
        f"{opponent}: {result['opponent_health']} HP\n"
        f"{winner} wins. Prize: {result['prize']:,} points."
    )
    await callback.answer("Battle forfeited.")


async def duel_player_ids(duel_id: int) -> tuple[int, int]:
    from app.models.duel import Duel

    async with SessionLocal() as session:
        duel = await session.get(Duel, duel_id)
        if duel is None:
            raise DuelError("Duel not found.")
        return duel.challenger_id, duel.opponent_id
