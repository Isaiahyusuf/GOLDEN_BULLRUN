from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.database.connection import SessionLocal
from app.models.payment import Payment
from app.models.reward import WeeklyRewardPool, WeeklyRewardPayout
from app.models.transaction import PointTransaction
from app.models.user import User
from app.services.historical_leaderboard import (
    HistoricalLedgerError,
    reconstruct_leaderboard_from_ledger,
)


TEAM_RATE = Decimal("0.60")
POOL_RATE = Decimal("0.40")
REWARD_SHARES = (
    (1, Decimal("0.50")),
    (2, Decimal("0.30")),
    (3, Decimal("0.20")),
)
TOKEN_QUANTUM = Decimal("0.000000001")


def calculate_weekly_rewards(purchase_total):
    total = max(Decimal(str(purchase_total)), Decimal("0"))
    total = total.quantize(TOKEN_QUANTUM, rounding=ROUND_DOWN)

    team_amount = (total * TEAM_RATE).quantize(
        TOKEN_QUANTUM, rounding=ROUND_DOWN
    )
    pool_amount = (total * POOL_RATE).quantize(
        TOKEN_QUANTUM, rounding=ROUND_DOWN
    )
    payouts = [
        (
            rank,
            (pool_amount * share).quantize(
                TOKEN_QUANTUM, rounding=ROUND_DOWN
            ),
        )
        for rank, share in REWARD_SHARES
    ]

    return team_amount, pool_amount, payouts


def get_utc_week_bounds(week_key):
    try:
        start = datetime.strptime(
            f"{week_key}-1", "%G-W%V-%u"
        ).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(
            "Week key must use ISO format YYYY-Www, such as 2026-W42."
        ) from exc

    if start.strftime("%G-W%V") != week_key:
        raise ValueError(
            "Week key must use ISO format YYYY-Www, such as 2026-W42."
        )

    return start, start + timedelta(days=7)


