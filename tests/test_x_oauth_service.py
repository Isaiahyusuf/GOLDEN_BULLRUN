import asyncio
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet

from app.services import x_oauth_service


def test_pkce_challenge_and_token_encryption(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(x_oauth_service.settings, "x_api_client_id", "client")
    monkeypatch.setattr(
        x_oauth_service.settings,
        "x_api_redirect_uri",
        "https://bot.example/x/oauth/callback",
    )
    monkeypatch.setattr(
        x_oauth_service.settings,
        "x_api_token_encryption_key",
        key,
    )

    encrypted = x_oauth_service._encrypt_token("private-access-token")

    assert x_oauth_service._pkce_challenge("verifier") == (
        "iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ"
    )
    assert encrypted != "private-access-token"
    assert x_oauth_service._decrypt_token(encrypted) == "private-access-token"


def test_authorization_url_saves_state_and_requests_read_only_scopes(monkeypatch):
    from app.models.x_account import XOAuthState

    class FakeSession:
        def __init__(self):
            self.added = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            assert len(args) == 3
            return None

        def begin(self):
            return self

        async def get(self, model, key):
            assert model.__name__ == "User"
            assert key == 1001
            return object()

        async def execute(self, query):
            assert query is not None
            return None

        def add(self, item):
            self.added.append(item)

    session = FakeSession()
    monkeypatch.setattr(
        x_oauth_service.settings,
        "x_api_client_id",
        "client-id",
    )
    monkeypatch.setattr(
        x_oauth_service.settings,
        "x_api_redirect_uri",
        "https://bot.example/x/oauth/callback",
    )
    monkeypatch.setattr(
        x_oauth_service.settings,
        "x_api_token_encryption_key",
        Fernet.generate_key().decode("ascii"),
    )
    monkeypatch.setattr(
        x_oauth_service,
        "SessionLocal",
        lambda: session,
    )

    authorization_url = asyncio.run(
        x_oauth_service.create_x_authorization_url(1001)
    )
    query = parse_qs(urlsplit(authorization_url).query)
    saved_state = session.added[0]

    assert isinstance(saved_state, XOAuthState)
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == [
        "https://bot.example/x/oauth/callback"
    ]
    assert set(query["scope"][0].split()) == x_oauth_service.X_REQUIRED_SCOPES
    assert query["state"] == [saved_state.state]
    assert query["code_challenge"] == [
        x_oauth_service._pkce_challenge(saved_state.code_verifier)
    ]
    assert query["code_challenge_method"] == ["S256"]


def test_verifies_all_four_x_actions_for_linked_user(monkeypatch):
    campaign = SimpleNamespace(
        id=7,
        post_id="12345",
        target_user_id="author-id",
        active=True,
    )

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            assert len(args) == 3
            return None

        async def get(self, model, key):
            assert model.__name__ == "XRaidCampaign"
            assert key == 7
            return campaign

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            assert len(args) == 3
            return None

    async def fake_x_get(client, path, access_token, params=None):
        assert client is not None
        assert access_token == "access-token"
        if path == "users/me":
            return {"data": {"id": "player-id", "username": "player"}}
        if path == "users/player-id/liked_tweets":
            return {"data": [{"id": "12345"}]}
        if path == "tweets/12345/retweeted_by":
            return {"data": [{"id": "player-id"}]}
        if path == "users/player-id/following":
            return {"data": [{"id": "author-id"}]}
        if path == "tweets/search/recent":
            assert params["query"] == "conversation_id:12345 from:player"
            return {
                "data": [
                    {
                        "author_id": "player-id",
                        "referenced_tweets": [
                            {"type": "replied_to", "id": "12345"}
                        ],
                    }
                ]
            }
        raise AssertionError(f"Unexpected X endpoint: {path}")

    async def fake_get_access_token(telegram_id):
        assert telegram_id == 1001
        return "access-token", "player-id", "player"

    def fake_client_session(timeout):
        assert isinstance(timeout, x_oauth_service.aiohttp.ClientTimeout)
        return FakeClient()

    monkeypatch.setattr(
        x_oauth_service.settings,
        "x_api_client_id",
        "client",
    )
    monkeypatch.setattr(
        x_oauth_service.settings,
        "x_api_redirect_uri",
        "https://bot.example/x/oauth/callback",
    )
    monkeypatch.setattr(
        x_oauth_service.settings,
        "x_api_token_encryption_key",
        Fernet.generate_key().decode("ascii"),
    )
    monkeypatch.setattr(
        x_oauth_service,
        "_get_current_access_token",
        fake_get_access_token,
    )
    monkeypatch.setattr(
        x_oauth_service,
        "SessionLocal",
        FakeSession,
    )
    monkeypatch.setattr(
        x_oauth_service.aiohttp,
        "ClientSession",
        fake_client_session,
    )
    monkeypatch.setattr(x_oauth_service, "_x_get", fake_x_get)

    result = asyncio.run(
        x_oauth_service.verify_campaign_actions(7, 1001)
    )

    assert result == {
        "like": True,
        "repost": True,
        "reply": True,
        "follow": True,
    }


def test_paginated_action_lookup_finds_later_page(monkeypatch):
    responses = iter(
        [
            {"data": [], "meta": {"next_token": "next"}},
            {"data": [{"id": "target"}], "meta": {}},
        ]
    )
    seen_params = []

    async def fake_x_get(client, path, access_token, params=None):
        assert client is not None
        assert path == "users/1/following"
        assert access_token == "token"
        seen_params.append(dict(params))
        return next(responses)

    monkeypatch.setattr(x_oauth_service, "_x_get", fake_x_get)

    result = asyncio.run(
        x_oauth_service._contains_id(
            object(),
            "users/1/following",
            "token",
            "target",
            page_size=100,
            row_id="id",
        )
    )

    assert result is True
    assert seen_params == [
        {"max_results": 100},
        {"max_results": 100, "pagination_token": "next"},
    ]
