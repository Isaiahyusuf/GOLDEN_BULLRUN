from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from app.database import connection


@pytest.mark.asyncio
async def test_database_readiness_retries_before_initializing_schema(monkeypatch):
    attempts = 0

    class Connection:
        async def __aenter__(self):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise OperationalError(
                    "connect",
                    {},
                    OSError("connection refused"),
                )
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def execute(self, statement):
            return None

    class Engine:
        def connect(self):
            return Connection()

        def begin(self):
            pytest.fail("Schema initialization should not run in this test")

    sleep = AsyncMock()
    monkeypatch.setattr(connection, "engine", Engine())
    monkeypatch.setattr(connection.asyncio, "sleep", sleep)

    async def initialize_schema():
        return None

    monkeypatch.setattr(connection, "_initialize_schema", initialize_schema)
    await connection.init_db()

    assert attempts == 3
    assert [call.args[0] for call in sleep.await_args_list] == [1, 2]


@pytest.mark.asyncio
async def test_database_readiness_fails_after_bounded_retries(monkeypatch):
    attempts = 0

    class Connection:
        async def __aenter__(self):
            nonlocal attempts
            attempts += 1
            raise OperationalError(
                "connect",
                {},
                OSError("connection refused"),
            )

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class Engine:
        def connect(self):
            return Connection()

    sleep = AsyncMock()
    monkeypatch.setattr(connection, "engine", Engine())
    monkeypatch.setattr(connection.asyncio, "sleep", sleep)

    with pytest.raises(
        connection.DatabaseConnectionError,
        match="Could not connect to PostgreSQL after 5 attempts",
    ):
        await connection.init_db()

    assert attempts == connection.DATABASE_CONNECT_ATTEMPTS
    assert sleep.await_count == connection.DATABASE_CONNECT_ATTEMPTS - 1


@pytest.mark.asyncio
async def test_engine_is_disposed_when_database_startup_fails(monkeypatch):
    from app import main

    engine = type("Engine", (), {"dispose": AsyncMock()})()
    monkeypatch.setattr(
        main,
        "init_db",
        AsyncMock(side_effect=connection.DatabaseConnectionError("offline")),
    )
    monkeypatch.setattr(main, "engine", engine)

    with pytest.raises(connection.DatabaseConnectionError, match="offline"):
        await main.main()

    engine.dispose.assert_awaited_once()
