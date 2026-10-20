from typing import Any

import aiohttp
from solders.pubkey import Pubkey
from solders.signature import Signature

from app.config import settings


class PaymentVerificationError(Exception):
    pass


def block_time_to_utc(block_time: Any):
    from datetime import datetime, timezone

    if (
        not isinstance(block_time, int)
        or isinstance(block_time, bool)
        or block_time <= 0
    ):
        raise PaymentVerificationError(
            "The transaction has no valid on-chain receipt timestamp."
        )

    try:
        return datetime.fromtimestamp(block_time, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise PaymentVerificationError(
            "The transaction receipt timestamp is invalid."
        ) from exc


def payments_configured() -> bool:
    if not settings.payments_enabled:
        return False

    if not all((
        settings.solana_rpc_url,
        settings.gold_token_mint,
        settings.payment_wallet_address,
    )):
        return False

    if not settings.solana_rpc_url.startswith("https://"):
        return False

    try:
        Pubkey.from_string(settings.gold_token_mint)
        Pubkey.from_string(settings.payment_wallet_address)
    except ValueError:
        return False

    return True


async def _fetch_transaction(signature: str) -> dict[str, Any] | None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            signature,
            {
                "commitment": "finalized",
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
            },
        ],
    }

    timeout = aiohttp.ClientTimeout(total=15)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                settings.solana_rpc_url,
                json=payload,
            ) as response:
                response.raise_for_status()
                data = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise PaymentVerificationError(
            "Could not safely verify the transaction with Solana."
        ) from exc

    if not isinstance(data, dict) or data.get("error"):
        raise PaymentVerificationError(
            "Solana RPC rejected the verification request."
        )

    result = data.get("result")
    return result if isinstance(result, dict) else None


def _raw_amount(value: Any) -> int:
    if isinstance(value, bool):
        raise PaymentVerificationError("Invalid token transfer amount.")

    try:
        amount = int(value)
    except (TypeError, ValueError) as exc:
        raise PaymentVerificationError(
            "Invalid token transfer amount."
        ) from exc

    if amount < 0:
        raise PaymentVerificationError("Invalid token transfer amount.")

    return amount


def _all_instructions(
    message: dict[str, Any],
    meta: dict[str, Any],
) -> list[dict[str, Any]]:
    instructions = message.get("instructions") or []

    if not isinstance(instructions, list):
        raise PaymentVerificationError("Transaction instructions are invalid.")

    result = [item for item in instructions if isinstance(item, dict)]

    inner_groups = meta.get("innerInstructions") or []
    if not isinstance(inner_groups, list):
        raise PaymentVerificationError("Inner instructions are invalid.")

    for group in inner_groups:
        if not isinstance(group, dict):
            continue

        nested = group.get("instructions") or []
        if not isinstance(nested, list):
            raise PaymentVerificationError("Inner instructions are invalid.")

        result.extend(item for item in nested if isinstance(item, dict))

    return result


