import pytest

from app.services import payment_service


def test_protection_package_renews_for_seven_days():
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    user = SimpleNamespace(
        protection_expires_at=now + timedelta(days=2)
    )

    expiry = payment_service.extend_protection(user, now)

    assert expiry == now + timedelta(days=9)
    assert user.protection_expires_at == expiry


@pytest.mark.asyncio
async def test_verified_protection_purchase_activates_in_same_transaction(
    monkeypatch,
):
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    fixed_now = datetime(2026, 10, 16, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz else fixed_now.replace(tzinfo=None)

    payment = SimpleNamespace(
        purchase_reference="protection-purchase-reference",
        telegram_id=12345,
        status="pending",
        signature=None,
        buyer_wallet="Vote111111111111111111111111111111111111111",
        token_amount=Decimal("30000"),
        package_id=payment_service.PROTECTION_PACKAGE_ID,
        credits=0,
        verified_at=None,
        received_at=None,
        credited_at=None,
    )
    user = SimpleNamespace(
        protection_expires_at=fixed_now + timedelta(days=2),
        purchased_credits=500,
    )
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[payment, None, user])
    session.add = MagicMock()

    transaction_context = MagicMock()
    transaction_context.__aenter__ = AsyncMock(return_value=session)
    transaction_context.__aexit__ = AsyncMock(return_value=False)
    session.begin.return_value = transaction_context

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    async def verify(signature, expected_tokens, buyer_wallet):
        assert signature == "verified-signature"
        assert expected_tokens == 30_000
        assert buyer_wallet == payment.buyer_wallet
        return {
            "signature": signature,
            "block_time": 1_700_000_000,
        }

    monkeypatch.setattr(payment_service, "datetime", FrozenDateTime)
    monkeypatch.setattr(payment_service, "payments_configured", lambda: True)
    monkeypatch.setattr(payment_service, "verify_token_payment", verify)
    monkeypatch.setattr(payment_service, "SessionLocal", lambda: session_context)

    result = await payment_service.submit_purchase_signature(
        payment.telegram_id,
        payment.purchase_reference,
        "verified-signature",
    )

    assert payment.status == "credited"
    assert payment.signature == "verified-signature"
    assert user.protection_expires_at == fixed_now + timedelta(days=9)
    assert user.purchased_credits == 500
    assert result["protection_expires_at"] == fixed_now + timedelta(days=9)
    assert result["credits"] == 0
    ledger_entry = session.add.call_args.args[0]
    assert ledger_entry.reason == (
        "protection_purchase:protection-purchase-reference"
    )


def test_valid_buyer_wallet_is_normalized():
    from solders.pubkey import Pubkey

    wallet = str(Pubkey.from_string(
        "Vote111111111111111111111111111111111111111"
    ))

    assert payment_service.validate_buyer_wallet(wallet) == wallet


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-wallet",
        "123",
    ],
)
def test_invalid_buyer_wallet_is_rejected(value):
    with pytest.raises(payment_service.PaymentServiceError, match="invalid"):
        payment_service.validate_buyer_wallet(value)


@pytest.mark.asyncio
async def test_purchase_creation_fails_when_payments_are_disabled(
    monkeypatch,
):
    monkeypatch.setattr(
        payment_service, "payments_configured", lambda: False
    )

    with pytest.raises(
        payment_service.PaymentServiceError, match="disabled"
    ):
        await payment_service.create_purchase_intent(
            12345,
            "1",
            "Vote111111111111111111111111111111111111111",
        )


@pytest.mark.asyncio
async def test_unknown_package_is_rejected_before_database_access(
    monkeypatch,
):
    monkeypatch.setattr(
        payment_service, "payments_configured", lambda: True
    )

    def unexpected_database_access():
        pytest.fail("Database should not be accessed for an unknown package")

    monkeypatch.setattr(
        payment_service, "SessionLocal", unexpected_database_access
    )

    with pytest.raises(
        payment_service.PaymentServiceError, match="package"
    ):
        await payment_service.create_purchase_intent(
            12345,
            "unknown",
            "Vote111111111111111111111111111111111111111",
        )


@pytest.mark.asyncio
async def test_signature_submission_fails_when_payments_are_disabled(
    monkeypatch,
):
    monkeypatch.setattr(
        payment_service, "payments_configured", lambda: False
    )

    with pytest.raises(
        payment_service.PaymentServiceError, match="disabled"
    ):
        await payment_service.submit_purchase_signature(
            12345,
            "test-purchase-reference",
            "test-signature",
        )