def get_completed_week_key(now=None):
    """Return the ISO week key for the last fully completed UTC week."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    current_week_start = (
        now.replace(hour=0, minute=0, second=0, microsecond=0)
        - timedelta(days=now.weekday())
    )
    previous_week_start = current_week_start - timedelta(days=7)
    return previous_week_start.strftime("%G-W%V")


async def _existing_snapshot_result(session, existing):
    leaderboard = existing.leaderboard_snapshot

    if not isinstance(leaderboard, list):
        return {
            "already_done": False,
            "week_key": existing.week_key,
            "error": "existing_snapshot_incomplete",
        }

    if (
        existing.purchase_total is None
        or existing.team_amount is None
        or existing.pool_amount is None
    ):
        return {
            "already_done": False,
            "week_key": existing.week_key,
            "error": "existing_snapshot_incomplete",
        }

    try:
        purchase_total = Decimal(str(existing.purchase_total))
        stored_team = Decimal(str(existing.team_amount))
        stored_pool = Decimal(str(existing.pool_amount))
        if not all(
            value.is_finite()
            for value in (purchase_total, stored_team, stored_pool)
        ) or purchase_total < 0:
            raise InvalidOperation

        expected_team, expected_pool, expected_payouts = (
            calculate_weekly_rewards(purchase_total)
        )
    except (InvalidOperation, TypeError, ValueError, ArithmeticError):
        return {
            "already_done": False,
            "week_key": existing.week_key,
            "error": "existing_snapshot_inconsistent",
        }

    if stored_team != expected_team or stored_pool != expected_pool:
        return {
            "already_done": False,
            "week_key": existing.week_key,
            "error": "existing_snapshot_inconsistent",
        }

    # Validate the complete stored leaderboard before trusting its winners.
    seen_ids = set()
    for rank, player in enumerate(leaderboard, start=1):
        if (
            not isinstance(player, dict)
            or isinstance(player.get("rank"), bool)
            or not isinstance(player.get("rank"), int)
            or player.get("rank") != rank
            or isinstance(player.get("telegram_id"), bool)
            or not isinstance(player.get("telegram_id"), int)
            or isinstance(player.get("points"), bool)
            or not isinstance(player.get("points"), int)
            or player["points"] < 0
            or not isinstance(player.get("name"), str)
            or not player["name"].strip()
        ):
            return {
                "already_done": False,
                "week_key": existing.week_key,
                "error": "existing_snapshot_inconsistent",
            }

        telegram_id = player["telegram_id"]
        if telegram_id in seen_ids:
            return {
                "already_done": False,
                "week_key": existing.week_key,
                "error": "existing_snapshot_inconsistent",
            }
        seen_ids.add(telegram_id)

        username = player.get("username")
        if username is not None and not isinstance(username, str):
            return {
                "already_done": False,
                "week_key": existing.week_key,
                "error": "existing_snapshot_inconsistent",
            }

    stored_payouts = list(
        (
            await session.scalars(
                select(WeeklyRewardPayout)
                .where(WeeklyRewardPayout.week_key == existing.week_key)
                .order_by(WeeklyRewardPayout.rank.asc())
            )
        ).all()
    )
    expected_winners = leaderboard[:3]

    if len(stored_payouts) != len(expected_winners):
        return {
            "already_done": False,
            "week_key": existing.week_key,
            "error": "existing_snapshot_inconsistent",
        }

    payout_results = []
    for player, payout, expected in zip(
        expected_winners, stored_payouts, expected_payouts
    ):
        try:
            payout_amount = Decimal(str(payout.amount))
            amount_is_valid = payout_amount.is_finite()
        except (InvalidOperation, TypeError, ValueError, ArithmeticError):
            amount_is_valid = False
            payout_amount = None

        if (
            payout.week_key != existing.week_key
            or payout.rank != player["rank"]
            or payout.telegram_id != player["telegram_id"]
            or payout.rank != expected[0]
            or not amount_is_valid
            or payout_amount != expected[1]
            or payout.username != player.get("username")
            or payout.winner_name != player["name"]
        ):
            return {
                "already_done": False,
                "week_key": existing.week_key,
                "error": "existing_snapshot_inconsistent",
            }

        payout_results.append({
            "rank": payout.rank,
            "telegram_id": payout.telegram_id,
            "amount": payout.amount,
        })

    return {
        "already_done": True,
        "week_key": existing.week_key,
        "purchase_total": existing.purchase_total,
        "team_amount": existing.team_amount,
        "pool_amount": existing.pool_amount,
        "leaderboard": leaderboard,
        "payouts": payout_results,
    }


async def validate_existing_weekly_snapshot(week_key):
    """Read-only validation; never creates or changes a reward snapshot."""
    try:
        get_utc_week_bounds(week_key)
    except (TypeError, ValueError):
        return {
            "already_done": False,
            "week_key": week_key,
            "error": "invalid_week_key",
        }

    async with SessionLocal() as session:
        existing = await session.get(WeeklyRewardPool, week_key)
        if existing is None:
            return {
                "already_done": False,
                "week_key": week_key,
                "error": "existing_snapshot_missing",
            }

        return await _existing_snapshot_result(session, existing)


async def create_weekly_reward_snapshot(week_key):
    if not week_key or len(week_key) > 32:
        raise ValueError("A valid week key is required.")

    week_start, week_end = get_utc_week_bounds(week_key)

    try:
        async with SessionLocal() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(829441007)")
                )

                existing = await session.get(WeeklyRewardPool, week_key)
                if existing:
                    return await _existing_snapshot_result(session, existing)

                purchase_total = await session.scalar(
                    select(
                        func.coalesce(func.sum(Payment.token_amount), 0)
                    ).where(
                        Payment.status == "credited",
                        Payment.received_at >= week_start,
                        Payment.received_at < week_end,
                    )
                )
                purchase_total = Decimal(str(purchase_total or 0))

                team_amount, pool_amount, payouts = (
                    calculate_weekly_rewards(purchase_total)
                )

                users = list(
                    (await session.scalars(select(User))).all()
                )
                transactions = list(
                    (
                        await session.scalars(
                            select(PointTransaction).order_by(
                                PointTransaction.id.asc()
                            )
                        )
                    ).all()
                )

                try:
                    snapshot = reconstruct_leaderboard_from_ledger(
                        users,
                        transactions,
                        cutoff=week_end,
                        limit=10,
                    )
                except HistoricalLedgerError:
                    return {
                        "already_done": False,
                        "week_key": week_key,
                        "error": "historical_leaderboard_unavailable",
                    }

                session.add(
                    WeeklyRewardPool(
                        week_key=week_key,
                        balance_snapshot=Decimal("0"),
                        purchase_total=purchase_total,
                        team_amount=team_amount,
                        pool_amount=pool_amount,
                        leaderboard_snapshot=snapshot,
                    )
                )
                await session.flush()

                for player, (rank, amount) in zip(snapshot[:3], payouts):
                    session.add(
                        WeeklyRewardPayout(
                            week_key=week_key,
                            rank=rank,
                            telegram_id=player["telegram_id"],
                            username=player["username"],
                            winner_name=player["name"],
                            amount=amount,
                            status="pending_wallet",
                        )
                    )

                result = {
                    "already_done": False,
                    "week_key": week_key,
                    "purchase_total": purchase_total,
                    "team_amount": team_amount,
                    "pool_amount": pool_amount,
                    "leaderboard": snapshot,
                    "payouts": [
                        {
                            "rank": rank,
                            "telegram_id": player["telegram_id"],
                            "amount": amount,
                        }
                        for player, (rank, amount) in zip(
                            snapshot[:3], payouts
                        )
                    ],
                }

        return result

    except IntegrityError:
        async with SessionLocal() as session:
            existing = await session.get(WeeklyRewardPool, week_key)
            if existing:
                return await _existing_snapshot_result(session, existing)
        raise
