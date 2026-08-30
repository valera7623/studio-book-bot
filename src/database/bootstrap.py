"""Импорт моделей и создание таблиц."""


def _register_models_and_create_all(sync_conn):
    from src.database.base import Base
    from src.database.models import booking  # noqa: F401
    from src.database.models import consent  # noqa: F401
    from src.database.models import payment  # noqa: F401
    from src.database.models import studio  # noqa: F401
    from src.database.models import user  # noqa: F401

    Base.metadata.create_all(sync_conn)


async def init_database(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(_register_models_and_create_all)