def test_verified_payment_credits_once_and_rejects_reuse(monkeypatch):
    import asyncio
    from datetime import datetime, timezone

    from sqlalchemy import delete, select

    from app.database.connection import SessionLocal, engine, init_db
    from app.models.payment import Payment
    from app.models.user import User

    telegram_id = 880009991
    signature = "test-payment-service-signature-success"
    buyer_wallet = "Vote111111111111111111111111111111111111111"
    reference = "test-credit-once-reference"

    monkeypatch.setattr(payment_service, "payments_configured", lambda: True)

    async def fake_verify(submitted_signature, expected_tokens, wallet):
        assert submitted_signature == signature
        assert expected_tokens == 5000
        assert wallet == buyer_wallet
        return {
            "signature": signature,
            "block_time": 1_700_000_000,
        }

    monkeypatch.setattr(
        payment_service, "verify_token_payment", fake_verify
    )

    async def run():
        await init_db()
        try:
            async with SessionLocal() as session:
                async with session.begin():
                    await session.execute(
                        delete(Payment).where(
                            Payment.purchase_reference == reference
                        )
                    )
                    await session.execute(
                        delete(User).where(User.telegram_id == telegram_id)
                    )
                    session.add(
                        User(
                            telegram_id=telegram_id,
                            full_name="Payment Test Player",
                            purchased_credits=0,
                        )
                    )
                    session.add(
                        Payment(
                            telegram_id=telegram_id,
                            package_id="1",
                            purchase_reference=reference,
                            token_mint="test-mint",
                            recipient="test-recipient",
                            buyer_wallet=buyer_wallet,
                            token_amount=5000,
                            credits=10000,
                            status="pending",
                        )
                    )

            result = await payment_service.submit_purchase_signature(
                telegram_id, reference, signature
            )
            assert result["credits"] == 10000
            assert result["purchased_credits"] == 10000
            assert result["received_at"] == datetime.fromtimestamp(
                1_700_000_000, tz=timezone.utc
            )

            with pytest.raises(
                payment_service.PaymentServiceError,
                match="already been processed",
            ):
                await payment_service.submit_purchase_signature(
                    telegram_id, reference, signature
                )

            async with SessionLocal() as session:
                user = await session.get(User, telegram_id)
                payment = await session.scalar(
                    select(Payment).where(
                        Payment.purchase_reference == reference
                    )
                )
                assert user.purchased_credits == 10000
                assert payment.status == "credited"
                assert payment.signature == signature
                assert payment.received_at is not None
                assert payment.credited_at is not None
        finally:
            async with SessionLocal() as session:
                async with session.begin():
                    await session.execute(
                        delete(Payment).where(
                            Payment.purchase_reference == reference
                        )
                    )
                    await session.execute(
                        delete(User).where(User.telegram_id == telegram_id)
                    )
            await engine.dispose()

    asyncio.run(run())


def test_failed_verification_does_not_credit_or_complete_purchase(
    monkeypatch,
):
    import asyncio

    from sqlalchemy import delete, select

    from app.database.connection import SessionLocal, engine, init_db
    from app.models.payment import Payment
    from app.models.user import User
    from app.services.solana_service import PaymentVerificationError

    telegram_id = 880009992
    signature = "test-payment-service-signature-failure"
    buyer_wallet = "Vote111111111111111111111111111111111111111"
    reference = "test-verification-failure-reference"

    monkeypatch.setattr(payment_service, "payments_configured", lambda: True)

    async def fake_verify(*args, **kwargs):
        raise PaymentVerificationError("Test verification failure")

    monkeypatch.setattr(
        payment_service, "verify_token_payment", fake_verify
    )

    async def run():
        await init_db()
        try:
            async with SessionLocal() as session:
                async with session.begin():
                    await session.execute(
                        delete(Payment).where(
                            Payment.purchase_reference == reference
                        )
                    )
                    await session.execute(
                        delete(User).where(User.telegram_id == telegram_id)
                    )
                    session.add(
                        User(
                            telegram_id=telegram_id,
                            full_name="Payment Failure Test",
                            purchased_credits=0,
                        )
                    )
                    session.add(
                        Payment(
                            telegram_id=telegram_id,
                            package_id="1",
                            purchase_reference=reference,
                            token_mint="test-mint",
                            recipient="test-recipient",
                            buyer_wallet=buyer_wallet,
                            token_amount=5000,
                            credits=10000,
                            status="pending",
                        )
                    )

            with pytest.raises(
                payment_service.PaymentServiceError,
                match="Test verification failure",
            ):
                await payment_service.submit_purchase_signature(
                    telegram_id, reference, signature
                )

            async with SessionLocal() as session:
                user = await session.get(User, telegram_id)
                payment = await session.scalar(
                    select(Payment).where(
                        Payment.purchase_reference == reference
                    )
                )
                assert user.purchased_credits == 0
                assert payment.status == "pending"
                assert payment.signature is None
                assert payment.received_at is None
                assert payment.credited_at is None
        finally:
            async with SessionLocal() as session:
                async with session.begin():
                    await session.execute(
                        delete(Payment).where(
                            Payment.purchase_reference == reference
                        )
                    )
                    await session.execute(
                        delete(User).where(User.telegram_id == telegram_id)
                    )
            await engine.dispose()

    asyncio.run(run())
