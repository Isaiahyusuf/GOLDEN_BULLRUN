from decimal import Decimal

import pytest

from app.services.weekly_rewards import (
    calculate_weekly_rewards,
    get_utc_week_bounds,
)


def test_weekly_purchases_are_split_sixty_forty():
    team, pool, payouts = calculate_weekly_rewards(Decimal("1000"))

    assert team == Decimal("600.000000000")
    assert pool == Decimal("400.000000000")
    assert payouts == [
        (1, Decimal("200.000000000")),
        (2, Decimal("120.000000000")),
        (3, Decimal("80.000000000")),
    ]


def test_existing_wallet_balance_and_old_liabilities_are_not_inputs():
    team, pool, payouts = calculate_weekly_rewards(Decimal("1000"))

    assert team + pool == Decimal("1000.000000000")
    assert pool == Decimal("400.000000000")
    assert payouts[0][1] == Decimal("200.000000000")


def test_zero_purchases_produce_zero_allocations():
    team, pool, payouts = calculate_weekly_rewards(Decimal("0"))

    assert team == Decimal("0E-9")
    assert pool == Decimal("0E-9")
    assert all(amount == Decimal("0E-9") for _, amount in payouts)


def test_negative_purchase_total_is_treated_as_zero():
    team, pool, payouts = calculate_weekly_rewards(Decimal("-25"))

    assert team == Decimal("0E-9")
    assert pool == Decimal("0E-9")
    assert all(amount == Decimal("0E-9") for _, amount in payouts)


def test_week_bounds_use_monday_utc_and_exclusive_end():
    start, end = get_utc_week_bounds("2026-W42")

    assert start.isoformat() == "2026-10-12T00:00:00+00:00"
    assert end.isoformat() == "2026-10-19T00:00:00+00:00"


def test_invalid_week_key_is_rejected():
    with pytest.raises(ValueError):
        get_utc_week_bounds("not-a-week")


def test_weekly_reward_pool_starts_reserved():
    from app.models.reward import WeeklyRewardPool

    column = WeeklyRewardPool.__table__.c.settlement_status

    assert column.nullable is False
    assert column.default.arg == "reserved"


def test_weekly_snapshot_uses_receipt_time_not_verification_time():
    import asyncio
    from datetime import datetime, timezone

    from sqlalchemy import delete

    from app.database.connection import SessionLocal, engine, init_db
    from app.models.payment import Payment
    from app.models.reward import WeeklyRewardPool, WeeklyRewardPayout
    from app.services.weekly_rewards import create_weekly_reward_snapshot

    week_key = "2024-W01"
    signatures = [
        "weekly-receipt-inside",
        "weekly-receipt-outside",
        "weekly-pending-receipt",
    ]

    def utc(value):
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)

    async def run():
        await init_db()
        try:
            async with SessionLocal() as session:
                async with session.begin():
                    await session.execute(
                        delete(WeeklyRewardPayout).where(
                            WeeklyRewardPayout.week_key == week_key
                        )
                    )
                    await session.execute(
                        delete(WeeklyRewardPool).where(
                            WeeklyRewardPool.week_key == week_key
                        )
                    )
                    await session.execute(
                        delete(Payment).where(
                            Payment.signature.in_(signatures)
                        )
                    )

                    # Received during the week, but verified afterward:
                    # this purchase must count in 2024-W01.
                    session.add(
                        Payment(
                            telegram_id=880009993,
                            package_id="1",
                            purchase_reference="weekly-receipt-in-2024w01",
                            token_mint="test-mint",
                            recipient="test-recipient",
                            token_amount=100,
                            credits=1000,
                            signature=signatures[0],
                            status="credited",
                            verified_at=utc("2024-01-08T00:05:00"),
                            received_at=utc("2024-01-07T23:55:00"),
                        )
                    )

                    # Verified during the week, but received before it:
                    # this purchase must not count in 2024-W01.
                    session.add(
                        Payment(
                            telegram_id=880009994,
                            package_id="1",
                            purchase_reference="weekly-receipt-before-2024w01",
                            token_mint="test-mint",
                            recipient="test-recipient",
                            token_amount=200,
                            credits=1000,
                            signature=signatures[1],
                            status="credited",
                            verified_at=utc("2024-01-02T12:00:00"),
                            received_at=utc("2023-12-31T23:55:00"),
                        )
                    )

                    # A pending payment never counts, even with an
                    # in-week receipt timestamp.
                    session.add(
                        Payment(
                            telegram_id=880009995,
                            package_id="1",
                            purchase_reference="weekly-pending-2024w01",
                            token_mint="test-mint",
                            recipient="test-recipient",
                            token_amount=300,
                            credits=1000,
                            signature=signatures[2],
                            status="pending",
                            verified_at=None,
                            received_at=utc("2024-01-03T12:00:00"),
                        )
                    )

            from unittest.mock import patch

            # This test targets receipt-time accounting, not weekly earnings.
            with patch(
                "app.services.weekly_rewards.rank_weekly_earnings_from_ledger",
                return_value=[],
            ):
                snapshot = await create_weekly_reward_snapshot(week_key)

            assert snapshot["purchase_total"] == 100
            assert snapshot["team_amount"] == 60
            assert snapshot["pool_amount"] == 40
        finally:
            async with SessionLocal() as session:
                async with session.begin():
                    await session.execute(
                        delete(WeeklyRewardPayout).where(
                            WeeklyRewardPayout.week_key == week_key
                        )
                    )
                    await session.execute(
                        delete(WeeklyRewardPool).where(
                            WeeklyRewardPool.week_key == week_key
                        )
                    )
                    await session.execute(
                        delete(Payment).where(
                            Payment.signature.in_(signatures)
                        )
                    )
            await engine.dispose()

    asyncio.run(run())


