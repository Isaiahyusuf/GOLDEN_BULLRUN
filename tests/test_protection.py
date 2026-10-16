from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.protection_service import (
    PROTECTION_DAYS,
    PROTECTION_PRICE,
    protection_is_active,
)


def test_protection_price_and_duration():
    assert PROTECTION_PRICE == 30_000
    assert PROTECTION_DAYS == 7


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
