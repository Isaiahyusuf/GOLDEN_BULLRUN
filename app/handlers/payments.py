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
    submit_purchase_signature,
)
from app.services.solana_service import payments_configured
from app.keyboards.main_menu import payment_unavailable_menu
from app.services.protection_service import (
    get_protected_percentage,
    get_protection_status,
)


router = Router()


class PurchaseFlow(StatesGroup):
    waiting_for_wallet = State()
    waiting_for_signature = State()


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
            f"Payment not credited: {exc}\n\n"
            "If you already sent tokens, do not pay again until the transaction is checked."
        )
        return

    await state.clear()
    if result["package_id"] == PROTECTION_PACKAGE_ID:
        expires_at = result["protection_expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        expiry_text = expires_at.strftime("%d %b %Y, %H:%M UTC")
        confirmation = (
            "✅ <b>Protection activated</b>\n\n"
            f"Protection rank: <b>{result['protection_rank']}/5</b>\n"
            f"Bullrun Points preserved at weekly reset: "
            f"<b>{get_protected_percentage(result['protection_rank'])}%</b> "
            "of Bullrun Points above 10,000.\n"
            f"Expires: <b>{expiry_text}</b>\n"
            "Bull Arena losses are not protected.\n\n"
        )
    else:
        confirmation = (
            "✅ <b>Payment verified</b>\n\n"
            f"Credits added: <b>{result['credits']:,}</b>\n"
            f"Purchased credits balance: <b>{result['purchased_credits']:,}</b>\n\n"
        )

    await message.answer(
        confirmation + f"Transaction:\n<code>{result['signature']}</code>",
        parse_mode="HTML",
    )
