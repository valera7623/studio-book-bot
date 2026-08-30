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


def _add_column(sync_conn, table: str, cols: set[str], name: str, ddl: str) -> None:
    if name not in cols:
        sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def _add_missing_columns(sync_conn) -> None:
    if _table_exists(sync_conn, "bookings"):
        cols = _columns(sync_conn, "bookings")
        _add_column(sync_conn, "bookings", cols, "reminder_sent_at", "reminder_sent_at DATETIME")
        _add_column(sync_conn, "bookings", cols, "reminder_2h_sent_at", "reminder_2h_sent_at DATETIME")
        _add_column(sync_conn, "bookings", cols, "quoted_price_rub", "quoted_price_rub INTEGER DEFAULT 0")
        _add_column(sync_conn, "bookings", cols, "prepay_amount_rub", "prepay_amount_rub INTEGER DEFAULT 0")
    if _table_exists(sync_conn, "studios"):
        cols = _columns(sync_conn, "studios")
        _add_column(sync_conn, "studios", cols, "subscription_until", "subscription_until DATETIME")
        _add_column(sync_conn, "studios", cols, "hold_ttl_minutes", "hold_ttl_minutes INTEGER DEFAULT 20")
        _add_column(sync_conn, "studios", cols, "prepay_percent", "prepay_percent INTEGER DEFAULT 100")
        _add_column(sync_conn, "studios", cols, "cancel_free_hours", "cancel_free_hours INTEGER DEFAULT 72")
        _add_column(
            sync_conn,
            "studios",
            cols,
            "late_cancel_retain_percent",
            "late_cancel_retain_percent INTEGER DEFAULT 50",
        )
    if _table_exists(sync_conn, "resources"):
        cols = _columns(sync_conn, "resources")
        _add_column(sync_conn, "resources", cols, "slot_step_min", "slot_step_min INTEGER DEFAULT 60")
        _add_column(sync_conn, "resources", cols, "min_duration_min", "min_duration_min INTEGER DEFAULT 60")
        _add_column(sync_conn, "resources", cols, "buffer_min", "buffer_min INTEGER DEFAULT 5")
        _add_column(
            sync_conn,
            "resources",
            cols,
            "hour_markup_percent",
            "hour_markup_percent INTEGER DEFAULT 50",
        )
        _add_column(sync_conn, "resources", cols, "weekend_price_rub", "weekend_price_rub INTEGER DEFAULT 0")
        _add_column(sync_conn, "resources", cols, "night_price_rub", "night_price_rub INTEGER DEFAULT 0")
        _add_column(sync_conn, "resources", cols, "night_start", "night_start TIME")
    if _table_exists(sync_conn, "payments"):
        cols = _columns(sync_conn, "payments")
        _add_column(sync_conn, "payments", cols, "refunded_at", "refunded_at DATETIME")
        _add_column(sync_conn, "payments", cols, "refund_amount_rub", "refund_amount_rub INTEGER DEFAULT 0")


def _rebuild_booking_active_index(sync_conn) -> None:
    if not _table_exists(sync_conn, "bookings"):
        return
    sync_conn.execute(text("DROP INDEX IF EXISTS uq_booking_resource_start_active"))
    sync_conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_resource_start_active "
            "ON bookings (resource_id, starts_at) "
            "WHERE status IN ('hold', 'paid', 'blocked')"
        )
    )


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
        _rebuild_booking_active_index(sync_conn)


async def init_database(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(_register_models_and_create_all)
