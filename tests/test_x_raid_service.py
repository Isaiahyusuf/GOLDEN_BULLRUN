import asyncio

from sqlalchemy import delete, select

from app.database.connection import SessionLocal, engine, init_db
from app.models.transaction import PointTransaction
from app.models.user import User
from app.models.x_raid import XRaidCampaign, XRaidClaim
from app.services import x_raid_service


def test_x_post_url_is_validated_and_normalized():
    assert x_raid_service.parse_x_post_url(
        "https://twitter.com/player/status/123456?ref=share"
    ) == ("123456", "https://x.com/player/status/123456")

    try:
        x_raid_service.parse_x_post_url("http://x.com/player/status/123")
    except x_raid_service.XRaidError as exc:
        assert "https" in str(exc)
    else:
        raise AssertionError("An insecure URL should be rejected.")


def test_quiz_answer_matching_ignores_case_and_extra_whitespace():
    assert x_raid_service._answer_hash("The Royal Crown") == (
        x_raid_service._answer_hash("  the   royal crown  ")
    )
    assert x_raid_service._answer_hash("gold") != x_raid_service._answer_hash("silver")


def test_campaign_rewards_are_not_x_engagement_rewards():
    assert x_raid_service.QUIZ_REWARD_POINTS == 200
    assert x_raid_service.MAX_QUIZ_ATTEMPTS == 3


def test_group_play_button_opens_private_bot_missions():
    from app.keyboards.main_menu import private_game_link

    button = private_game_link("missions").inline_keyboard[0][0]

    assert button.url == "https://t.me/TrumptyDumptybot?start=missions"


def test_quiz_claim_awards_once_and_locks_after_three_wrong_answers():
    correct_player_id = 990004001
    locked_player_id = 990004002

    async def run():
        try:
            return await _quiz_claim_run(correct_player_id, locked_player_id)
        finally:
            await engine.dispose()

    result = asyncio.run(run())
    assert result == {
        "wrong_status": "incorrect",
        "correct_status": "correct",
        "repeat_status": "already_claimed",
        "locked_status": "locked",
        "correct_player_points": 1_200,
        "locked_player_points": 1_000,
        "claim_points": 200,
        "claim_attempts": 2,
    }


async def _quiz_claim_run(correct_player_id: int, locked_player_id: int) -> dict:
    await init_db()
    async with SessionLocal() as session:
        async with session.begin():
            await session.execute(
                delete(XRaidClaim).where(
                    XRaidClaim.telegram_id.in_(
                        [correct_player_id, locked_player_id]
                    )
                )
            )
            await session.execute(
                delete(PointTransaction).where(
                    PointTransaction.telegram_id.in_(
                        [correct_player_id, locked_player_id]
                    )
                )
            )
            old_campaign_ids = select(XRaidCampaign.id).where(
                XRaidCampaign.created_by == correct_player_id
            )
            await session.execute(
                delete(XRaidClaim).where(
                    XRaidClaim.campaign_id.in_(old_campaign_ids)
                )
            )
            await session.execute(
                delete(XRaidCampaign).where(
                    XRaidCampaign.created_by == correct_player_id
                )
            )
            await session.execute(
                delete(User).where(
                    User.telegram_id.in_([correct_player_id, locked_player_id])
                )
            )
            session.add_all([
                User(
                    telegram_id=correct_player_id,
                    full_name="Quiz Test Player",
                    points=1_000,
                ),
                User(
                    telegram_id=locked_player_id,
                    full_name="Locked Quiz Player",
                    points=1_000,
                ),
            ])

    campaign = await x_raid_service.set_campaign(
        correct_player_id,
        "https://x.com/owner/status/123456789",
        "What is the featured color?",
        "Royal Blue",
    )
    wrong = await x_raid_service.submit_quiz_answer(
        campaign.id,
        correct_player_id,
        "red",
    )
    correct = await x_raid_service.submit_quiz_answer(
        campaign.id,
        correct_player_id,
        " ROYAL   BLUE ",
    )
    repeat = await x_raid_service.submit_quiz_answer(
        campaign.id,
        correct_player_id,
        "royal blue",
    )

    for answer in ("one", "two", "three", "four"):
        locked = await x_raid_service.submit_quiz_answer(
            campaign.id,
            locked_player_id,
            answer,
        )

    async with SessionLocal() as session:
        async with session.begin():
            correct_player = await session.get(User, correct_player_id)
            locked_player = await session.get(User, locked_player_id)
            claim = await session.get(
                XRaidClaim,
                (campaign.id, correct_player_id),
            )
            result = {
                "wrong_status": wrong["status"],
                "correct_status": correct["status"],
                "repeat_status": repeat["status"],
                "locked_status": locked["status"],
                "correct_player_points": correct_player.points,
                "locked_player_points": locked_player.points,
                "claim_points": claim.awarded_points,
                "claim_attempts": claim.attempts,
            }
            await session.execute(
                delete(XRaidClaim).where(
                    XRaidClaim.campaign_id == campaign.id
                )
            )
            await session.execute(
                delete(PointTransaction).where(
                    PointTransaction.telegram_id.in_(
                        [correct_player_id, locked_player_id]
                    )
                )
            )
            await session.execute(
                delete(XRaidCampaign).where(XRaidCampaign.id == campaign.id)
            )
            await session.execute(
                delete(User).where(
                    User.telegram_id.in_([correct_player_id, locked_player_id])
                )
            )
        return result
