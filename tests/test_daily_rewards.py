from datetime import date
import asyncio
from unittest.mock import AsyncMock

from app.services.daily_rewards import (
    DAILY_REWARD_LADDER,
    DUEL_DAILY_CAP,
    MESSAGE_DAILY_CAP,
    activity_score,
    settle_daily_rewards,
)


def test_daily_activity_score_weights_and_caps_messages():
    assert activity_score(20, 0, 0) == 20
    assert activity_score(100, 2, 1) == 45


def test_daily_reward_hierarchy_is_descending_and_awards_five_places():
    assert DAILY_REWARD_LADDER == (500, 350, 250, 150, 100)
    assert len(DAILY_REWARD_LADDER) == 5
    assert list(DAILY_REWARD_LADDER) == sorted(
        DAILY_REWARD_LADDER, reverse=True
    )
    assert DUEL_DAILY_CAP == 5
    assert MESSAGE_DAILY_CAP == 20


def test_daily_settlement_returns_nothing_if_already_settled(monkeypatch):
    class Result:
        rowcount = 0

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def begin(self):
            return self

        async def execute(self, statement):
            return Result()

    class SessionMaker:
        def __call__(self):
            return Session()

    monkeypatch.setattr(
        "app.services.daily_rewards.SessionLocal",
        SessionMaker(),
    )

    result = asyncio.run(settle_daily_rewards(date(2026, 10, 15)))

    assert result == {
        "day_key": date(2026, 10, 15),
        "already_settled": True,
        "winners": [],
    }


def test_group_activity_is_not_gated_by_pvp_group_id(monkeypatch):
    from datetime import datetime, timezone

    from app.config import settings
    from app.services.daily_rewards import record_group_message

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def begin(self):
            return self

        scalar = AsyncMock(side_effect=[123, 123])

    class SessionMaker:
        def __call__(self):
            return Session()

    monkeypatch.setattr(settings, "pvp_group_id", None)
    monkeypatch.setattr(
        "app.services.daily_rewards.SessionLocal",
        SessionMaker(),
    )

    recorded = asyncio.run(
        record_group_message(
            123,
            now=datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
        )
    )

    assert recorded is True
