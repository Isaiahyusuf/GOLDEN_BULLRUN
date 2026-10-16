import asyncio
import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlencode, urlsplit

import aiohttp
from aiogram.exceptions import TelegramAPIError
from aiohttp import web
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database.connection import SessionLocal
from app.models.user import User
from app.models.x_account import XAccountLink, XOAuthState
from app.models.x_raid import XRaidCampaign


X_AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
X_API_BASE_URL = "https://api.x.com/2"
X_TOKEN_URL = f"{X_API_BASE_URL}/oauth2/token"
X_REQUIRED_SCOPES = {
    "users.read",
    "tweet.read",
    "like.read",
    "follows.read",
    "offline.access",
}
X_ACTION_LABELS = {
    "like": "Like the campaign post",
    "repost": "Repost the campaign post",
    "reply": "Reply to the campaign post",
    "follow": "Follow the post author",
}
X_OAUTH_STATE_LIFETIME = timedelta(minutes=10)
X_TOKEN_REFRESH_MARGIN = timedelta(minutes=2)
X_LOOKUP_MAX_PAGES = 20


class XOAuthError(RuntimeError):
    pass


def x_oauth_configured() -> bool:
    if not (
        settings.x_api_client_id
        and settings.x_api_redirect_uri
        and settings.x_api_token_encryption_key
    ):
        return False

    redirect = urlsplit(settings.x_api_redirect_uri)
    if redirect.scheme != "https" or not redirect.netloc:
        return False
    try:
        Fernet(settings.x_api_token_encryption_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False
    return True


def _validate_configuration() -> None:
    if not (
        settings.x_api_client_id
        and settings.x_api_redirect_uri
        and settings.x_api_token_encryption_key
    ):
        raise XOAuthError(
            "X account verification is not configured yet. No quiz reward "
            "can be claimed until the X integration is ready."
        )

    redirect = urlsplit(settings.x_api_redirect_uri)
    if redirect.scheme != "https" or not redirect.netloc:
        raise XOAuthError("X OAuth must use a public HTTPS callback URL.")

    try:
        Fernet(settings.x_api_token_encryption_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise XOAuthError(
            "The X token-encryption key is invalid. Contact the bot administrator."
        ) from exc


def _fernet() -> Fernet:
    _validate_configuration()
    return Fernet(settings.x_api_token_encryption_key.encode("ascii"))


def _encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def _decrypt_token(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError) as exc:
        raise XOAuthError(
            "The stored X authorization could not be decrypted. "
            "Ask the administrator to check the encryption key."
        ) from exc


def _basic_auth() -> aiohttp.BasicAuth | None:
    if not settings.x_api_client_secret:
        return None
    return aiohttp.BasicAuth(
        settings.x_api_client_id,
        settings.x_api_client_secret,
    )


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


async def create_x_authorization_url(telegram_id: int) -> str:
    _validate_configuration()
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    now = datetime.now(timezone.utc)

    async with SessionLocal() as session:
        async with session.begin():
            if await session.get(User, telegram_id) is None:
                raise XOAuthError("Send /start in the bot before connecting X.")
            await session.execute(
                delete(XOAuthState).where(
                    (XOAuthState.telegram_id == telegram_id)
                    | (XOAuthState.expires_at <= now)
                )
            )
            session.add(
                XOAuthState(
                    state=state,
                    telegram_id=telegram_id,
                    code_verifier=verifier,
                    expires_at=now + X_OAUTH_STATE_LIFETIME,
                )
            )

    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.x_api_client_id,
            "redirect_uri": settings.x_api_redirect_uri,
            "scope": " ".join(sorted(X_REQUIRED_SCOPES)),
            "state": state,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    return f"{X_AUTHORIZE_URL}?{query}"


async def _consume_oauth_state(state: str) -> tuple[int, str]:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        async with session.begin():
            stored = await session.scalar(
                select(XOAuthState)
                .where(XOAuthState.state == state)
                .with_for_update()
            )
            if stored is None:
                raise XOAuthError(
                    "This X authorization link is invalid or has already been used. "
                    "Start the connection again in the bot."
                )

            expires_at = stored.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now:
                await session.delete(stored)
                raise XOAuthError(
                    "This X authorization link expired. Start the connection "
                    "again in the bot."
                )

            result = (stored.telegram_id, stored.code_verifier)
            await session.delete(stored)
            return result


async def _response_json(response: aiohttp.ClientResponse) -> dict:
    try:
        payload = await response.json(content_type=None)
    except (aiohttp.ContentTypeError, ValueError) as exc:
        logging.warning("X API returned a non-JSON response (HTTP %s)", response.status)
        raise XOAuthError(
            "X could not verify this request right now. Please try again later."
        ) from exc

    if response.status >= 400 or not isinstance(payload, dict):
        logging.warning("X API request failed with HTTP %s", response.status)
        raise XOAuthError(
            "X could not verify this request right now. Please try again later."
        )

    if payload.get("errors"):
        logging.warning("X API returned an error payload")
        raise XOAuthError(
            "X could not verify this request right now. Please try again later."
        )
    return payload


async def _request_token(data: dict[str, str]) -> dict:
    _validate_configuration()
    auth = _basic_auth()
    if auth is None:
        data["client_id"] = settings.x_api_client_id

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.post(
                X_TOKEN_URL,
                data=data,
                auth=auth,
                headers={"Accept": "application/json"},
            ) as response:
                result = await _response_json(response)
    except XOAuthError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logging.warning("X OAuth token request failed: %s", type(exc).__name__)
        raise XOAuthError(
            "X authorization is temporarily unavailable. Please try again later."
        ) from exc

    if not isinstance(result.get("access_token"), str):
        raise XOAuthError("X did not return a usable authorization token.")
    return result


async def _x_get(
    client: aiohttp.ClientSession,
    path: str,
    access_token: str,
    params: dict[str, str | int] | None = None,
) -> dict:
    try:
        async with client.get(
            f"{X_API_BASE_URL}/{path.lstrip('/')}",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        ) as response:
            return await _response_json(response)
    except XOAuthError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logging.warning("X API request failed: %s", type(exc).__name__)
        raise XOAuthError(
            "X could not verify this request right now. Please try again later."
        ) from exc


async def complete_x_authorization(code: str, state: str) -> tuple[int, str]:
    _validate_configuration()
    if not code or not state or len(state) > 64:
        raise XOAuthError("X did not return a valid authorization response.")

    telegram_id, verifier = await _consume_oauth_state(state)
    tokens = await _request_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.x_api_redirect_uri,
            "code_verifier": verifier,
        }
    )

    scopes = set(str(tokens.get("scope", "")).split())
    if not X_REQUIRED_SCOPES.issubset(scopes):
        raise XOAuthError(
            "The X account did not grant all required read permissions. "
            "Reconnect and approve the requested permissions."
        )
    refresh_token = tokens.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise XOAuthError(
            "X did not grant a refresh token. Enable offline access in the "
            "X app settings, then connect again."
        )

    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        profile = await _x_get(
            client,
            "users/me",
            tokens["access_token"],
            params={"user.fields": "id,username"},
        )

    x_user = profile.get("data")
    if (
        not isinstance(x_user, dict)
        or not isinstance(x_user.get("id"), str)
        or not isinstance(x_user.get("username"), str)
    ):
        raise XOAuthError("X did not return a valid account profile.")

    expires_in = tokens.get("expires_in")
    if not isinstance(expires_in, int) or expires_in <= 0:
        raise XOAuthError("X returned an invalid authorization expiry.")
    now = datetime.now(timezone.utc)

    try:
        async with SessionLocal() as session:
            async with session.begin():
                linked_owner = await session.scalar(
                    select(XAccountLink)
                    .where(XAccountLink.x_user_id == x_user["id"])
                    .with_for_update()
                )
                if (
                    linked_owner is not None
                    and linked_owner.telegram_id != telegram_id
                ):
                    raise XOAuthError(
                        "That X account is already connected to another player."
                    )

                link = await session.get(
                    XAccountLink,
                    telegram_id,
                    with_for_update=True,
                )
                if link is not None and link.x_user_id != x_user["id"]:
                    await session.delete(link)
                    await session.flush()
                    link = None

                if link is None:
                    link = XAccountLink(telegram_id=telegram_id)
                    session.add(link)

                link.x_user_id = x_user["id"]
                link.x_username = x_user["username"]
                link.encrypted_access_token = _encrypt_token(
                    tokens["access_token"]
                )
                link.encrypted_refresh_token = _encrypt_token(refresh_token)
                link.expires_at = now + timedelta(seconds=expires_in)
                link.updated_at = now
    except IntegrityError as exc:
        raise XOAuthError(
            "That X account is already connected to another player."
        ) from exc

    return telegram_id, x_user["username"]


