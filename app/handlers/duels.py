from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, select

from app.database.connection import SessionLocal
from app.models.user import User
from app.services.duel_service import (
    DuelError,
    accept_duel,
    create_duel,
    submit_choice,
)

router = Router()
GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}


def accept_keyboard(duel_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚔️ ACCEPT DUEL",
                    callback_data=f"duel:accept:{duel_id}",
                )
            ]
        ]
    )


def move_keyboard(duel_id: int, round_number: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚔️ ATTACK",
                    callback_data=f"duel:move:{duel_id}:{round_number}:attack",
                ),
                InlineKeyboardButton(
                    text="🛡 DEFEND",
                    callback_data=f"duel:move:{duel_id}:{round_number}:defend",
                ),
            ]
        ]
    )


async def player_name(player_id: int) -> str:
    async with SessionLocal() as session:
        player = await session.get(User, player_id)
        return player.full_name if player else str(player_id)


@router.message(Command("pvp", "duel"))
async def start_duel(message: Message):
    if message.chat.type not in GROUP_TYPES:
        await message.answer("Start PvP challenges in a group where the bot is present.")
        return

    if message.from_user is None:
        return

    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[1].startswith("@"):
        await message.answer(
            "Use: /pvp @username points\n"
            "Example: /pvp @player 100"
        )
        return

    username = parts[1].lstrip("@").lower()
    try:
        wager = int(parts[2])
    except ValueError:
        await message.answer("The wager must be a whole number of points.")
        return

    async with SessionLocal() as session:
        opponent = await session.scalar(
            select(User).where(func.lower(User.username) == username)
        )

    if opponent is None:
        await message.answer(
            "That player isn't registered yet. Ask them to tap Start below to "
            "register, then you can challenge them.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🚀 TAP START TO REGISTER",
                            url="https://t.me/TrumptyDumptybot?start=register",
                        )
                    ]
                ]
            ),
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

    challenger_name = message.from_user.full_name
    await message.answer(
        f"⚔️ TRUMPTY ROYALE DUEL #{duel_id}\n\n"
        f"{challenger_name} challenges @{username}.\n"
        f"Wager: {wager:,} points each\n"
        "First to 2 round wins takes the pot.\n"
        "If the score is tied after 3 rounds, both wagers are refunded.\n\n"
        "Each completed duel can earn +25 participation points; the winner "
        "earns +50 extra. Bonuses are limited to 5 completed duels per player "
        "each UTC day.\n\n"
        f"Only @{username} can accept this challenge.",
        reply_markup=accept_keyboard(duel_id),
    )


@router.callback_query(F.data.startswith("duel:accept:"))
async def accept_duel_button(callback: CallbackQuery):
    if callback.message is None or callback.data is None:
        await callback.answer("This duel message is unavailable.", show_alert=True)
        return

    try:
        duel_id = int(callback.data.split(":")[2])
        result = await accept_duel(
            duel_id=duel_id,
            accepting_user_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
        )
    except (ValueError, IndexError):
        await callback.answer("Invalid duel button.", show_alert=True)
        return
    except DuelError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.message.edit_text(
        f"⚔️ DUEL #{duel_id} IS ON!\n\n"
        f"Wager locked: {result['wager']:,} points each.\n"
        "Choose ATTACK or DEFEND. Your choice is hidden until both players move.\n"
        "First to 2 round wins takes the pot.",
        reply_markup=move_keyboard(duel_id, 1),
    )
    await callback.answer("Duel accepted!")


@router.callback_query(F.data.startswith("duel:move:"))
async def duel_move_button(callback: CallbackQuery):
    if callback.message is None or callback.data is None:
        await callback.answer("This duel message is unavailable.", show_alert=True)
        return

    try:
        _, _, duel_id_text, round_text, choice = callback.data.split(":")
        duel_id = int(duel_id_text)
        expected_round = int(round_text)

        result = await submit_choice(
            duel_id=duel_id,
            player_id=callback.from_user.id,
            choice=choice,
            chat_id=callback.message.chat.id,
            expected_round=expected_round,
        )
    except (ValueError, IndexError):
        await callback.answer("Invalid move button.", show_alert=True)
        return
    except DuelError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    if result["status"] == "waiting":
        await callback.answer("Move locked. Waiting for the other player.")
        return

    score = result["score"]
    score_text = (
        f"Score: Challenger {score['challenger']} – "
        f"Opponent {score['opponent']}"
    )

    if result["status"] == "next_round":
        await callback.message.edit_text(
            f"⚔️ DUEL #{duel_id} — ROUND {result['next_round']}\n\n"
            f"{score_text}\n"
            "Both players: choose your next move.\n"
            "Moves remain hidden until both have chosen.",
            reply_markup=move_keyboard(duel_id, result["next_round"]),
        )
        await callback.answer("Round complete.")
        return

    if result["status"] == "draw":
        await callback.message.edit_text(
            f"🤝 DUEL #{duel_id} — DRAW\n\n"
            f"{score_text}\n"
            "Both wagers have been refunded.\n"
            "Eligible players also receive +25 daily activity points."
        )
        await callback.answer("Draw — wagers refunded.")
        return

    winner = await player_name(result["winner_id"])
    await callback.message.edit_text(
        f"🏆 DUEL #{duel_id} — {winner} WINS!\n\n"
        f"{score_text}\n"
        f"Prize: {result['prize']:,} points.\n"
        "Eligible players receive +25 activity points; the winner gets +50 extra."
    )
    await callback.answer("Duel complete!")
