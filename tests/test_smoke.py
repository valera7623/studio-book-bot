from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.bot.loader import get_dispatcher, load_routers, setup_middlewares
from src.database import get_session_maker
from src.database.models.user import User
from src.handlers import user_commands
from src.handlers.user_commands import cmd_start


def test_start_handler_registered():
    assert user_commands.cmd_start is not None


async def test_start_answers_welcome(session):
    user = User(telegram_id=1, first_name="Ира", language_code="ru")
    session.add(user)
    await session.commit()
    await session.refresh(user)

    message = AsyncMock()
    command = MagicMock()
    command.args = None
    state = AsyncMock()

    await cmd_start(message, command, user, session, state)

    state.clear.assert_awaited()
    message.answer.assert_awaited()
    text = message.answer.await_args.args[0]
    assert "фотостудию" in text
    assert "парол" not in text.lower()


async def test_dispatcher_loads(engine):
    dp = get_dispatcher()
    setup_middlewares(dp, get_session_maker(engine))
    load_routers(dp)
    assert dp.sub_routers


async def test_tables_created(engine):
    from sqlalchemy import inspect

    def _tables(sync_conn):
        return set(inspect(sync_conn).get_table_names())

    async with engine.connect() as conn:
        names = await conn.run_sync(_tables)

    assert {"users", "studios", "resources", "bookings", "payments", "consents"} <= names