async def get_linked_x_username(telegram_id: int) -> str | None:
    async with SessionLocal() as session:
        link = await session.get(XAccountLink, telegram_id)
        return link.x_username if link is not None else None


async def unlink_x_account(telegram_id: int) -> bool:
    async with SessionLocal() as session:
        async with session.begin():
            link = await session.get(
                XAccountLink,
                telegram_id,
                with_for_update=True,
            )
            if link is None:
                return False
            await session.delete(link)
            await session.execute(
                delete(XOAuthState).where(
                    XOAuthState.telegram_id == telegram_id
                )
            )
            return True


async def discard_x_oauth_state(state: str) -> None:
    if not state:
        return
    async with SessionLocal() as session:
        async with session.begin():
            await session.execute(
                delete(XOAuthState).where(XOAuthState.state == state)
            )


async def _get_current_access_token(telegram_id: int) -> tuple[str, str, str]:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        async with session.begin():
            link = await session.scalar(
                select(XAccountLink)
                .where(XAccountLink.telegram_id == telegram_id)
                .with_for_update()
            )
            if link is None:
                raise XOAuthError(
                    "Connect your X account with /start connectx before claiming."
                )

            expires_at = link.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at > now + X_TOKEN_REFRESH_MARGIN:
                return (
                    _decrypt_token(link.encrypted_access_token),
                    link.x_user_id,
                    link.x_username,
                )

            refresh_token = _decrypt_token(link.encrypted_refresh_token)
            tokens = await _request_token(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                }
            )
            new_refresh_token = tokens.get("refresh_token", refresh_token)
            expires_in = tokens.get("expires_in")
            if (
                not isinstance(new_refresh_token, str)
                or not new_refresh_token
                or not isinstance(expires_in, int)
                or expires_in <= 0
            ):
                raise XOAuthError("X returned invalid refreshed credentials.")

            link.encrypted_access_token = _encrypt_token(
                tokens["access_token"]
            )
            link.encrypted_refresh_token = _encrypt_token(new_refresh_token)
            link.expires_at = now + timedelta(seconds=expires_in)
            link.updated_at = now
            return (
                tokens["access_token"],
                link.x_user_id,
                link.x_username,
            )


