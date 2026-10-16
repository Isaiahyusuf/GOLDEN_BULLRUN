from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.protection_service import apply_weekly_reset


def mock_database_session(existing_reset=None):
    session = MagicMock()
    session.get = AsyncMock(return_value=existing_reset)

    factory = MagicMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = context

    return factory, session


@pytest.mark.asyncio
async def test_reset_is_blocked_when_snapshot_creation_fails():
    factory, session = mock_database_session()

    with patch(
        "app.services.protection_service.SessionLocal", factory
    ), patch(
        "app.services.weekly_rewards.create_weekly_reward_snapshot",
        new_callable=AsyncMock,
        side_effect=RuntimeError("snapshot database failure"),
    ) as snapshot:
        with pytest.raises(RuntimeError, match="snapshot database failure"):
            await apply_weekly_reset("2026-W42")

    snapshot.assert_awaited_once_with("2026-W42")
    session.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_is_blocked_when_snapshot_returns_error():
    factory, session = mock_database_session()

    with patch(
        "app.services.protection_service.SessionLocal", factory
    ), patch(
        "app.services.weekly_rewards.create_weekly_reward_snapshot",
        new_callable=AsyncMock,
        return_value={
            "already_done": False,
            "error": "snapshot_unavailable",
        },
    ) as snapshot:
        result = await apply_weekly_reset("2026-W42")

    assert result["blocked"] is True
    assert result["reason"] == "snapshot_unavailable"
    assert result["reset"] == 0
    snapshot.assert_awaited_once_with("2026-W42")
    session.get.assert_awaited_once()


@pytest.mark.parametrize(
    "snapshot_result",
    [
        {
            "already_done": True,
            "week_key": "2026-W42",
            "purchase_total": 0,
            "team_amount": 0,
            "pool_amount": 0,
        },
        {
            "already_done": True,
            "week_key": "2026-W42",
            "purchase_total": 0,
            "team_amount": 0,
            "pool_amount": 0,
            "leaderboard": [],
        },
        {
            "already_done": False,
            "purchase_total": 0,
            "team_amount": 0,
            "pool_amount": 0,
            "leaderboard": [],
            "payouts": [],
        },
        {
            "already_done": False,
            "week_key": "2026-W41",
            "purchase_total": 0,
            "team_amount": 0,
            "pool_amount": 0,
            "leaderboard": [],
            "payouts": [],
        },
    ],
)
@pytest.mark.asyncio
async def test_reset_is_blocked_when_snapshot_result_is_invalid(
    snapshot_result,
):
    factory, session = mock_database_session()

    with patch(
        "app.services.protection_service.SessionLocal", factory
    ), patch(
        "app.services.weekly_rewards.create_weekly_reward_snapshot",
        new_callable=AsyncMock,
        return_value=snapshot_result,
    ):
        result = await apply_weekly_reset("2026-W42")

    assert result["blocked"] is True
    assert result["reason"] == "invalid_snapshot_result"
    assert result["reset"] == 0
    session.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_reset_does_not_create_another_snapshot():
    factory, session = mock_database_session(existing_reset=object())

    with patch(
        "app.services.protection_service.SessionLocal", factory
    ), patch(
        "app.services.weekly_rewards.create_weekly_reward_snapshot",
        new_callable=AsyncMock,
    ) as snapshot:
        result = await apply_weekly_reset("2026-W42")

    assert result["already_done"] is True
    assert result["reset"] == 0
    snapshot.assert_not_awaited()
    session.get.assert_awaited_once()


from datetime import datetime, timezone


def recovery_session(reset_keys, existing_pool=None):
    factory, session = mock_database_session()
    scalar_result = MagicMock()
    scalar_result.all.return_value = [
        MagicMock(reset_key=key) for key in reset_keys
    ]
    session.scalars = AsyncMock(return_value=scalar_result)
    session.get = AsyncMock(return_value=existing_pool)
    return factory, session


def valid_recovery_snapshot(week_key):
    return {
        "already_done": True,
        "week_key": week_key,
        "purchase_total": 0,
        "team_amount": 0,
        "pool_amount": 0,
        "leaderboard": [],
        "payouts": [],
    }


