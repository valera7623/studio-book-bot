from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine as sa_create_async_engine,
)

from src.config import settings


def create_async_engine(dsn: str | None = None):
    """Async engine. SQLite сейчас; DSN можно сменить на Postgres без смены моделей."""
    url = dsn or settings.sqlite_dsn
    eng = sa_create_async_engine(
        url,
        echo=False,
        future=True,
    )

    if url.startswith("sqlite"):

        @event.listens_for(eng.sync_engine, "connect")
        def _sqlite_pragma(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return eng


def get_session_maker(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
