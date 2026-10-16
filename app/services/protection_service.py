from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.connection import SessionLocal
from app.models.user import User
from app.models.transaction import PointTransaction
from app.models.weekly_reset import WeeklyReset
from app.models.reward import WeeklyRewardPool


PROTECTION_PRICE = 30_000
PROTECTION_DAYS = 7
MAX_PROTECTION_RANK = 5
MAX_PROTECTION_PRICE = 150_000
STARTING_POINTS = 10_000


def get_protection_rank(player):
    return min(max(int(getattr(player, "protection_rank", 0)), 0), MAX_PROTECTION_RANK)


def get_protection_price(current_rank):
    next_rank = min(max(current_rank, 0) + 1, MAX_PROTECTION_RANK)
    return min(PROTECTION_PRICE * next_rank, MAX_PROTECTION_PRICE)


def get_protected_percentage(rank):
    return min(max(rank, 0), MAX_PROTECTION_RANK) * 20


def protected_points_after_reset(points, rank):
    if points <= STARTING_POINTS:
        return points
    protected_excess = (points - STARTING_POINTS) * get_protected_percentage(rank) // 100
    return STARTING_POINTS + protected_excess


def utc_now():
    return datetime.now(timezone.utc)


def protection_is_active(player, now=None):
    now = now or utc_now()
    expiry = player.protection_expires_at

    if expiry is None:
        return False

    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    return expiry > now


async def get_protection_status(telegram_id):
    async with SessionLocal() as session:
        player = await session.get(User, telegram_id)

        if player is None:
            return None

        active = protection_is_active(player)

        return {
            "active": active,
            "expires_at": player.protection_expires_at if active else None,
            "rank": get_protection_rank(player),
            "protected_percentage": get_protected_percentage(
                get_protection_rank(player)
            ),
            "price": get_protection_price(get_protection_rank(player)),
            "duration_days": PROTECTION_DAYS,
        }


async def activate_protection(telegram_id, now=None):
    """Call only after the payment has been verified."""
    now = now or utc_now()

    async with SessionLocal() as session:
        async with session.begin():
            player = await session.scalar(
                select(User)
                .where(User.telegram_id == telegram_id)
                .with_for_update()
            )

            if player is None:
                return False

            player.protection_rank = min(
                get_protection_rank(player) + 1,
                MAX_PROTECTION_RANK,
            )
            expiry = player.protection_expires_at

            if expiry is not None and expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)

            base = expiry if expiry and expiry > now else now
            player.protection_expires_at = base + timedelta(
                days=PROTECTION_DAYS
            )

            session.add(
                PointTransaction(
                    telegram_id=telegram_id,
                    amount=0,
                    reason="protection_activated",
                )
            )

    return True


def _valid_recovery_snapshot(snapshot, week_key):
    return (
        isinstance(snapshot, dict)
        and not snapshot.get("error")
        and snapshot.get("week_key") == week_key
        and isinstance(snapshot.get("leaderboard"), list)
        and isinstance(snapshot.get("payouts"), list)
        and all(
            field in snapshot
            for field in ("purchase_total", "team_amount", "pool_amount")
        )
        and snapshot.get("already_done") in (True, False)
    )


