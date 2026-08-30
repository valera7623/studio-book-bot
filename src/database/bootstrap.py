"""Импорт моделей, создание таблиц и лёгкие миграции SQLite."""

from sqlalchemy import text


def _table_exists(sync_conn, name: str) -> bool:
    row = sync_conn.execute(
        text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name LIMIT 1"
        ),
        {"name": name},
    ).fetchone()
    return bool(row)


def _columns(sync_conn, table: str) -> set[str]:
    return {r[1] for r in sync_conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def _add_missing_columns(sync_conn) -> None:
    if _table_exists(sync_conn, "bookings"):
        cols = _columns(sync_conn, "bookings")
        if "reminder_sent_at" not in cols:
            sync_conn.execute(text("ALTER TABLE bookings ADD COLUMN reminder_sent_at DATETIME"))
    if _table_exists(sync_conn, "studios"):
        cols = _columns(sync_conn, "studios")
        if "subscription_until" not in cols:
            sync_conn.execute(text("ALTER TABLE studios ADD COLUMN subscription_until DATETIME"))


def _register_models_and_create_all(sync_conn):
    from src.database.base import Base
    from src.database.models import booking  # noqa: F401
    from src.database.models import consent  # noqa: F401
    from src.database.models import payment  # noqa: F401
    from src.database.models import studio  # noqa: F401
    from src.database.models import user  # noqa: F401

    Base.metadata.create_all(sync_conn)
    if sync_conn.dialect.name == "sqlite":
        _add_missing_columns(sync_conn)


async def init_database(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(_register_models_and_create_all)
