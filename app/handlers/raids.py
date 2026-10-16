import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from sqlalchemy import select

from app.config import settings
from app.database.connection import SessionLocal
from app.models.group import TelegramGroup
from app.services.x_raid_service import (
    MAX_QUIZ_ATTEMPTS,
    QUIZ_REWARD_POINTS,
    XRaidError,
    get_active_campaign,
    get_claim_status,
    set_campaign,
    stop_campaign,
    submit_quiz_answer,
)


router = Router()


class RaidAdminCheckError(Exception):
    pass


class QuizAnswer(StatesGroup):
    waiting = State()


def raid_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🧠 ANSWER RAID QUIZ",
                callback_data="raid:answer",
            )],
            [InlineKeyboardButton(
                text="🏠 MAIN MENU",
                callback_data="menu:home",
            )],
        ]
    )


def quiz_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="CANCEL",
                callback_data="raid:cancel",
            )]
        ]
    )


async def is_raid_admin(bot: Bot, telegram_id: int) -> bool:
    if telegram_id in settings.admin_ids:
        return True

    async with SessionLocal() as session:
        group_ids = list(
            (
                await session.scalars(
                    select(TelegramGroup.chat_id).where(
                        TelegramGroup.active.is_(True)
                    )
                )
            ).all()
        )

    check_failures = 0
    for chat_id in group_ids:
        try:
            member = await bot.get_chat_member(chat_id, telegram_id)
        except TelegramAPIError:
            check_failures += 1
            logging.exception(
                "Could not check raid-admin status for user %s in group %s",
                telegram_id,
                chat_id,
            )
            continue
        if member.status in {
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.ADMINISTRATOR,
        }:
            return True

    if check_failures:
        raise RaidAdminCheckError(
            "Could not verify your group-admin status. Make sure the bot is an "
            "administrator in the group and try again."
        )
    return False