async def recover_weekly_resets(now=None):
    """Recover missing weekly snapshots, then reset current points at most once."""
    from app.services.weekly_rewards import (
        create_weekly_reward_snapshot,
        validate_existing_weekly_snapshot,
        get_completed_week_key,
        get_utc_week_bounds,
    )

    now = now or utc_now()
    target_key = get_completed_week_key(now)

    async with SessionLocal() as session:
        reset_rows = list(
            (
                await session.scalars(
                    select(WeeklyReset).order_by(WeeklyReset.reset_key.asc())
                )
            ).all()
        )

    # A new installation starts from the latest completed week.
    if not reset_rows:
        return await apply_weekly_reset(target_key, now=now)

    last_reset_key = reset_rows[-1].reset_key

    if last_reset_key > target_key:
        return {
            "reset": 0,
            "skipped": 0,
            "blocked": True,
            "reason": "reset_history_ahead_of_target",
            "week_key": target_key,
        }

    # A completed reset must already have its own valid snapshot.
    # Never invent a late snapshot for a week whose points were reset.
    async with SessionLocal() as session:
        previous_pool = await session.get(WeeklyRewardPool, last_reset_key)

    if previous_pool is None:
        return {
            "reset": 0,
            "skipped": 0,
            "blocked": True,
            "reason": "completed_reset_snapshot_missing",
            "week_key": last_reset_key,
        }

    previous_snapshot = await validate_existing_weekly_snapshot(last_reset_key)
    if not _valid_recovery_snapshot(previous_snapshot, last_reset_key):
        return {
            "reset": 0,
            "skipped": 0,
            "blocked": True,
            "reason": "completed_reset_snapshot_invalid",
            "week_key": last_reset_key,
        }

    if last_reset_key == target_key:
        return {
            "reset": 0,
            "skipped": 0,
            "already_done": True,
            "week_key": target_key,
        }

    # Fill every missing snapshot in chronological order.
    cursor = get_utc_week_bounds(last_reset_key)[1]
    target_start, _ = get_utc_week_bounds(target_key)

    while cursor <= target_start:
        week_key = cursor.strftime("%G-W%V")
        snapshot = await create_weekly_reward_snapshot(week_key)

        if not _valid_recovery_snapshot(snapshot, week_key):
            return {
                "reset": 0,
                "skipped": 0,
                "blocked": True,
                "reason": snapshot.get("error", "recovery_snapshot_invalid")
                if isinstance(snapshot, dict)
                else "recovery_snapshot_invalid",
                "week_key": week_key,
            }

        cursor += timedelta(days=7)

    # Only the latest completed week performs a live points reset.
    return await apply_weekly_reset(target_key, now=now)


async def apply_weekly_reset(reset_key, now=None):
    """Save the weekly reward snapshot before resetting any points."""
    if not reset_key or len(reset_key) > 32:
        raise ValueError("A valid reset key is required.")

    # Do not create a late snapshot for a reset that already happened.
    async with SessionLocal() as session:
        existing_reset = await session.get(WeeklyReset, reset_key)
        if existing_reset is not None:
            return {
                "reset": 0,
                "skipped": 0,
                "already_done": True,
            }

    # The reset key must be an ISO week key, such as 2026-W42.
    # If snapshot creation raises an exception, no points are reset.
    from app.services.weekly_rewards import create_weekly_reward_snapshot

    snapshot = await create_weekly_reward_snapshot(reset_key)

    if snapshot.get("error"):
        return {
            "reset": 0,
            "skipped": 0,
            "already_done": False,
            "blocked": True,
            "reason": snapshot["error"],
        }

    snapshot_is_valid = (
        snapshot.get("week_key") == reset_key
        and isinstance(snapshot.get("leaderboard"), list)
        and isinstance(snapshot.get("payouts"), list)
        and all(
            field in snapshot
            for field in ("purchase_total", "team_amount", "pool_amount")
        )
        and snapshot.get("already_done") in (True, False)
    )

    if not snapshot_is_valid:
        return {
            "reset": 0,
            "skipped": 0,
            "already_done": False,
            "blocked": True,
            "reason": "invalid_snapshot_result",
        }

    now = now or utc_now()
    reset_count = 0
    skipped_count = 0

    try:
        async with SessionLocal() as session:
            async with session.begin():
                session.add(WeeklyReset(reset_key=reset_key))
                await session.flush()

                players = (
                    await session.scalars(
                        select(User).with_for_update()
                    )
                ).all()

                for player in players:
                    if protection_is_active(player, now):
                        skipped_count += 1
                        protected_points = protected_points_after_reset(
                            player.points,
                            get_protection_rank(player),
                        )
                        if protected_points == player.points:
                            continue

                    old_points = player.points
                    if protection_is_active(player, now):
                        player.points = protected_points
                    else:
                        player.points = STARTING_POINTS
                    reset_count += 1

                    session.add(
                        PointTransaction(
                            telegram_id=player.telegram_id,
                            amount=player.points - old_points,
                            reason=f"weekly_reset:{reset_key}",
                        )
                    )

    except IntegrityError as error:
        original = getattr(error, "orig", None)
        sqlstate = getattr(original, "sqlstate", None)

        if sqlstate == "23505":
            return {
                "reset": 0,
                "skipped": 0,
                "already_done": True,
            }

        raise

    return {
        "reset": reset_count,
        "skipped": skipped_count,
        "already_done": False,
        "week_key": reset_key,
        "snapshot_created": True,
    }
