"""Счётчики клиентов студии и подписчиков платформы. Super Admin не нужен."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.booking import (
    STATUS_BLOCKED,
    STATUS_CANCELLED,
    STATUS_HOLD,
    STATUS_PAID,
    Booking,
)
from src.database.models.studio import TARIFF_FREE, TARIFF_PLUS, TARIFF_STARTER, Studio
from src.database.models.user import User
from src.services.tariffs import tariff_label

CLIENT_STATUSES = (STATUS_HOLD, STATUS_PAID, STATUS_CANCELLED)


async def _distinct_clients(
    session: AsyncSession,
    studio_id: int,
    statuses: tuple[str, ...],
) -> int:
    value = await session.scalar(
        select(func.count(func.distinct(Booking.client_telegram_id))).where(
            Booking.studio_id == studio_id,
            Booking.status.in_(statuses),
        )
    )
    return int(value or 0)


async def studio_audience_counts(session: AsyncSession, studio_id: int) -> dict[str, int]:
    """Клиенты и брони одной студии. Закрытые интервалы владельца не считаются."""
    paid_clients = await _distinct_clients(session, studio_id, (STATUS_PAID,))
    started_clients = await _distinct_clients(session, studio_id, CLIENT_STATUSES)
    rows = (
        await session.execute(
            select(Booking.status, func.count())
            .where(
                Booking.studio_id == studio_id,
                Booking.status != STATUS_BLOCKED,
            )
            .group_by(Booking.status)
        )
    ).all()
    by_status = {str(status): int(n) for status, n in rows}
    return {
        "paid_clients": paid_clients,
        "started_clients": started_clients,
        "paid_bookings": by_status.get(STATUS_PAID, 0),
        "hold_bookings": by_status.get(STATUS_HOLD, 0),
        "cancelled_bookings": by_status.get(STATUS_CANCELLED, 0),
    }


async def platform_subscriber_counts(session: AsyncSession) -> dict[str, int]:
    users_n = await session.scalar(select(func.count()).select_from(User)) or 0
    studios_n = await session.scalar(select(func.count()).select_from(Studio)) or 0
    rows = (
        await session.execute(select(Studio.tariff, func.count()).group_by(Studio.tariff))
    ).all()
    by_tariff = {str(tariff): int(n) for tariff, n in rows}
    starter = by_tariff.get(TARIFF_STARTER, 0)
    plus = by_tariff.get(TARIFF_PLUS, 0)
    free = by_tariff.get(TARIFF_FREE, 0)
    other = studios_n - starter - plus - free
    if other > 0:
        free += other
    return {
        "users": int(users_n),
        "studios": int(studios_n),
        "free": free,
        "starter": starter,
        "plus": plus,
        "paid": starter + plus,
    }


def format_booking_counts(counts: dict[str, int]) -> str:
    return (
        f"оплачено {counts['paid_bookings']}, "
        f"ожидают {counts['hold_bookings']}, "
        f"отменено {counts['cancelled_bookings']}"
    )


def format_cabinet_audience(counts: dict[str, int]) -> str:
    clients = counts["paid_clients"]
    if clients:
        clients_line = f"Клиенты: {clients} с оплатой"
    else:
        clients_line = "Клиенты: пока никого с оплатой"
    return f"{clients_line}\nБрони: {format_booking_counts(counts)}"


def format_studio_stats_text(studio: Studio, counts: dict[str, int]) -> str:
    from html import escape

    name = escape(studio.name)
    clients = counts["paid_clients"]
    started = counts["started_clients"]
    if clients:
        clients_line = f"👥 Клиенты: <b>{clients}</b> уникальных с хотя бы одной оплатой"
        if started > clients:
            clients_line += f"\n   заходили в запись без оплаты: {started - clients}"
    else:
        clients_line = (
            "👥 Клиенты: пока никого с оплатой.\n"
            "Ссылка записи — кнопка «Ссылка записи» в /studio."
        )
    return (
        f"📊 <b>Сводка студии «{name}»</b>\n"
        f"Тариф: {tariff_label(studio.tariff)}\n\n"
        f"{clients_line}\n\n"
        f"📋 Брони: {format_booking_counts(counts)}\n\n"
        "Это счётчик <b>вашей</b> студии — Super Admin не нужен.\n"
        "Сводка всей платформы: /admin, если ваш Telegram ID указан в ADMINS."
    )


def format_no_studio_stats_text() -> str:
    return (
        "Студии ещё нет. Создайте её командой /studio — "
        "там и в /stats будет число клиентов.\n\n"
        "Super Admin не нужен: это кабинет владельца, не платформы."
    )


def format_platform_subscribers(counts: dict[str, int]) -> str:
    return (
        f"Подписчики тарифа: платных <b>{counts['paid']}</b> "
        f"(старт {counts['starter']}, плюс {counts['plus']}), "
        f"бесплатно {counts['free']}"
    )
