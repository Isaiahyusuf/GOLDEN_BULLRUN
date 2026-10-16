from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.services.payment_service import (
    PACKAGES,
    PaymentServiceError,
    create_purchase_intent,
    submit_purchase_signature,
)
from app.services.solana_service import payments_configured
from app.keyboards.main_menu import payment_unavailable_menu


router = Router()


class PurchaseFlow(StatesGroup):
    waiting_for_wallet = State()
    waiting_for_signature = State()


@router.callback_query(F.data.startswith("buy:"))
async def begin_purchase(callback: CallbackQuery, state: FSMContext):
    if callback.message is None or callback.message.chat.type != "private":
        await callback.answer(
            "Purchases are handled in the bot's private chat.",
            show_alert=True,
        )
        return

    package_id = callback.data.split(":", 1)[1]
    package = PACKAGES.get(package_id)

    if package is None:
        await callback.answer("Package not found.", show_alert=True)
        return

    if not payments_configured():
        await callback.message.edit_text(
            "🔒 <b>Checkout is not enabled yet.</b>\n\n"
            "Do not send tokens. Payments will open after the official "
            "wallet and verification setup have been tested.",
            reply_markup=payment_unavailable_menu(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    name, price, credits = package
    await state.clear()
    await state.update_data(package_id=package_id)
    await state.set_state(PurchaseFlow.waiting_for_wallet)

    await callback.message.edit_text(
        f"🪙 <b>{name}</b>\n\n"
        f"Price: <b>{price:,} $TRUMPTY</b>\n"
        f"Credits: <b>{credits:,}</b>\n\n"
        "Send the public Solana wallet address you will pay from.\n"
        "Never send a seed phrase or private key.",
        reply_markup=payment_unavailable_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


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

    await message.answer(
        "🧾 <b>Purchase created</b>\n\n"
        f"Package: <b>{purchase['package_name']}</b>\n"
        f"Amount: <b>{purchase['token_amount']:,} $TRUMPTY</b>\n"
        f"Credits after verification: <b>{purchase['credits']:,}</b>\n\n"
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
    await message.answer(
        "✅ <b>Payment verified</b>\n\n"
        f"Credits added: <b>{result['credits']:,}</b>\n"
        f"Purchased credits balance: <b>{result['purchased_credits']:,}</b>\n\n"
        f"Transaction:\n<code>{result['signature']}</code>",
        parse_mode="HTML",
    )
