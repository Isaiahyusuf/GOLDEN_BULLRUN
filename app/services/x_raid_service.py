import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import SessionLocal
from app.models.transaction import PointTransaction
from app.models.user import User
from app.models.x_raid import XRaidCampaign, XRaidClaim


QUIZ_REWARD_POINTS = 200
MAX_QUIZ_ATTEMPTS = 3
MAX_QUESTION_LENGTH = 500
MAX_ANSWER_LENGTH = 200
REQUIRED_X_ACTIONS = ("like", "repost", "reply", "follow")


class XRaidError(Exception):
    pass


def parse_x_post_url(value: str) -> tuple[str, str]:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.hostname not in {
        "x.com",
        "www.x.com",
        "twitter.com",
        "www.twitter.com",
    }:
        raise XRaidError("Use a valid https://x.com post link.")

    parts = parsed.path.strip("/").split("/")
    if len(parts) < 3 or parts[1] not in {"status", "statuses"}:
        raise XRaidError("The X link must point to a post, such as x.com/name/status/123.")
    post_id = parts[2]
    if not post_id.isdigit():
        raise XRaidError("The X post link does not contain a valid post ID.")

    return post_id, f"https://x.com/{parts[0]}/status/{post_id}"


def normalize_quiz_answer(value: str) -> str:
    return " ".join(value.casefold().split())


def _answer_hash(value: str) -> str:
    return hashlib.sha256(normalize_quiz_answer(value).encode("utf-8")).hexdigest()


async def get_active_campaign() -> XRaidCampaign | None:
    async with SessionLocal() as session:
        return await session.scalar(
            select(XRaidCampaign)
            .where(XRaidCampaign.active.is_(True))
            .order_by(XRaidCampaign.id.desc())
            .limit(1)
        )


async def get_claim_status(campaign_id: int, telegram_id: int) -> dict:
    async with SessionLocal() as session:
        claim = await session.get(XRaidClaim, (campaign_id, telegram_id))
        if claim is None:
            return {
                "awarded_points": 0,
                "attempts": 0,
                "verified_actions": {},
            }
        return {
            "awarded_points": claim.awarded_points,
            "attempts": claim.attempts,
            "verified_actions": claim.verified_actions,
        }


async def set_campaign(
    admin_telegram_id: int,
    post_url: str,
    question: str,
    answer: str,
) -> XRaidCampaign:
    post_id, canonical_url = parse_x_post_url(post_url)
    question = question.strip()
    answer = answer.strip()
    if not question or len(question) > MAX_QUESTION_LENGTH:
        raise XRaidError(
            f"The quiz question must contain 1 to {MAX_QUESTION_LENGTH} characters."
        )
    if not answer or len(answer) > MAX_ANSWER_LENGTH:
        raise XRaidError(
            f"The answer must contain 1 to {MAX_ANSWER_LENGTH} characters."
        )

    async with SessionLocal() as session:
        async with session.begin():
            await session.execute(
                update(XRaidCampaign)
                .where(XRaidCampaign.active.is_(True))
                .values(active=False)
            )
            campaign = XRaidCampaign(
                post_id=post_id,
                post_url=canonical_url,
                target_user_id="",
                target_username="",
                quiz_question=question,
                quiz_answer_hash=_answer_hash(answer),
                active=True,
                created_by=admin_telegram_id,
            )
            session.add(campaign)
            await session.flush()
            await session.refresh(campaign)
            return campaign


async def stop_campaign() -> bool:
    async with SessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                update(XRaidCampaign)
                .where(XRaidCampaign.active.is_(True))
                .values(active=False)
            )
            return result.rowcount > 0


