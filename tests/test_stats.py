from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.database.models.booking import (
    STATUS_BLOCKED,
    STATUS_CANCELLED,
    STATUS_HOLD,
    STATUS_PAID,
    Booking,
)
from src.database.models.studio import TARIFF_FREE, TARIFF_PLUS, TARIFF_STARTER, Resource, Studio
from src.database.models.user import User
from src.handlers.owner import cmd_stats, show_cabinet
from src.services.stats import (
    format_cabinet_audience,
    format_no_studio_stats_text,
    format_platform_subscribers,
    format_studio_stats_text,
    platform_subscriber_counts,
    studio_audience_counts,
)


def _utc(*parts) -> datetime:
    return datetime(*parts, tzinfo=timezone.utc)


async def _seed_studio(session, *, telegram_id=1001, tariff=TARIFF_FREE) -> Studio:
    owner = User(
        telegram_id=telegram_id,
        username="owner",
        first_name="Анна",
        language_code="ru",
    )
    session.add(owner)
    await session.flush()
    studio = Studio(
        slug=f"studio-{telegram_id}",
        name="Светлая",
        owner_id=owner.id,
        owner_telegram_id=owner.telegram_id,
        timezone="Europe/Moscow",
        tariff=tariff,
    )
    session.add(studio)
    await session.flush()
    resource = Resource(
        studio_id=studio.id,
        name="Циклорама",
        timezone="Europe/Moscow",
        price_rub=1000,
    )
    session.add(resource)
    await session.flush()
    studio._resource = resource
    studio._owner = owner
    return studio


def _booking(studio: Studio, *, telegram_id: int, status: str, hour: int) -> Booking:
    start = _utc(2026, 9, 1, hour)
    return Booking(
        resource_id=studio._resource.id,
        studio_id=studio.id,
        client_telegram_id=telegram_id,
        client_name=f"Клиент {telegram_id}",
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        status=status,
        quoted_price_rub=1000,
        prepay_amount_rub=1000,
    )


async def test_unique_paid_clients_dedupes_same_telegram(session):
    studio = await _seed_studio(session)
    session.add_all(
        [
            _booking(studio, telegram_id=2001, status=STATUS_PAID, hour=10),
            _booking(studio, telegram_id=2001, status=STATUS_PAID, hour=12),
            _booking(studio, telegram_id=2002, status=STATUS_PAID, hour=14),
            _booking(studio, telegram_id=2003, status=STATUS_HOLD, hour=16),
            _booking(studio, telegram_id=2004, status=STATUS_CANCELLED, hour=18),
            _booking(studio, telegram_id=2005, status=STATUS_BLOCKED, hour=20),
        ]
    )
    await session.commit()

    counts = await studio_audience_counts(session, studio.id)
    assert counts["paid_clients"] == 2
    assert counts["started_clients"] == 4
    assert counts["paid_bookings"] == 3
    assert counts["hold_bookings"] == 1
    assert counts["cancelled_bookings"] == 1


async def test_empty_studio_audience_zero(session):
    studio = await _seed_studio(session)
    await session.commit()
    counts = await studio_audience_counts(session, studio.id)
    assert counts == {
        "paid_clients": 0,
        "started_clients": 0,
        "paid_bookings": 0,
        "hold_bookings": 0,
        "cancelled_bookings": 0,
    }
    text = format_cabinet_audience(counts)
    assert "пока никого с оплатой" in text
    stats = format_studio_stats_text(studio, counts)
    assert "Super Admin не нужен" in stats
    assert "Светлая" in stats


async def test_platform_subscribers_by_tariff(session):
    await _seed_studio(session, telegram_id=1, tariff=TARIFF_FREE)
    await _seed_studio(session, telegram_id=2, tariff=TARIFF_STARTER)
    await _seed_studio(session, telegram_id=3, tariff=TARIFF_PLUS)
    await session.commit()

    counts = await platform_subscriber_counts(session)
    assert counts["studios"] == 3
    assert counts["free"] == 1
    assert counts["starter"] == 1
    assert counts["plus"] == 1
    assert counts["paid"] == 2
    line = format_platform_subscribers(counts)
    assert "платных <b>2</b>" in line
    assert "старт 1" in line
    assert "плюс 1" in line


async def test_stats_command_without_studio(session):
    user = User(telegram_id=9, first_name="Гость", language_code="ru")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    message = AsyncMock()
    await cmd_stats(message, session, user)
    text = message.answer.await_args.args[0]
    assert text == format_no_studio_stats_text()
    assert "Super Admin не нужен" in text


async def test_stats_command_and_cabinet_show_paid_clients(session):
    studio = await _seed_studio(session, telegram_id=42)
    session.add(_booking(studio, telegram_id=77, status=STATUS_PAID, hour=11))
    await session.commit()

    message = AsyncMock()
    await cmd_stats(message, session, studio._owner)
    stats_text = message.answer.await_args.args[0]
    assert "уникальных" in stats_text
    assert "<b>1</b>" in stats_text

    cabinet = AsyncMock()
    await show_cabinet(cabinet, session, studio._owner)
    cab_text = cabinet.answer.await_args.args[0]
    assert "Клиенты: 1 с оплатой" in cab_text
    assert "Super Admin не нужен" in cab_text


async def test_help_lists_stats_without_super_admin():
    from src.handlers.user_commands import cmd_help

    user = SimpleNamespace(telegram_id=1)
    message = AsyncMock()
    await cmd_help(message, user)
    text = message.answer.await_args.args[0]
    assert "/stats" in text
    assert "Super Admin не нужен" in text


async def test_admin_text_includes_tariff_subscribers(session):
    from src.handlers.admin_commands import platform_support_text

    await _seed_studio(session, telegram_id=5, tariff=TARIFF_STARTER)
    await session.commit()
    text = await platform_support_text(session)
    assert "Подписчики тарифа" in text
    assert "платных <b>1</b>" in text
    assert "Super Admin в этом боте нет" in text
    assert "/stats" in text
