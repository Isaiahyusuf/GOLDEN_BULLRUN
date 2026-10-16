import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    ForceReply,
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
    REQUIRED_X_ACTIONS,
    XRaidError,
    get_active_campaign,
    get_claim_status,
    is_quiz_answer_correct,
    record_verified_actions,
    set_campaign,
    stop_campaign,
    submit_quiz_answer,
)
from app.services.x_oauth_service import (
    X_ACTION_LABELS,
    XOAuthError,
    create_x_authorization_url,
    get_linked_x_username,
    unlink_x_account,
    verify_campaign_actions,
    x_oauth_configured,
)
from app.keyboards.main_menu import (
    private_x_connect_link,
    x_authorization_menu,
)


router = Router()


class RaidAdminCheckError(Exception):
    pass


class QuizAnswer(StatesGroup):
    waiting = State()


def raid_keyboard(
    *,
    chat_type: str,
    linked_x: bool,
    verification_ready: bool,
) -> InlineKeyboardMarkup:
    rows = []
    if verification_ready:
        rows.append(
            [InlineKeyboardButton(
                text="🧠 ANSWER RAID QUIZ",
                callback_data="raid:answer",
            )]
        )
        if not linked_x:
            if chat_type == "private":
                rows.append(
                    [InlineKeyboardButton(
                        text="🔗 CONNECT X ACCOUNT",
                        callback_data="x:connect",
                    )]
                )
            else:
                rows.append(
                    [InlineKeyboardButton(
                        text="🔗 CONNECT X IN PRIVATE CHAT",
                        url=private_x_connect_link(),
                    )]
                )
    rows.append(
        [InlineKeyboardButton(
            text="🏠 MAIN MENU",
            callback_data="menu:home",
        )]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
            "A group admin can start one here with:\n"
            "<code>/setraid https://x.com/name/status/POST_ID | "
            "Question about the post? | correct answer</code>\n"
            "Stop it with <code>/stopraid</code>."
        )
    else:
        status = await get_claim_status(campaign.id, telegram_id)
        linked_x_username = await get_linked_x_username(telegram_id)
        verification_ready = x_oauth_configured()
        text = (
            "🎯 <b>ACTIVE X POST QUIZ</b>\n\n"
            f"Read the <a href=\"{escape(campaign.post_url, quote=True)}\">X post</a>, "
            "then answer the question here in the group or bot.\n\n"
            f"<b>Question:</b> {escape(campaign.quiz_question)}\n\n"
            f"Correct answer reward: <b>{QUIZ_REWARD_POINTS} points</b> "
            f"(one claim per campaign; {MAX_QUIZ_ATTEMPTS} attempts).\n"
            "To claim points, connect your X account and Like and Repost this "
            "post, Reply to it, and Follow its author."
        )
        if linked_x_username:
            text += f"\n\n🔗 Connected X account: <b>@{escape(linked_x_username)}</b>."
        if not verification_ready:
            text += (
                "\n\n⚠️ X verification is not configured. Quiz rewards are "
                "unavailable until the bot administrator completes setup."
            )
        if status["awarded_points"]:
            text += "\n\n✅ You already claimed this quiz reward."
        elif status["attempts"] >= MAX_QUIZ_ATTEMPTS:
            text += "\n\n❌ You used all attempts for this quiz."

    if edit:
        await target.edit_text(
            text,
            reply_markup=(
                raid_keyboard(
                    chat_type=target.chat.type,
                    linked_x=bool(linked_x_username),
                    verification_ready=verification_ready,
                )
                if campaign
                else None
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        await target.answer(
            text,
            reply_markup=(
                raid_keyboard(
                    chat_type=target.chat.type,
                    linked_x=bool(linked_x_username),
                    verification_ready=verification_ready,
                )
                if campaign
                else None
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@router.message(Command("missions"))
async def missions_command(message: Message):
    await send_raid_screen(message, message.from_user.id)


@router.message(Command("setraid"))
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
    if not x_oauth_configured():
        await message.answer(
            "X verification is not configured yet. The administrator must "
            "configure the X API app and callback in Railway before starting "
            "a reward quiz."
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


@router.message(Command("stopraid"))
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
    if callback.message is None:
        await callback.answer("This message is unavailable.", show_alert=True)
        return
    await send_raid_screen(callback.message, callback.from_user.id, edit=True)
    await callback.answer()


@router.callback_query(F.data == "raid:answer")
async def begin_quiz_answer(callback: CallbackQuery, state: FSMContext):
    if callback.message is None:
        await callback.answer("This message is unavailable.", show_alert=True)
        return

    campaign = await get_active_campaign()
    if campaign is None:
        await callback.answer("There is no active X quiz.", show_alert=True)
        return
    if not x_oauth_configured():
        await callback.answer(
            "X verification is not configured. Quiz rewards are unavailable.",
            show_alert=True,
        )
        return

    if await get_linked_x_username(callback.from_user.id) is None:
        await callback.answer(
            "Connect your X account first using the Connect X button.",
            show_alert=True,
        )
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
    await callback.message.answer(
        f"<b>Raid quiz</b>\n\n{escape(campaign.quiz_question)}\n\n"
        f"Reply to this message with your answer. You have "
        f"{MAX_QUIZ_ATTEMPTS - status['attempts']} attempt(s) left. "
        "Use /cancel to leave.",
        reply_markup=ForceReply(
            selective=True,
            input_field_placeholder="Your answer",
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "x:connect")
async def connect_x_account(callback: CallbackQuery):
    if callback.message is None or callback.message.chat.type != "private":
        await callback.answer(
            "Connect X from the bot's private chat.",
            show_alert=True,
        )
        return

    try:
        authorization_url = await create_x_authorization_url(
            callback.from_user.id
        )
    except XOAuthError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.message.answer(
        "🔗 <b>Connect your X account</b>\n\n"
        "Authorize TRUMPTY ROYALE to read your liked posts, reposts, "
        "replies, follows, and public profile. The bot will never post "
        "or follow on your behalf.",
        reply_markup=x_authorization_menu(authorization_url),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(Command("unlinkx"))
async def unlink_x_command(message: Message):
    if message.from_user is None:
        await message.answer("Could not identify the command sender.")
        return

    if await unlink_x_account(message.from_user.id):
        await message.answer(
            "Your X account has been disconnected and its stored tokens deleted."
        )
    else:
        await message.answer("You do not have a connected X account.")


@router.message(Command("cancel"), QuizAnswer.waiting)
async def cancel_quiz_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Quiz cancelled. Open Missions whenever you are ready.")


@router.message(QuizAnswer.waiting, F.text)
async def receive_quiz_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, int):
        await state.clear()
        await message.answer("Quiz session expired. Open Missions to try again.")
        return

    if message.from_user is None:
        await state.clear()
        await message.answer("Could not identify the quiz player.")
        return

    try:
        status = await get_claim_status(campaign_id, message.from_user.id)
        if status["awarded_points"]:
            result = {
                "status": "already_claimed",
                "points_awarded": 0,
                "attempts_left": max(
                    0, MAX_QUIZ_ATTEMPTS - status["attempts"]
                ),
            }
        elif status["attempts"] >= MAX_QUIZ_ATTEMPTS:
            result = {
                "status": "locked",
                "points_awarded": 0,
                "attempts_left": 0,
            }
        elif await is_quiz_answer_correct(campaign_id, message.text):
            verified_actions = await verify_campaign_actions(
                campaign_id,
                message.from_user.id,
            )
            await record_verified_actions(
                campaign_id,
                message.from_user.id,
                verified_actions,
            )
            missing_actions = [
                X_ACTION_LABELS[action]
                for action in REQUIRED_X_ACTIONS
                if not verified_actions[action]
            ]
            if missing_actions:
                await state.clear()
                await message.answer(
                    "✅ Your quiz answer is correct, but these X actions "
                    "still need to be completed:\n"
                    + "\n".join(f"• {action}" for action in missing_actions)
                    + "\n\nComplete them, then answer the quiz again. "
                    "This check did not use an answer attempt."
                )
                return
            result = await submit_quiz_answer(
                campaign_id,
                message.from_user.id,
                message.text,
                verified_actions,
            )
        else:
            result = await submit_quiz_answer(
                campaign_id,
                message.from_user.id,
                message.text,
                {action: False for action in REQUIRED_X_ACTIONS},
            )
    except XRaidError as exc:
        await state.clear()
        await message.answer(str(exc))
        return
    except XOAuthError as exc:
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
        reply_markup=raid_keyboard(
            chat_type=message.chat.type,
            linked_x=(
                await get_linked_x_username(message.from_user.id)
            ) is not None,
            verification_ready=x_oauth_configured(),
        ),
        parse_mode="HTML",
    )