async def verify_token_payment(
    signature: str,
    expected_tokens: int,
    buyer_wallet: str,
) -> dict[str, Any]:
    if not payments_configured():
        raise PaymentVerificationError(
            "Payments are disabled or the official Solana configuration is incomplete."
        )

    if (
        not isinstance(expected_tokens, int)
        or isinstance(expected_tokens, bool)
        or expected_tokens <= 0
    ):
        raise PaymentVerificationError("The expected payment amount is invalid.")

    try:
        parsed_signature = str(Signature.from_string(signature))
    except (ValueError, TypeError) as exc:
        raise PaymentVerificationError(
            "The transaction signature is invalid."
        ) from exc

    transaction = await _fetch_transaction(parsed_signature)

    if transaction is None:
        raise PaymentVerificationError(
            "The transaction is not finalized or could not be found."
        )

    meta = transaction.get("meta")
    tx_data = transaction.get("transaction")

    if not isinstance(meta, dict) or not isinstance(tx_data, dict):
        raise PaymentVerificationError("The transaction response is incomplete.")

    if meta.get("err") is not None:
        raise PaymentVerificationError("The on-chain transaction failed.")

    signatures = tx_data.get("signatures") or []
    if parsed_signature not in signatures:
        raise PaymentVerificationError(
            "The returned transaction does not match the submitted signature."
        )

    message = tx_data.get("message")
    if not isinstance(message, dict):
        raise PaymentVerificationError("The transaction message is incomplete.")

    account_keys = message.get("accountKeys") or []
    if not isinstance(account_keys, list):
        raise PaymentVerificationError("The transaction account list is invalid.")

    account_addresses = []
    for key in account_keys:
        if isinstance(key, str):
            account_addresses.append(key)
        elif isinstance(key, dict) and isinstance(key.get("pubkey"), str):
            account_addresses.append(key["pubkey"])
        else:
            raise PaymentVerificationError(
                "The transaction account list is invalid."
            )

    try:
        buyer_wallet = str(Pubkey.from_string(buyer_wallet))
    except (ValueError, TypeError) as exc:
        raise PaymentVerificationError(
            "The buyer wallet address is invalid."
        ) from exc

    mint = settings.gold_token_mint
    recipient = settings.payment_wallet_address

    pre_balances = meta.get("preTokenBalances") or []
    if not isinstance(pre_balances, list):
        raise PaymentVerificationError("Source token balance data is invalid.")

    source_owners: dict[str, str] = {}
    for entry in pre_balances:
        if not isinstance(entry, dict) or entry.get("mint") != mint:
            continue

        index = entry.get("accountIndex")
        owner = entry.get("owner")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= len(account_addresses)
            or not isinstance(owner, str)
        ):
            raise PaymentVerificationError("Source token balance data is invalid.")

        source_owners[account_addresses[index]] = owner

    post_balances = meta.get("postTokenBalances") or []

    if not isinstance(post_balances, list):
        raise PaymentVerificationError("Token balance data is invalid.")

    recipient_accounts: set[str] = set()
    decimals_found: set[int] = set()

    for entry in post_balances:
        if not isinstance(entry, dict):
            continue
        if entry.get("mint") != mint or entry.get("owner") != recipient:
            continue

        index = entry.get("accountIndex")
        token_amount = entry.get("uiTokenAmount") or {}
        decimals = token_amount.get("decimals")

        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= len(account_addresses)
            or not isinstance(decimals, int)
            or isinstance(decimals, bool)
            or decimals < 0
            or decimals > 18
        ):
            raise PaymentVerificationError("Token balance data is invalid.")

        recipient_accounts.add(account_addresses[index])
        decimals_found.add(decimals)

    if not recipient_accounts or len(decimals_found) != 1:
        raise PaymentVerificationError(
            "No verifiable receipt was found for the official wallet and token."
        )

    decimals = next(iter(decimals_found))
    expected_raw = expected_tokens * (10 ** decimals)
    received_raw = 0
    matching_transfers = 0

    instructions = _all_instructions(message, meta)

    for instruction in instructions:
        if instruction.get("program") not in {"spl-token", "spl-token-2022"}:
            continue

        parsed = instruction.get("parsed")
        if not isinstance(parsed, dict):
            continue

        info = parsed.get("info")
        if not isinstance(info, dict):
            continue

        transfer_type = parsed.get("type")
        if transfer_type not in {"transfer", "transferChecked"}:
            continue

        destination = info.get("destination")
        if destination not in recipient_accounts:
            continue

        source = info.get("source")
        if (
            not isinstance(source, str)
            or source_owners.get(source) != buyer_wallet
        ):
            raise PaymentVerificationError(
                "The transfer source does not belong to the buyer wallet."
            )

        if transfer_type == "transferChecked":
            if info.get("mint") != mint:
                raise PaymentVerificationError(
                    "A transfer to the receiving token account used an unexpected mint."
                )

            token_amount = info.get("tokenAmount")
            if not isinstance(token_amount, dict):
                raise PaymentVerificationError(
                    "The checked transfer amount is incomplete."
                )

            instruction_decimals = token_amount.get("decimals")
            if instruction_decimals != decimals:
                raise PaymentVerificationError(
                    "The transfer token decimals do not match."
                )

            amount = _raw_amount(token_amount.get("amount"))
        else:
            amount = _raw_amount(info.get("amount"))

        received_raw += amount
        matching_transfers += 1

    if matching_transfers == 0:
        raise PaymentVerificationError(
            "No qualifying token transfer to the official wallet was found."
        )

    if received_raw != expected_raw:
        raise PaymentVerificationError(
            "The received token amount does not exactly match the package price."
        )

    return {
        "signature": parsed_signature,
        "mint": mint,
        "recipient": recipient,
        "tokens_received_raw": received_raw,
        "decimals": decimals,
        "slot": transaction.get("slot"),
        "block_time": transaction.get("blockTime"),
    }


class TokenBalanceError(Exception):
    pass


async def get_trumpty_token_balance():
    """Read the configured wallet's finalized balance for the configured mint."""
    from decimal import Decimal

    if not settings.solana_rpc_url or not settings.solana_rpc_url.startswith("https://"):
        raise TokenBalanceError("A valid HTTPS Solana RPC URL is required.")

    if not settings.gold_token_mint or not settings.payment_wallet_address:
        raise TokenBalanceError("The token mint and team wallet must be configured.")

    try:
        mint = str(Pubkey.from_string(settings.gold_token_mint))
        wallet = str(Pubkey.from_string(settings.payment_wallet_address))
    except ValueError as exc:
        raise TokenBalanceError("The configured token mint or wallet is invalid.") from exc

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet,
            {"mint": mint},
            {"encoding": "jsonParsed", "commitment": "finalized"},
        ],
    }

    timeout = aiohttp.ClientTimeout(total=15)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                settings.solana_rpc_url,
                json=payload,
            ) as response:
                response.raise_for_status()
                data = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise TokenBalanceError("Could not read the team token balance from Solana.") from exc

    if not isinstance(data, dict) or data.get("error"):
        raise TokenBalanceError("Solana RPC rejected the token balance request.")

    result = data.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("value"), list):
        raise TokenBalanceError("Solana returned an invalid token balance response.")

    total_raw = 0
    decimals_seen = set()

    for account in result["value"]:
        try:
            info = account["account"]["data"]["parsed"]["info"]
            token_amount = info["tokenAmount"]

            if info.get("mint") != mint or info.get("owner") != wallet:
                raise TokenBalanceError("A token account did not match the configured wallet and mint.")

            raw_amount = int(token_amount["amount"])
            decimals = int(token_amount["decimals"])

            if raw_amount < 0 or not 0 <= decimals <= 18:
                raise ValueError("Invalid token amount.")

            total_raw += raw_amount
            decimals_seen.add(decimals)
        except TokenBalanceError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise TokenBalanceError("Solana returned invalid token account data.") from exc

    if len(decimals_seen) > 1:
        raise TokenBalanceError("The token accounts returned inconsistent decimals.")

    decimals = next(iter(decimals_seen), 0)
    return Decimal(total_raw) / (Decimal(10) ** decimals)