async def _contains_id(
    client: aiohttp.ClientSession,
    path: str,
    access_token: str,
    target_id: str,
    *,
    page_size: int,
    row_id: str,
) -> bool:
    params: dict[str, str | int] = {"max_results": page_size}
    for _ in range(X_LOOKUP_MAX_PAGES):
        result = await _x_get(client, path, access_token, params)
        rows = result.get("data") or []
        if any(
            isinstance(row, dict) and row.get(row_id) == target_id
            for row in rows
        ):
            return True

        metadata = result.get("meta")
        next_token = (
            metadata.get("next_token")
            if isinstance(metadata, dict)
            else None
        )
        if not next_token:
            return False
        params["pagination_token"] = next_token

    raise XOAuthError(
        "X has more activity pages than can be checked safely. "
        "Try again after confirming your account's recent activity."
    )


async def verify_campaign_actions(
    campaign_id: int,
    telegram_id: int,
) -> dict[str, bool]:
    _validate_configuration()
    access_token, x_user_id, x_username = await _get_current_access_token(
        telegram_id
    )

    async with SessionLocal() as session:
        campaign = await session.get(XRaidCampaign, campaign_id)
        if campaign is None or not campaign.active:
            raise XOAuthError("That X quiz is no longer active.")
        post_id = campaign.post_id
        cached_author_id = campaign.target_user_id

    try:
        async with asyncio.timeout(90):
            return await _verify_campaign_actions(
                campaign_id,
                post_id,
                cached_author_id,
                access_token,
                x_user_id,
                x_username,
            )
    except asyncio.TimeoutError as exc:
        raise XOAuthError(
            "X verification took too long. No points were awarded; try again."
        ) from exc


