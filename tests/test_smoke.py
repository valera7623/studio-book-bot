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


def test_landing_lists_service_prices():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "landing" / "index.html").read_text(encoding="utf-8")
    assert "Стоимость услуг" in html
    assert "{{TARIFF_STARTER_RUB}}" in html
    assert "2&nbsp;000" in html
    assert "id=\"prices\"" in html


async def test_landing_http_substitutes_tariffs(engine):
    from aiohttp.test_utils import TestClient, TestServer

    from src.web.app import create_web_app

    app = create_web_app(bot=None, session_maker=get_session_maker(engine))
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/")
        assert resp.status == 200
        text = await resp.text()
        assert "490" in text
        assert "990" in text
        assert "2\xa0000" in text or "2&nbsp;000" in text
        assert "Стоимость услуг" in text
        assert "220910861433" in text
        assert "https://studiobook.com.ru/" in text
        robots = await client.get("/robots.txt")
        assert robots.status == 200
        offer = await client.get("/offer")
        assert offer.status == 200
        offer_text = await offer.text()
        assert "Публичная оферта" in offer_text
        assert "220910861433" in offer_text
        assert "studiobook.com.ru" in offer_text
        pdf = await client.get("/offer.pdf")
        assert pdf.status == 200
        assert "pdf" in (pdf.headers.get("Content-Type") or "").lower()


async def test_admin_support_text_shows_payform_and_counts(session):
    from src.handlers.admin_commands import platform_support_text

    text = await platform_support_text(session)
    assert "Касса Prodamus" in text
    assert "Webhook:" in text
    assert "Платежи:" in text
    assert "Брони:" in text


def test_go_live_runbook_has_webhook():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    go_live = (root / "docs" / "go_live.md").read_text(encoding="utf-8")
    assert "https://studiobook.com.ru/prodamus/webhook" in go_live
    owner = (root / "src" / "handlers" / "owner.py").read_text(encoding="utf-8")
    assert "Пилот за вечер" in owner
    outreach = (root / "docs" / "outreach.md").read_text(encoding="utf-8")
    assert "3–5%" in outreach or "3-5%" in outreach
    pain = (root / "docs" / "pain_check.md").read_text(encoding="utf-8")
    assert "первая оплата слота" in pain
