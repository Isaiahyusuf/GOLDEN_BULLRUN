import pytest
from solders.signature import Signature

from app.config import settings
from app.services import solana_service
from app.services.solana_service import (
    PaymentVerificationError,
    verify_token_payment,
)


MINT = "So11111111111111111111111111111111111111112"
RECIPIENT = "11111111111111111111111111111111"
OTHER_WALLET = "Vote111111111111111111111111111111111111111"
TOKEN_ACCOUNT = "SysvarRent111111111111111111111111111111111"
SIGNATURE = str(Signature.default())


def make_transaction(
    *,
    mint=MINT,
    owner=RECIPIENT,
    amount="5000000000",
    decimals=6,
    failed=False,
):
    return {
        "slot": 123,
        "blockTime": 1_700_000_000,
        "transaction": {
            "signatures": [SIGNATURE],
            "message": {
                "accountKeys": [
                    {"pubkey": OTHER_WALLET},
                    {"pubkey": TOKEN_ACCOUNT},
                ],
                "instructions": [
                    {
                        "program": "spl-token",
                        "parsed": {
                            "type": "transferChecked",
                            "info": {
                                "source": OTHER_WALLET,
                                "destination": TOKEN_ACCOUNT,
                                "mint": mint,
                                "tokenAmount": {
                                    "amount": amount,
                                    "decimals": decimals,
                                },
                            },
                        },
                    }
                ],
            },
        },
        "meta": {
            "err": {"InstructionError": [0, "Custom"]} if failed else None,
            "preTokenBalances": [
                {
                    "accountIndex": 0,
                    "mint": mint,
                    "owner": OTHER_WALLET,
                    "uiTokenAmount": {
                        "amount": amount,
                        "decimals": decimals,
                    },
                }
            ],
            "postTokenBalances": [
                {
                    "accountIndex": 1,
                    "mint": mint,
                    "owner": owner,
                    "uiTokenAmount": {
                        "amount": amount,
                        "decimals": decimals,
                    },
                }
            ],
            "innerInstructions": [],
        },
    }


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "payments_enabled", True)
    monkeypatch.setattr(
        settings, "solana_rpc_url", "https://rpc.example.invalid"
    )
    monkeypatch.setattr(settings, "trumpty_token_mint", MINT)
    monkeypatch.setattr(settings, "payment_wallet_address", RECIPIENT)


@pytest.mark.asyncio
async def test_valid_finalized_payment(configured, monkeypatch):
    async def fake_fetch(signature):
        assert signature == SIGNATURE
        return make_transaction()

    monkeypatch.setattr(solana_service, "_fetch_transaction", fake_fetch)

    result = await verify_token_payment(SIGNATURE, 5_000, OTHER_WALLET)

    assert result["tokens_received_raw"] == 5_000_000_000
    assert result["mint"] == MINT
    assert result["recipient"] == RECIPIENT
    assert result["slot"] == 123


@pytest.mark.asyncio
async def test_payments_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "payments_enabled", False)

    with pytest.raises(PaymentVerificationError, match="disabled"):
        await verify_token_payment(SIGNATURE, 5_000, OTHER_WALLET)


@pytest.mark.asyncio
async def test_invalid_signature_is_rejected(configured):
    with pytest.raises(PaymentVerificationError, match="signature"):
        await verify_token_payment("not-a-signature", 5_000, OTHER_WALLET)


@pytest.mark.asyncio
async def test_missing_transaction_is_rejected(configured, monkeypatch):
    async def fake_fetch(signature):
        return None

    monkeypatch.setattr(solana_service, "_fetch_transaction", fake_fetch)

    with pytest.raises(PaymentVerificationError, match="not finalized"):
        await verify_token_payment(SIGNATURE, 5_000, OTHER_WALLET)


@pytest.mark.asyncio
async def test_failed_on_chain_transaction_is_rejected(configured, monkeypatch):
    async def fake_fetch(signature):
        return make_transaction(failed=True)

    monkeypatch.setattr(solana_service, "_fetch_transaction", fake_fetch)

    with pytest.raises(PaymentVerificationError, match="failed"):
        await verify_token_payment(SIGNATURE, 5_000, OTHER_WALLET)


@pytest.mark.asyncio
async def test_wrong_mint_is_rejected(configured, monkeypatch):
    async def fake_fetch(signature):
        return make_transaction(mint=OTHER_WALLET)

    monkeypatch.setattr(solana_service, "_fetch_transaction", fake_fetch)

    with pytest.raises(PaymentVerificationError, match="receipt"):
        await verify_token_payment(SIGNATURE, 5_000, OTHER_WALLET)


@pytest.mark.asyncio
async def test_wrong_recipient_is_rejected(configured, monkeypatch):
    async def fake_fetch(signature):
        return make_transaction(owner=OTHER_WALLET)

    monkeypatch.setattr(solana_service, "_fetch_transaction", fake_fetch)

    with pytest.raises(PaymentVerificationError, match="receipt"):
        await verify_token_payment(SIGNATURE, 5_000, OTHER_WALLET)


@pytest.mark.asyncio
async def test_wrong_amount_is_rejected(configured, monkeypatch):
    async def fake_fetch(signature):
        return make_transaction(amount="4999000000")

    monkeypatch.setattr(solana_service, "_fetch_transaction", fake_fetch)

    with pytest.raises(PaymentVerificationError, match="amount"):
        await verify_token_payment(SIGNATURE, 5_000, OTHER_WALLET)


@pytest.mark.asyncio
async def test_wrong_signature_in_response_is_rejected(configured, monkeypatch):
    async def fake_fetch(signature):
        transaction = make_transaction()
        transaction["transaction"]["signatures"] = [str(Signature.new_unique())]
        return transaction

    monkeypatch.setattr(solana_service, "_fetch_transaction", fake_fetch)

    with pytest.raises(PaymentVerificationError, match="does not match"):
        await verify_token_payment(SIGNATURE, 5_000, OTHER_WALLET)


@pytest.mark.asyncio
async def test_transfer_to_unrecognized_token_account_is_rejected(
    configured, monkeypatch
):
    async def fake_fetch(signature):
        transaction = make_transaction()
        transaction["transaction"]["message"]["instructions"][0]["parsed"][
            "info"
        ]["destination"] = OTHER_WALLET
        return transaction

    monkeypatch.setattr(solana_service, "_fetch_transaction", fake_fetch)

    with pytest.raises(PaymentVerificationError, match="transfer"):
        await verify_token_payment(SIGNATURE, 5_000, OTHER_WALLET)


def test_block_time_converts_to_utc():
    from datetime import datetime, timezone

    from app.services.solana_service import block_time_to_utc

    result = block_time_to_utc(1_700_000_000)

    assert result == datetime(
        2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc
    )


@pytest.mark.parametrize("value", [None, 0, -1, True, "1700000000"])
def test_invalid_block_time_is_rejected(value):
    from app.services.solana_service import block_time_to_utc

    with pytest.raises(PaymentVerificationError, match="timestamp"):
        block_time_to_utc(value)


@pytest.mark.asyncio
async def test_wrong_sender_wallet_is_rejected(configured, monkeypatch):
    async def fake_fetch(signature):
        return make_transaction()

    monkeypatch.setattr(solana_service, "_fetch_transaction", fake_fetch)

    with pytest.raises(PaymentVerificationError, match="source"):
        await verify_token_payment(SIGNATURE, 5_000, RECIPIENT)
