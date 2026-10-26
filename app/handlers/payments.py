from datetime import timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.services.payment_service import (
    PACKAGES,
    PROTECTION_PACKAGE_ID,
    PaymentServiceError,
    create_purchase_intent,
    get_pending_purchase,
    submit_purchase_signature,
)
from app.services.solana_service import payments_configured
from app.keyboards.main_menu import (
    payment_signature_prompt_menu,
    payment_unavailable_menu,
    payment_verification_error_menu,
    pending_payment_menu,
)
from app.services.protection_service import (
    get_protected_percentage,
    get_protection_status,
)


router = Router()


class PurchaseFlow(StatesGroup):
    waiting_for_wallet = State()
    waiting_for_signature = State()


def payment_confirmation_text(result: dict) -> str:
    if result["package_id"] == PROTECTION_PACKAGE_ID:
        expires_at = result["protection_expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        expiry_text = expires_at.strftime("%d %b %Y, %H:%M UTC")
        return (
            "✅ <b>Protection activated</b>\n\n"
            f"Protection rank: <b>{result['protection_rank']}/5</b>\n"
            f"Bullrun Points preserved at weekly reset: "
            f"<b>{get_protected_percentage(result['protection_rank'])}%</b> "
            "of Bullrun Points above 10,000.\n"
            f"Expires: <b>{expiry_text}</b>\n"
            "Bull Arena losses are not protected.\n\n"
            f"Transaction:\n<code>{result['signature']}</code>"
        )

    return (
        "✅ <b>Payment verified</b>\n\n"
        f"Credits added: <b>{result['credits']:,}</b>\n"
        f"Purchased credits balance: <b>{result['purchased_credits']:,}</b>\n\n"
        f"Transaction:\n<code>{result['signature']}</code>"
    )


def payment_error_text(error: PaymentServiceError) -> str:
    return (
        "Payment not credited: The transaction signature could not be verified.\n\n"
        f"Details: {error}\n\n"
        "If you’ve already sent tokens, do not pay again."
    )


async def pending_purchase_reference(
    telegram_id: int,
    state: FSMContext,
) -> tuple[str | None, dict | None]:
    data = await state.get_data()
    reference = data.get("purchase_reference")
    purchase = await get_pending_purchase(telegram_id, reference)
    if purchase is None and reference is None:
        purchase = await get_pending_purchase(telegram_id)

    if purchase is not None:
        reference = purchase["reference"]
        await state.update_data(purchase_reference=reference)

    return reference, purchase


async def begin_purchase_flow(
    callback: CallbackQuery,
    state: FSMContext,
    package_id: str,
    name: str,
    price: int,
    credits: int | None,
):
    if callback.message is None or callback.message.chat.type != "private":
        await callback.answer(
            "Purchases are handled in the bot's private chat.",
            show_alert=True,
        )
        return

    if not payments_configured():
        await callback.answer(
            "Checkout is not enabled yet. No payment has been requested.",
            show_alert=True,
        )
        return

    await state.clear()
    await state.update_data(package_id=package_id)
    await state.set_state(PurchaseFlow.waiting_for_wallet)

    product_details = (
        f"Credits: <b>{credits:,}</b>\n\n"
        if credits
        else "Protection duration: <b>7 days</b>\n\n"
    )
    if package_id == PROTECTION_PACKAGE_ID:
        status = await get_protection_status(callback.from_user.id)
        next_rank = min(status["rank"] + 1, 5)
        product_details = (
            f"Rank after purchase: <b>{next_rank}/5</b>\n"
            f"Bullrun Points preserved at weekly reset: "
            f"<b>{get_protected_percentage(next_rank)}%</b> of Bullrun Points above "
            f"{10_000:,}.\n"
            "Bull Arena losses are not protected.\n\n"
        )
    await callback.message.edit_text(
        f"🪙 <b>{name}</b>\n\n"
        f"Price: <b>{price:,} $GOLD</b>\n"
        f"{product_details}"
        "Send the public Solana wallet address you will pay from.\n"
        "Never send a seed phrase or private key.",
        reply_markup=payment_unavailable_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy:"))
async def begin_purchase(callback: CallbackQuery, state: FSMContext):
    package_id = callback.data.split(":", 1)[1]
    package = PACKAGES.get(package_id)

    if package is None:
        await callback.answer("Package not found.", show_alert=True)
        return

    name, price, credits = package
    await begin_purchase_flow(
        callback,
        state,
        package_id,
        name,
        price,
        credits,
    )


@router.callback_query(F.data == "protect:buy")
async def begin_protection_purchase(callback: CallbackQuery, state: FSMContext):
    if callback.message is None or callback.message.chat.type != "private":
        await callback.answer(
            "Purchases are handled in the bot's private chat.",
            show_alert=True,
        )
        return

    status = await get_protection_status(callback.from_user.id)
    if status is None:
        await callback.answer(
            "Send /start in the bot's private chat before purchasing.",
            show_alert=True,
        )
        return

    await begin_purchase_flow(
        callback,
        state,
        PROTECTION_PACKAGE_ID,
        f"Bull Protection · Rank {min(status['rank'] + 1, 5)}",
        status["price"],
        None,
    )


@router.message(PurchaseFlow.waiting_for_wallet, F.chat.type == "private")
async def receive_buyer_wallet(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Send your public Solana wallet address as text.")
        return

    data = await state.get_data()
    package_id = data.get("package_id")

    try:
        purchase = await create_purchase_intent(
            message.from_user.id,
            package_id,
            message.text,
        )
    except PaymentServiceError as exc:
        await message.answer(str(exc))
        return

    await state.update_data(purchase_reference=purchase["reference"])
    await state.set_state(PurchaseFlow.waiting_for_signature)

    credits_text = (
        f"Credits after verification: <b>{purchase['credits']:,}</b>\n\n"
        if purchase["credits"]
        else "Protection after verification: <b>7 days</b>\n\n"
    )
    await message.answer(
        "🧾 <b>Purchase created</b>\n\n"
        f"Package: <b>{purchase['package_name']}</b>\n"
        f"Amount: <b>{purchase['token_amount']:,} $GOLD</b>\n"
        f"{credits_text}"
        f"Official receiving wallet:\n<code>{purchase['recipient']}</code>\n\n"
        f"Purchase reference:\n<code>{purchase['reference']}</code>\n\n"
        "Only send the exact amount from the wallet you registered above. "
        "After the transaction is finalized, send its transaction signature here.\n\n"
        "Do not send your seed phrase or private key.",
        parse_mode="HTML",
    )


@router.message(PurchaseFlow.waiting_for_signature, F.chat.type == "private")
async def receive_purchase_signature(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Send the Solana transaction signature as text.")
        return

    data = await state.get_data()
    reference = data.get("purchase_reference")

    if not reference:
        await state.clear()
        await message.answer("Purchase session expired. Open the private shop to start again.")
        return

    try:
        result = await submit_purchase_signature(
            message.from_user.id,
            reference,
            message.text.strip(),
        )
    except PaymentServiceError as exc:
        await message.answer(
            payment_error_text(exc),
            reply_markup=payment_verification_error_menu(),
        )
        return

    await state.clear()
    await message.answer(
        payment_confirmation_text(result),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "payment:retry_signature")
async def retry_purchase_signature(callback: CallbackQuery, state: FSMContext):
    if callback.message is None or callback.message.chat.type != "private":
        await callback.answer(
            "Payment recovery is available in the bot's private chat.",
            show_alert=True,
        )
        return

    reference, purchase = await pending_purchase_reference(
        callback.from_user.id,
        state,
    )
    if reference is None or purchase is None:
        await callback.answer(
            "No pending payment was found. Check your balance before starting another purchase.",
            show_alert=True,
        )
        return

    await state.set_state(PurchaseFlow.waiting_for_signature)
    await callback.message.edit_text(
        "Send the correct transaction signature for your existing payment.\n\n"
        "Your purchase reference and expected payment details are unchanged. "
        "If you’ve already sent tokens, do not pay again.",
        reply_markup=payment_signature_prompt_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "payment:check_existing")
async def check_existing_payment(callback: CallbackQuery, state: FSMContext):
    if callback.message is None or callback.message.chat.type != "private":
        await callback.answer(
            "Payment recovery is available in the bot's private chat.",
            show_alert=True,
        )
        return

    reference, purchase = await pending_purchase_reference(
        callback.from_user.id,
        state,
    )
    if reference is None or purchase is None:
        await callback.answer(
            "No pending payment was found. Check your balance before starting another purchase.",
            show_alert=True,
        )
        return

    await state.set_state(PurchaseFlow.waiting_for_signature)
    if not purchase["verification_signature"]:
        await callback.message.edit_text(
            "Your existing payment is still pending and no signature has been "
            "submitted yet. Send the signature for the payment you already made.\n\n"
            "Do not create another purchase or pay again.",
            reply_markup=payment_signature_prompt_menu(),
        )
        await callback.answer()
        return

    try:
        result = await submit_purchase_signature(
            callback.from_user.id,
            reference,
            None,
        )
    except PaymentServiceError as exc:
        await callback.message.edit_text(
            payment_error_text(exc),
            reply_markup=payment_verification_error_menu(),
        )
    else:
        await state.clear()
        await callback.message.edit_text(
            payment_confirmation_text(result),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "payment:back")
async def back_to_pending_payment(callback: CallbackQuery, state: FSMContext):
    if callback.message is None or callback.message.chat.type != "private":
        await callback.answer()
        return

    await callback.message.edit_text(
        "🪙 <b>Existing payment</b>\n\n"
        "Your purchase is still pending and has not been removed. "
        "You can retry with a corrected signature or check the signature already submitted. "
        "Do not pay again.",
        reply_markup=pending_payment_menu(),
        parse_mode="HTML",
    )
    await callback.answer()
