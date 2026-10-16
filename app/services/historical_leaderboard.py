from datetime import datetime, timezone


class HistoricalLedgerError(RuntimeError):
    """Raised when point history cannot establish reliable past balances."""


def _as_utc(value):
    if not isinstance(value, datetime):
        raise HistoricalLedgerError("A required history timestamp is missing.")

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def reconstruct_leaderboard_from_ledger(
    users,
    transactions,
    cutoff,
    limit=10,
):
    """
    Reconstruct standings immediately before cutoff by reversing later
    point transactions from each user's current balance.

    Refuse to rank users if their complete ledger does not reconcile.
    """
    if limit < 1:
        raise ValueError("Leaderboard limit must be at least 1.")

    cutoff = _as_utc(cutoff)
    users_by_id = {user.telegram_id: user for user in users}

    if len(users_by_id) != len(users):
        raise HistoricalLedgerError("Duplicate user records were supplied.")

    ledger_totals = {telegram_id: 0 for telegram_id in users_by_id}
    later_changes = {telegram_id: 0 for telegram_id in users_by_id}

    for transaction in transactions:
        telegram_id = transaction.telegram_id

        if telegram_id not in users_by_id:
            raise HistoricalLedgerError(
                "Point history references a missing user account."
            )

        if not isinstance(transaction.amount, int):
            raise HistoricalLedgerError(
                "A point transaction has an invalid amount."
            )

        created_at = _as_utc(transaction.created_at)

        if (
            getattr(transaction, "reason", None) == "development_ledger_baseline"
            and created_at >= cutoff
        ):
            raise HistoricalLedgerError(
                "Development baseline prevents reliable historical ranking "
                "for this cutoff."
            )

        ledger_totals[telegram_id] += transaction.amount

        if created_at >= cutoff:
            later_changes[telegram_id] += transaction.amount

    candidates = []

    for user in users:
        if user.points != ledger_totals[user.telegram_id]:
            raise HistoricalLedgerError(
                f"Point history does not reconcile for user "
                f"{user.telegram_id}; historical ranking is unsafe."
            )

        created_at = _as_utc(user.created_at)

        # Players who joined at or after the cutoff did not participate
        # in the period ending at that cutoff.
        if created_at >= cutoff:
            continue

        historical_points = user.points - later_changes[user.telegram_id]

        if historical_points < 0:
            raise HistoricalLedgerError(
                f"Reconstructed balance is negative for user "
                f"{user.telegram_id}."
            )

        candidates.append(
            {
                "telegram_id": user.telegram_id,
                "username": user.username,
                "name": user.full_name,
                "points": historical_points,
                "_created_at": created_at,
            }
        )

    candidates.sort(
        key=lambda player: (
            -player["points"],
            player["_created_at"],
            player["telegram_id"],
        )
    )

    result = []

    for rank, player in enumerate(candidates[:limit], start=1):
        result.append(
            {
                "rank": rank,
                "telegram_id": player["telegram_id"],
                "username": player["username"],
                "name": player["name"],
                "points": player["points"],
            }
        )

    return result