async def send_raid_screen(
    target: Message,
    telegram_id: int,
    *,
    edit: bool = False,
) -> None:
    campaign = await get_active_campaign()
    if campaign is None:
        text = (
            "🎯 <b>X RAID MISSIONS</b>\n\n"
            "No X quiz is active right now.\n\n"
            "Admins can start one with:\n"
            "<code>/setraid https://x.com/name/status/POST_ID | "
            "Question about the post? | correct answer</code>\n"
            "Stop it with <code>/stopraid</code>."
        )
    else:
        status = await get_claim_status(campaign.id, telegram_id)
        text = (
            "🎯 <b>ACTIVE X POST QUIZ</b>\n\n"
            f"Read the <a href=\"{escape(campaign.post_url, quote=True)}\">X post</a>, "
            "then answer the question here in the bot.\n\n"
            f"<b>Question:</b> {escape(campaign.quiz_question)}\n\n"
            f"Correct answer reward: <b>{QUIZ_REWARD_POINTS} points</b> "
            f"(one claim per campaign; {MAX_QUIZ_ATTEMPTS} attempts).\n"
            "Points are for the quiz only; no like, repost, reply, or follow is required."
        )
        if status["awarded_points"]:
            text += "\n\n✅ You already claimed this quiz reward."
        elif status["attempts"] >= MAX_QUIZ_ATTEMPTS:
            text += "\n\n❌ You used all attempts for this quiz."

    if edit:
        await target.edit_text(
            text,
            reply_markup=raid_keyboard() if campaign else None,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        await target.answer(
            text,
            reply_markup=raid_keyboard() if campaign else None,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@router.message(Command("missions"), F.chat.type == ChatType.PRIVATE)
async def missions_command(message: Message):
    await send_raid_screen(message, message.from_user.id)


@router.message(Command("setraid"), F.chat.type == ChatType.PRIVATE)
async def set_raid_command(message: Message):
    if not message.from_user:
        await message.answer("Could not identify the command sender.")
        return
    try:
        authorized = await is_raid_admin(message.bot, message.from_user.id)
    except RaidAdminCheckError as exc:
        await message.answer(str(exc))
        return
    if not authorized:
        await message.answer(
            "Only an administrator of a group where the bot is present can "
            "start an X quiz."
        )
        return

    content = (message.text or "").partition(" ")[2]
    parts = [part.strip() for part in content.split("|")]
    if len(parts) != 3:
        await message.answer(
            "Use:\n<code>/setraid https://x.com/name/status/POST_ID | "
            "Question about the post? | correct answer</code>",
            parse_mode="HTML",
        )
        return

    try:
        campaign = await set_campaign(
            message.from_user.id,
            parts[0],
            parts[1],
            parts[2],
        )
    except XRaidError as exc:
        await message.answer(str(exc))
        return

    await message.answer(
        "✅ X post quiz is active.\n"
        f"Post: {campaign.post_url}\n"
        f"Question: {campaign.quiz_question}\n"
        f"Reward: {QUIZ_REWARD_POINTS} points for a correct answer "
        f"(up to {MAX_QUIZ_ATTEMPTS} attempts)."
    )


@router.message(Command("stopraid"), F.chat.type == ChatType.PRIVATE)
async def stop_raid_command(message: Message):
    if not message.from_user:
        await message.answer("Could not identify the command sender.")
        return
    try:
        authorized = await is_raid_admin(message.bot, message.from_user.id)
    except RaidAdminCheckError as exc:
        await message.answer(str(exc))
        return
    if not authorized:
        await message.answer(
            "Only an administrator of a group where the bot is present can "
            "stop an X quiz."
        )
        return

    if await stop_campaign():
        await message.answer("The active X post quiz has been stopped.")
    else:
        await message.answer("There is no active X quiz to stop.")


@router.callback_query(F.data == "raid:screen")
async def show_raid_screen_callback(callback: CallbackQuery):
    if callback.message is None or callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer(
            "Open Missions in the bot's private chat.",
            show_alert=True,
        )
        return
    await send_raid_screen(callback.message, callback.from_user.id, edit=True)
    await callback.answer()


@router.callback_query(F.data == "raid:answer")
async def begin_quiz_answer(callback: CallbackQuery, state: FSMContext):
    if callback.message is None or callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer(
            "Answer the raid quiz in the bot's private chat.",
            show_alert=True,
        )
        return

    campaign = await get_active_campaign()
    if campaign is None:
        await callback.answer("There is no active X quiz.", show_alert=True)
        return

    status = await get_claim_status(campaign.id, callback.from_user.id)
    if status["awarded_points"]:
        await callback.answer("You already claimed this quiz reward.", show_alert=True)
        return
    if status["attempts"] >= MAX_QUIZ_ATTEMPTS:
        await callback.answer("You used all attempts for this quiz.", show_alert=True)
        return

    await state.set_state(QuizAnswer.waiting)
    await state.update_data(campaign_id=campaign.id)
    await callback.message.edit_text(
        f"<b>Raid quiz</b>\n\n{escape(campaign.quiz_question)}\n\n"
        f"Send your answer as a message. You have "
        f"{MAX_QUIZ_ATTEMPTS - status['attempts']} attempt(s) left. "
        "Use /cancel to leave.",
        reply_markup=quiz_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "raid:cancel", QuizAnswer.waiting)
async def cancel_quiz_answer(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.message is not None and callback.message.chat.type == ChatType.PRIVATE:
        await send_raid_screen(callback.message, callback.from_user.id, edit=True)
    await callback.answer("Quiz cancelled.")


@router.message(Command("cancel"), QuizAnswer.waiting)
async def cancel_quiz_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Quiz cancelled. Open Missions whenever you are ready.")


@router.message(QuizAnswer.waiting, F.chat.type == ChatType.PRIVATE, F.text)
async def receive_quiz_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, int):
        await state.clear()
        await message.answer("Quiz session expired. Open Missions to try again.")
        return

    try:
        result = await submit_quiz_answer(
            campaign_id,
            message.from_user.id,
            message.text,
        )
    except XRaidError as exc:
        await state.clear()
        await message.answer(str(exc))
        return

    await state.clear()
    if result["status"] == "correct":
        response = f"✅ Correct! <b>+{result['points_awarded']} points</b> added."
    elif result["status"] == "already_claimed":
        response = "You already claimed this quiz reward."
    elif result["status"] == "locked":
        response = "You used all attempts for this quiz."
    else:
        response = (
            "❌ That answer is not correct. "
            f"{result['attempts_left']} attempt(s) left."
        )

    await message.answer(
        response,
        reply_markup=raid_keyboard(),
        parse_mode="HTML",
    )
