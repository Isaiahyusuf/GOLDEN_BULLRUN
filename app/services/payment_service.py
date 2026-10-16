from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from solders.pubkey import Pubkey

from app.config import settings
from app.database.connection import SessionLocal
from app.models.payment import Payment
from app.models.user import User
from app.services.solana_service import (
    PaymentVerificationError,
    block_time_to_utc,
    payments_configured,
    verify_token_payment,
)


PACKAGES = {
    "1": ("Starter Pack", 5_000, 10_000),
    "2": ("Warrior Pack", 10_000, 22_000),
    "3": ("Champion Pack", 15_000, 36_000),
    "4": ("Royal Pack", 20_000, 52_000),
    "5": ("Legend Pack", 25_000, 70_000),
}


class PaymentServiceError(Exception):
    pass


def validate_buyer_wallet(value: str) -> str:
    if not isinstance(value, str):
        raise PaymentServiceError("Send a valid Solana wallet address.")

    try:
        return str(Pubkey.from_string(value.strip()))
    except (ValueError, TypeError) as exc:
        raise PaymentServiceError(
            "That Solana wallet address is invalid. Please check it and try again."
        ) from exc


async def create_purchase_intent(
    telegram_id: int,
    package_id: str,
    buyer_wallet: str,
) -> dict:
    if not payments_configured():
        raise PaymentServiceError(
            "Checkout is disabled or the official payment configuration is incomplete."
        )

    package = PACKAGES.get(package_id)
    if package is None:
        raise PaymentServiceError("That package does not exist.")

    buyer_wallet = validate_buyer_wallet(buyer_wallet)
    name, price, credits = package

    async with SessionLocal() as session:
        async with session.begin():
            user = await session.scalar(
                select(User)
                .where(User.telegram_id == telegram_id)
                .with_for_update()
            )
            if user is None:
                raise PaymentServiceError(
                    "Please send /start in the bot's private chat before purchasing."
                )

            payment = Payment(
                telegram_id=telegram_id,
                package_id=package_id,
                token_mint=settings.trumpty_token_mint,
                recipient=settings.payment_wallet_address,
                buyer_wallet=buyer_wallet,
                token_amount=Decimal(price),
                credits=credits,
                status="pending",
            )
            session.add(payment)
            await session.flush()

            result = {
                "reference": payment.purchase_reference,
                "package_name": name,
                "token_amount": price,
                "credits": credits,
                "recipient": payment.recipient,
                "buyer_wallet": buyer_wallet,
            }

    return result


async def submit_purchase_signature(
    telegram_id: int,
    purchase_reference: str,
    signature: str,
) -> dict:
    if not payments_configured():
        raise PaymentServiceError("Payments are currently disabled.")

    try:
        async with SessionLocal() as session:
            async with session.begin():
                payment = await session.scalar(
                    select(Payment)
                    .where(
                        Payment.purchase_reference == purchase_reference,
                        Payment.telegram_id == telegram_id,
                    )
                    .with_for_update()
                )

                if payment is None:
                    raise PaymentServiceError(
                        "Purchase not found. Start checkout again from the private shop."
                    )

                if payment.status != "pending" or payment.signature is not None:
                    raise PaymentServiceError(
                        "This purchase has already been processed or is no longer pending."
                    )

                if not payment.buyer_wallet:
                    raise PaymentServiceError(
                        "This purchase has no registered buyer wallet. Start a new checkout."
                    )

                existing = await session.scalar(
                    select(Payment.id).where(Payment.signature == signature)
                )
                if existing is not None:
                    raise PaymentServiceError(
                        "That transaction signature has already been submitted."
                    )

                user = await session.scalar(
                    select(User)
                    .where(User.telegram_id == telegram_id)
                    .with_for_update()
                )
                if user is None:
                    raise PaymentServiceError("Your player account could not be found.")

                verification = await verify_token_payment(
                    signature,
                    int(payment.token_amount),
                    payment.buyer_wallet,
                )
                received_at = block_time_to_utc(verification["block_time"])
                now = datetime.now(timezone.utc)

                payment.signature = verification["signature"]
                payment.status = "credited"
                payment.verified_at = now
                payment.received_at = received_at
                payment.credited_at = now
                user.purchased_credits += payment.credits

                result = {
                    "package_id": payment.package_id,
                    "credits": payment.credits,
                    "purchased_credits": user.purchased_credits,
                    "signature": verification["signature"],
                    "received_at": received_at,
                }

        return result

    except IntegrityError as exc:
        raise PaymentServiceError(
            "That transaction has already been used or the purchase conflicted with another request. "
            "Check your balance before trying again."
        ) from exc
    except PaymentVerificationError as exc:
        raise PaymentServiceError(str(exc)) from exc