@pytest.mark.asyncio
async def test_recovery_bootstraps_only_latest_completed_week():
    from app.services.protection_service import recover_weekly_resets

    factory, _ = recovery_session([])
    now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)

    with patch(
        "app.services.protection_service.SessionLocal", factory
    ), patch(
        "app.services.protection_service.apply_weekly_reset",
        new_callable=AsyncMock,
        return_value={"reset": 2, "skipped": 0},
    ) as apply_reset, patch(
        "app.services.weekly_rewards.create_weekly_reward_snapshot",
        new_callable=AsyncMock,
    ) as snapshot:
        result = await recover_weekly_resets(now=now)

    assert result["reset"] == 2
    apply_reset.assert_awaited_once_with("2026-W41", now=now)
    snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_snapshots_missed_weeks_in_order_before_reset():
    from app.services.protection_service import recover_weekly_resets

    factory, _ = recovery_session(["2026-W39"], existing_pool=object())
    now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)

    async def make_snapshot(week_key):
        return valid_recovery_snapshot(week_key)

    with patch(
        "app.services.protection_service.SessionLocal", factory
    ), patch(
        "app.services.weekly_rewards.validate_existing_weekly_snapshot",
        new_callable=AsyncMock,
        return_value=valid_recovery_snapshot("2026-W39"),
    ), patch(
        "app.services.weekly_rewards.create_weekly_reward_snapshot",
        new_callable=AsyncMock,
        side_effect=make_snapshot,
    ) as snapshot, patch(
        "app.services.protection_service.apply_weekly_reset",
        new_callable=AsyncMock,
        return_value={"reset": 3, "skipped": 1},
    ) as apply_reset:
        result = await recover_weekly_resets(now=now)

    assert result["reset"] == 3
    assert [call.args[0] for call in snapshot.await_args_list] == [
        "2026-W40",
        "2026-W41",
    ]
    apply_reset.assert_awaited_once_with("2026-W41", now=now)


@pytest.mark.asyncio
async def test_recovery_blocks_when_previous_reset_snapshot_is_missing():
    from app.services.protection_service import recover_weekly_resets

    factory, _ = recovery_session(["2026-W40"], existing_pool=None)
    now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)

    with patch(
        "app.services.protection_service.SessionLocal", factory
    ), patch(
        "app.services.weekly_rewards.create_weekly_reward_snapshot",
        new_callable=AsyncMock,
    ) as snapshot, patch(
        "app.services.protection_service.apply_weekly_reset",
        new_callable=AsyncMock,
    ) as apply_reset:
        result = await recover_weekly_resets(now=now)

    assert result["blocked"] is True
    assert result["reason"] == "completed_reset_snapshot_missing"
    snapshot.assert_not_awaited()
    apply_reset.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_blocks_reset_when_intermediate_snapshot_fails():
    from app.services.protection_service import recover_weekly_resets

    factory, _ = recovery_session(["2026-W39"], existing_pool=object())
    now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)

    async def make_snapshot(week_key):
        if week_key == "2026-W40":
            return {
                "already_done": False,
                "week_key": week_key,
                "error": "historical_leaderboard_unavailable",
            }
        return valid_recovery_snapshot(week_key)

    with patch(
        "app.services.protection_service.SessionLocal", factory
    ), patch(
        "app.services.weekly_rewards.validate_existing_weekly_snapshot",
        new_callable=AsyncMock,
        return_value=valid_recovery_snapshot("2026-W39"),
    ), patch(
        "app.services.weekly_rewards.create_weekly_reward_snapshot",
        new_callable=AsyncMock,
        side_effect=make_snapshot,
    ) as snapshot, patch(
        "app.services.protection_service.apply_weekly_reset",
        new_callable=AsyncMock,
    ) as apply_reset:
        result = await recover_weekly_resets(now=now)

    assert result["blocked"] is True
    assert result["week_key"] == "2026-W40"
    assert [call.args[0] for call in snapshot.await_args_list] == [
        "2026-W40",
    ]
    apply_reset.assert_not_awaited()
