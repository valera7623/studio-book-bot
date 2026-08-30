from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from src.config import settings
from src.middlewares import (
    DatabaseMiddleware,
    LoggingMiddleware,
    ThrottlingMiddleware,
    UserMiddleware,
)


def get_dispatcher() -> Dispatcher:
    if settings.USE_REDIS:
        from aiogram.fsm.storage.redis import RedisStorage

        storage = RedisStorage.from_url(str(settings.REDIS_URL))
    else:
        storage = MemoryStorage()
    return Dispatcher(storage=storage)


def setup_middlewares(dp: Dispatcher, session_maker):
    dp.update.middleware(LoggingMiddleware())
    dp.update.middleware(
        ThrottlingMiddleware(
            rate_limit=settings.THROTTLE_RATE_LIMIT,
            ttl=settings.THROTTLE_TTL,
        )
    )
    dp.update.middleware(DatabaseMiddleware(session_maker))
    dp.update.middleware(UserMiddleware())


def load_routers(dp: Dispatcher):
    from src.handlers import admin_commands, booking, owner, profile, user_commands

    for router in (
        admin_commands.router,
        owner.router,
        booking.router,
        user_commands.router,
        profile.router,
    ):
        dp.include_router(router)