async def submit_quiz_answer(
    campaign_id: int,
    telegram_id: int,
    answer: str,
    verified_actions: dict[str, bool],
) -> dict:
    if not answer.strip() or len(answer) > MAX_ANSWER_LENGTH:
        raise XRaidError("Send a quiz answer of 1 to 200 characters.")
    if not isinstance(verified_actions, dict) or any(
        not isinstance(verified_actions.get(action), bool)
        for action in REQUIRED_X_ACTIONS
    ):
        raise XRaidError(
            "Like, Repost, Reply, and Follow must all be verified before claiming."
        )

    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        async with session.begin():
            campaign = await session.scalar(
                select(XRaidCampaign)
                .where(
                    XRaidCampaign.id == campaign_id,
                    XRaidCampaign.active.is_(True),
                )
                .with_for_update()
            )
            if campaign is None:
                raise XRaidError("That raid has ended. Open Missions for the current quiz.")
            if not campaign.quiz_question or not campaign.quiz_answer_hash:
                raise XRaidError("This raid quiz is not configured. Please try again later.")

            player = await session.scalar(
                select(User)
                .where(User.telegram_id == telegram_id)
                .with_for_update()
            )
            if player is None:
                raise XRaidError("Send /start before claiming Bullrun Points.")

            claim_insert = insert(XRaidClaim).values(
                campaign_id=campaign_id,
                telegram_id=telegram_id,
                verified_actions={},
                awarded_points=0,
                attempts=0,
                last_checked_at=None,
                updated_at=now,
            ).on_conflict_do_nothing(
                index_elements=[
                    XRaidClaim.campaign_id,
                    XRaidClaim.telegram_id,
                ]
            )
            await session.execute(claim_insert)
            claim = await session.scalar(
                select(XRaidClaim)
                .where(
                    XRaidClaim.campaign_id == campaign_id,
                    XRaidClaim.telegram_id == telegram_id,
                )
                .with_for_update()
            )
            if claim is None:
                raise XRaidError("Your quiz attempt could not be recorded. Please try again.")
            if claim.awarded_points:
                return {
                    "status": "already_claimed",
                    "points_awarded": 0,
                    "attempts_left": max(0, MAX_QUIZ_ATTEMPTS - claim.attempts),
                }
            if claim.attempts >= MAX_QUIZ_ATTEMPTS:
                return {
                    "status": "locked",
                    "points_awarded": 0,
                    "attempts_left": 0,
                }

            claim.attempts += 1
            claim.updated_at = now
            if not hmac.compare_digest(
                _answer_hash(answer),
                campaign.quiz_answer_hash,
            ):
                return {
                    "status": "incorrect",
                    "points_awarded": 0,
                    "attempts_left": MAX_QUIZ_ATTEMPTS - claim.attempts,
                }

            if not all(verified_actions[action] for action in REQUIRED_X_ACTIONS):
                raise XRaidError(
                    "Like, Repost, Reply, and Follow must all be verified before claiming."
                )

            claim.verified_actions = verified_actions
            claim.last_checked_at = now
            claim.awarded_points = QUIZ_REWARD_POINTS
            player.points += QUIZ_REWARD_POINTS
            session.add(
                PointTransaction(
                    telegram_id=telegram_id,
                    amount=QUIZ_REWARD_POINTS,
                    reason=f"x_raid_quiz:{campaign_id}",
                )
            )
            return {
                "status": "correct",
                "points_awarded": QUIZ_REWARD_POINTS,
                "attempts_left": MAX_QUIZ_ATTEMPTS - claim.attempts,
            }


async def is_quiz_answer_correct(campaign_id: int, answer: str) -> bool:
    if not answer.strip() or len(answer) > MAX_ANSWER_LENGTH:
        raise XRaidError("Send a quiz answer of 1 to 200 characters.")

    campaign = await get_active_campaign()
    if campaign is None or campaign.id != campaign_id:
        raise XRaidError("That raid has ended. Open Missions for the current quiz.")
    if not campaign.quiz_question or not campaign.quiz_answer_hash:
        raise XRaidError("This raid quiz is not configured. Please try again later.")
    return hmac.compare_digest(
        _answer_hash(answer),
        campaign.quiz_answer_hash,
    )


async def record_verified_actions(
    campaign_id: int,
    telegram_id: int,
    verified_actions: dict[str, bool],
) -> None:
    if not isinstance(verified_actions, dict) or any(
        not isinstance(verified_actions.get(action), bool)
        for action in REQUIRED_X_ACTIONS
    ):
        raise XRaidError("The X action check returned invalid results.")

    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        async with session.begin():
            campaign = await session.scalar(
                select(XRaidCampaign)
                .where(
                    XRaidCampaign.id == campaign_id,
                    XRaidCampaign.active.is_(True),
                )
                .with_for_update()
            )
            if campaign is None:
                raise XRaidError(
                    "That raid has ended. Open Missions for the current quiz."
                )

            if await session.get(User, telegram_id) is None:
                raise XRaidError("Send /start before claiming Bullrun Points.")

            await session.execute(
                insert(XRaidClaim)
                .values(
                    campaign_id=campaign_id,
                    telegram_id=telegram_id,
                    verified_actions=verified_actions,
                    awarded_points=0,
                    attempts=0,
                    last_checked_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[
                        XRaidClaim.campaign_id,
                        XRaidClaim.telegram_id,
                    ],
                    set_={
                        "verified_actions": verified_actions,
                        "last_checked_at": now,
                        "updated_at": now,
                    },
                )
            )