def _snapshot_validation_fixtures():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    leaderboard = [
        {
            "rank": 1,
            "telegram_id": 101,
            "username": "first",
            "name": "First Player",
            "points": 900,
        },
        {
            "rank": 2,
            "telegram_id": 102,
            "username": "second",
            "name": "Second Player",
            "points": 800,
        },
        {
            "rank": 3,
            "telegram_id": 103,
            "username": "third",
            "name": "Third Player",
            "points": 700,
        },
    ]

    existing = SimpleNamespace(
        week_key="2026-W41",
        leaderboard_snapshot=leaderboard,
        purchase_total=Decimal("100"),
        team_amount=Decimal("60.000000000"),
        pool_amount=Decimal("40.000000000"),
    )

    payouts = [
        SimpleNamespace(
            week_key="2026-W41",
            rank=rank,
            telegram_id=player["telegram_id"],
            amount=amount,
            username=player["username"],
            winner_name=player["name"],
        )
        for player, (rank, amount) in zip(
            leaderboard,
            [
                (1, Decimal("20.000000000")),
                (2, Decimal("12.000000000")),
                (3, Decimal("8.000000000")),
            ],
        )
    ]

    session = SimpleNamespace(
        scalars=AsyncMock(
            return_value=SimpleNamespace(all=lambda: payouts)
        )
    )
    return existing, payouts, session


def test_existing_snapshot_validator_accepts_consistent_snapshot():
    import asyncio

    from app.services.weekly_rewards import _existing_snapshot_result

    existing, payouts, session = _snapshot_validation_fixtures()

    result = asyncio.run(_existing_snapshot_result(session, existing))

    assert result["already_done"] is True
    assert len(result["payouts"]) == 3


@pytest.mark.parametrize(
    "corrupt",
    [
        "invalid_rank",
        "duplicate_player",
        "wrong_username",
        "wrong_winner_name",
        "wrong_payout_amount",
    ],
)
def test_existing_snapshot_validator_rejects_inconsistent_snapshot(corrupt):
    import asyncio

    from app.services.weekly_rewards import _existing_snapshot_result

    existing, payouts, session = _snapshot_validation_fixtures()

    if corrupt == "invalid_rank":
        existing.leaderboard_snapshot[0]["rank"] = 2
    elif corrupt == "duplicate_player":
        existing.leaderboard_snapshot[1]["telegram_id"] = (
            existing.leaderboard_snapshot[0]["telegram_id"]
        )
    elif corrupt == "wrong_username":
        payouts[0].username = "someone_else"
    elif corrupt == "wrong_winner_name":
        payouts[0].winner_name = "Someone Else"
    elif corrupt == "wrong_payout_amount":
        payouts[0].amount = Decimal("999")

    result = asyncio.run(_existing_snapshot_result(session, existing))

    assert result["already_done"] is False
    assert result["error"] == "existing_snapshot_inconsistent"


@pytest.mark.parametrize("bad_total", ["NaN", "Infinity", "-Infinity"])
def test_existing_snapshot_validator_rejects_non_finite_purchase_total(bad_total):
    import asyncio

    from app.services.weekly_rewards import _existing_snapshot_result

    existing, payouts, session = _snapshot_validation_fixtures()
    existing.purchase_total = Decimal(bad_total)

    result = asyncio.run(_existing_snapshot_result(session, existing))

    assert result["already_done"] is False
    assert result["error"] == "existing_snapshot_inconsistent"


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [("rank", True), ("points", True)],
)
def test_existing_snapshot_validator_rejects_boolean_numeric_fields(
    field, bad_value
):
    import asyncio

    from app.services.weekly_rewards import _existing_snapshot_result

    existing, payouts, session = _snapshot_validation_fixtures()
    existing.leaderboard_snapshot[0][field] = bad_value

    result = asyncio.run(_existing_snapshot_result(session, existing))

    assert result["already_done"] is False
    assert result["error"] == "existing_snapshot_inconsistent"
