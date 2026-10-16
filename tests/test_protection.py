from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.protection_service import (
    MAX_PROTECTION_PRICE,
    MAX_PROTECTION_RANK,
    PROTECTION_DAYS,
    PROTECTION_PRICE,
    get_protected_percentage,
    get_protection_price,
    protection_is_active,
    protected_points_after_reset,
)


def test_protection_price_and_duration():
    assert PROTECTION_PRICE == 30_000
    assert PROTECTION_DAYS == 7


def test_protection_rank_increases_preserved_share_and_price_with_caps():
    assert MAX_PROTECTION_RANK == 5
    assert MAX_PROTECTION_PRICE == 150_000
    assert [
        get_protected_percentage(rank) for rank in range(1, 6)
    ] == [20, 40, 60, 80, 100]
    assert [
        get_protection_price(rank) for rank in range(5)
    ] == [30_000, 60_000, 90_000, 120_000, 150_000]
    assert get_protection_price(5) == 150_000


def test_weekly_reset_preserves_rank_share_above_starting_balance():
    points = 60_000

    assert protected_points_after_reset(points, 1) == 20_000
    assert protected_points_after_reset(points, 2) == 30_000
    assert protected_points_after_reset(points, 3) == 40_000
    assert protected_points_after_reset(points, 4) == 50_000
    assert protected_points_after_reset(points, 5) == 60_000


def test_weekly_reset_does_not_raise_protected_balance_to_starting_balance():
    assert protected_points_after_reset(8_000, 3) == 8_000
    assert protected_points_after_reset(10_000, 3) == 10_000


def test_protection_is_active_before_expiry():
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    player = SimpleNamespace(
        protection_expires_at=now + timedelta(days=1)
    )
    assert protection_is_active(player, now)


def test_protection_is_inactive_after_expiry():
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    player = SimpleNamespace(
        protection_expires_at=now - timedelta(seconds=1)
    )
    assert not protection_is_active(player, now)


def test_protection_is_inactive_without_expiry():
    player = SimpleNamespace(protection_expires_at=None)
    assert not protection_is_active(player)


def test_protection_is_active_at_expiry_boundary():
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    player = SimpleNamespace(protection_expires_at=now)
    assert not protection_is_active(player, now)


def test_protection_handles_naive_database_datetime():
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    player = SimpleNamespace(
        protection_expires_at=datetime(2026, 10, 17)
    )
    assert protection_is_active(player, now)


def test_protection_is_inactive_when_naive_expiry_has_passed():
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    player = SimpleNamespace(
        protection_expires_at=datetime(2026, 10, 15)
    )
    assert not protection_is_active(player, now)
