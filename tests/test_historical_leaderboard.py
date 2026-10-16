from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.historical_leaderboard import (
    HistoricalLedgerError,
    rank_weekly_earnings_from_ledger,
    reconstruct_leaderboard_from_ledger,
)


UTC = timezone.utc
CUTOFF = datetime(2026, 10, 12, tzinfo=UTC)


def user(telegram_id, points, created_at=None, username=None, name=None):
    return SimpleNamespace(
        telegram_id=telegram_id,
        points=points,
        created_at=created_at or CUTOFF - timedelta(days=30),
        username=username,
        full_name=name or f"Player {telegram_id}",
    )


def transaction(telegram_id, amount, created_at, reason="daily_reward:2026-10-01:1"):
    return SimpleNamespace(
        telegram_id=telegram_id,
        amount=amount,
        reason=reason,
        created_at=created_at,
    )


def test_reconstructs_past_balances_by_reversing_later_changes():
    players = [
        user(1, 15_000),
        user(2, 12_000),
    ]
    history = [
        transaction(1, 10_000, CUTOFF - timedelta(days=2)),
        transaction(1, 5_000, CUTOFF + timedelta(days=1)),
        transaction(2, 10_000, CUTOFF - timedelta(days=2)),
        transaction(2, 2_000, CUTOFF + timedelta(days=2)),
    ]

    result = reconstruct_leaderboard_from_ledger(
        players, history, CUTOFF
    )

    assert [(p["telegram_id"], p["points"]) for p in result] == [
        (1, 10_000),
        (2, 10_000),
    ]
    assert [p["rank"] for p in result] == [1, 2]


def test_transaction_exactly_at_cutoff_is_reversed():
    players = [user(1, 20_000)]
    history = [
        transaction(1, 10_000, CUTOFF - timedelta(days=1)),
        transaction(1, 10_000, CUTOFF),
    ]

    result = reconstruct_leaderboard_from_ledger(
        players, history, CUTOFF
    )

    assert result[0]["points"] == 10_000


def test_excludes_users_created_at_or_after_cutoff():
    players = [
        user(1, 10_000),
        user(2, 10_000, created_at=CUTOFF),
    ]
    history = [
        transaction(1, 10_000, CUTOFF - timedelta(days=1)),
        transaction(2, 10_000, CUTOFF),
    ]

    result = reconstruct_leaderboard_from_ledger(
        players, history, CUTOFF
    )

    assert [p["telegram_id"] for p in result] == [1]


def test_blocks_when_current_balance_does_not_match_ledger():
    players = [user(1, 15_000)]
    history = [
        transaction(1, 10_000, CUTOFF - timedelta(days=1)),
    ]

    with pytest.raises(HistoricalLedgerError, match="does not reconcile"):
        reconstruct_leaderboard_from_ledger(
            players, history, CUTOFF
        )


def test_blocks_transactions_for_missing_accounts():
    players = [user(1, 10_000)]
    history = [
        transaction(1, 10_000, CUTOFF - timedelta(days=1)),
        transaction(999, 100, CUTOFF + timedelta(days=1)),
    ]

    with pytest.raises(HistoricalLedgerError, match="missing user"):
        reconstruct_leaderboard_from_ledger(
            players, history, CUTOFF
        )


def test_blocks_missing_transaction_timestamp():
    players = [user(1, 10_000)]
    history = [transaction(1, 10_000, None)]

    with pytest.raises(HistoricalLedgerError, match="timestamp"):
        reconstruct_leaderboard_from_ledger(
            players, history, CUTOFF
        )


def test_tie_breaks_by_creation_time_then_telegram_id():
    players = [
        user(2, 10_000, created_at=CUTOFF - timedelta(days=2)),
        user(1, 10_000, created_at=CUTOFF - timedelta(days=2)),
        user(3, 10_000, created_at=CUTOFF - timedelta(days=1)),
    ]
    history = [
        transaction(p.telegram_id, 10_000, CUTOFF - timedelta(days=3))
        for p in players
    ]

    result = reconstruct_leaderboard_from_ledger(
        players, history, CUTOFF
    )

    assert [p["telegram_id"] for p in result] == [1, 2, 3]


def test_respects_leaderboard_limit():
    players = [user(i, 10_000) for i in range(1, 5)]
    history = [
        transaction(i, 10_000, CUTOFF - timedelta(days=1))
        for i in range(1, 5)
    ]

    result = reconstruct_leaderboard_from_ledger(
        players, history, CUTOFF, limit=3
    )

    assert len(result) == 3
    assert [p["rank"] for p in result] == [1, 2, 3]


def test_blocks_development_baseline_at_or_after_cutoff():
    players = [user(1, 10_000)]
    history = [
        SimpleNamespace(
            telegram_id=1,
            amount=10_000,
            created_at=CUTOFF,
            reason="development_ledger_baseline",
        )
    ]

    with pytest.raises(HistoricalLedgerError, match="Development baseline"):
        reconstruct_leaderboard_from_ledger(players, history, CUTOFF)


def test_ranks_gross_eligible_awards_within_week_boundaries():
    week_start = CUTOFF
    week_end = CUTOFF + timedelta(days=7)
    players = [user(1, 0), user(2, 0)]
    history = [
        transaction(1, 100, week_start, "welcome_bonus"),
        transaction(1, -80, week_start + timedelta(days=1), "duel_reserve:1"),
        transaction(1, 200, week_start + timedelta(days=2), "duel_prize:1"),
        transaction(1, 80, week_start + timedelta(days=3), "duel_timeout_refund:2"),
        transaction(1, 500, week_start + timedelta(days=4), "weekly_reset:2026-W42"),
        transaction(2, 250, week_start + timedelta(days=1), "x_raid_quiz:1"),
        transaction(2, 300, week_end, "daily_reward:2026-10-19:1"),
        transaction(2, 400, week_start - timedelta(seconds=1), "daily_reward:2026-10-11:1"),
    ]

    result = rank_weekly_earnings_from_ledger(
        players, history, week_start, week_end
    )

    assert [(player["telegram_id"], player["points"]) for player in result] == [
        (1, 300),
        (2, 250),
    ]


def test_weekly_earnings_ties_use_creation_time_then_telegram_id():
    players = [
        user(2, 0, created_at=CUTOFF - timedelta(days=2)),
        user(1, 0, created_at=CUTOFF - timedelta(days=2)),
        user(3, 0, created_at=CUTOFF - timedelta(days=1)),
    ]
    history = [
        transaction(player.telegram_id, 100, CUTOFF)
        for player in players
    ]

    result = rank_weekly_earnings_from_ledger(
        players, history, CUTOFF, CUTOFF + timedelta(days=7)
    )

    assert [player["telegram_id"] for player in result] == [1, 2, 3]


def test_weekly_earnings_reject_non_positive_period():
    with pytest.raises(ValueError, match="positive duration"):
        rank_weekly_earnings_from_ledger(
            [user(1, 0)], [], CUTOFF, CUTOFF
        )
