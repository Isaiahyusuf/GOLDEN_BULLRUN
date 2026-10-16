from app.database.connection import normalize_database_url


def test_normalizes_railway_postgresql_url():
    result = normalize_database_url(
        "postgresql://user:pass@host.example:5432/game?sslmode=require"
    )
    assert result == (
        "postgresql+asyncpg://user:pass@host.example:5432/game?sslmode=require"
    )


def test_preserves_asyncpg_url():
    result = normalize_database_url(
        "postgresql+asyncpg://user:pass@host.example:5432/game?sslmode=require"
    )
    assert result == (
        "postgresql+asyncpg://user:pass@host.example:5432/game?sslmode=require"
    )


def test_normalizes_postgres_alias():
    result = normalize_database_url(
        "postgres://user:pass@host.example:5432/game?sslmode=require"
    )
    assert result == (
        "postgresql+asyncpg://user:pass@host.example:5432/game?sslmode=require"
    )


def test_rewrites_psycopg_driver_to_asyncpg():
    result = normalize_database_url(
        "postgresql+psycopg://user:pass@host.example:5432/game?sslmode=require"
    )
    assert result == (
        "postgresql+asyncpg://user:pass@host.example:5432/game?sslmode=require"
    )


def test_uses_default_when_database_url_is_blank():
    result = normalize_database_url("   ")
    assert result == "postgresql+asyncpg://localhost/trumpty_royale"


def test_uses_default_when_database_url_is_missing():
    result = normalize_database_url(None)
    assert result == "postgresql+asyncpg://localhost/trumpty_royale"


def test_keeps_local_default_driver_compatible():
    result = normalize_database_url(
        "postgresql+asyncpg://localhost/trumpty_royale"
    )
    assert result == "postgresql+asyncpg://localhost/trumpty_royale"