async def _verify_campaign_actions(
    campaign_id: int,
    post_id: str,
    cached_author_id: str,
    access_token: str,
    x_user_id: str,
    x_username: str,
) -> dict[str, bool]:
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        profile = await _x_get(
            client,
            "users/me",
            access_token,
            params={"user.fields": "id,username"},
        )
        current_user = profile.get("data", {})
        if current_user.get("id") != x_user_id:
            raise XOAuthError(
                "The connected X account changed. Reconnect it before claiming."
            )
        x_username = current_user.get("username", x_username)

        if cached_author_id:
            author_id = cached_author_id
        else:
            post = await _x_get(
                client,
                f"tweets/{post_id}",
                access_token,
                params={
                    "expansions": "author_id",
                    "tweet.fields": "author_id",
                    "user.fields": "id,username",
                },
            )
            tweet_data = post.get("data")
            author_id = (
                tweet_data.get("author_id")
                if isinstance(tweet_data, dict)
                else None
            )
            if not isinstance(author_id, str):
                raise XOAuthError(
                    "X could not identify the author of the campaign post."
                )

            async with SessionLocal() as session:
                async with session.begin():
                    campaign = await session.scalar(
                        select(XRaidCampaign)
                        .where(XRaidCampaign.id == campaign_id)
                        .with_for_update()
                    )
                    if campaign is None or not campaign.active:
                        raise XOAuthError("That X quiz is no longer active.")
                    campaign.target_user_id = author_id
                    authors = post.get("includes", {}).get("users") or []
                    if authors:
                        campaign.target_username = authors[0].get(
                            "username", ""
                        )

        liked = await _contains_id(
            client,
            f"users/{x_user_id}/liked_tweets",
            access_token,
            post_id,
            page_size=100,
            row_id="id",
        )
        reposted = await _contains_id(
            client,
            f"tweets/{post_id}/retweeted_by",
            access_token,
            x_user_id,
            page_size=100,
            row_id="id",
        )
        followed = await _contains_id(
            client,
            f"users/{x_user_id}/following",
            access_token,
            author_id,
            page_size=1000,
            row_id="id",
        )
        reply_query = f"conversation_id:{post_id} from:{x_username}"
        replies = await _x_get(
            client,
            "tweets/search/recent",
            access_token,
            params={
                "query": reply_query,
                "max_results": 100,
                "tweet.fields": "author_id,referenced_tweets",
            },
        )
        reply_data = replies.get("data") or []
        replied = any(
            isinstance(tweet, dict)
            and tweet.get("author_id") == x_user_id
            and any(
                isinstance(reference, dict)
                and reference.get("type") == "replied_to"
                and reference.get("id") == post_id
                for reference in tweet.get("referenced_tweets", [])
            )
            for tweet in reply_data
        )

    return {
        "like": liked,
        "repost": reposted,
        "reply": replied,
        "follow": followed,
    }


async def x_oauth_callback(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    error = request.query.get("error")
    state = request.query.get("state", "")
    if error:
        await discard_x_oauth_state(state)
        return web.Response(
            text=(
                "X account connection was cancelled. Return to the bot and "
                "try again if you still want to connect."
            ),
            content_type="text/plain",
            status=400,
        )

    try:
        telegram_id, username = await complete_x_authorization(
            request.query.get("code", ""),
            state,
        )
    except XOAuthError as exc:
        return web.Response(
            text=str(exc),
            content_type="text/plain",
            status=400,
        )

    try:
        await bot.send_message(
            telegram_id,
            "✅ X account connected: "
            f"<b>@{escape(username)}</b>\n\n"
            "You can now complete the Like, Repost, Reply, and Follow "
            "requirements for active X quiz campaigns. Use /missions to check "
            "your progress.",
            parse_mode="HTML",
        )
    except TelegramAPIError:
        logging.exception(
            "Could not notify Telegram user %s after X account linking",
            telegram_id,
        )

    return web.Response(
        text=(
            "X account connected successfully. Return to Telegram and open "
            "Missions to continue."
        ),
        content_type="text/plain",
    )


def create_x_oauth_web_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/x/oauth/callback", x_oauth_callback)
    return app
