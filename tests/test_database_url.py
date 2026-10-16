from app.database.connection import normalize_database_url


def test_normalizes_railway_postgresql_url():
    result = normalize_database_url(
        "postgresql://bot:secret@host.example:5432/game"
    )
    assert result == (
        "postgresql+asyncpg://bot:secret@host.example:5432/game"
    )


def test_preserves_asyncpg_url():
    result = normalize_database_url(
        "postgresql+asyncpg://bot:secret@host.example:5432/game"
    )
    assert result == (
        "postgresql+asyncpg://bot:secret@host.example:5432/game"
    )


def test_normalizes_postgres_alias():
    result = normalize_database_url(
        "postgres://bot:secret@host.example:5432/game"
    )
    assert result == (
        "postgresql+asyncpg://bot:secret@host.example:5432/game"
    )


def test_keeps_local_default_driver_compatible():
    result = normalize_database_url(
        "postgresql+asyncpg://localhost/trumpty_royale"
    )
    assert result == "postgresql+asyncpg://localhost/trumpty_royale"
