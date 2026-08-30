from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.base import utcnow
from src.database.models.booking import STATUS_HOLD, STATUS_PAID, Booking
from src.database.models.studio import (
    TARIFF_FREE,
    TARIFF_PLUS,
    TARIFF_STARTER,
    Resource,
    Studio,
)


def resource_limit_for(tariff: str) -> int:
    if tariff == TARIFF_PLUS:
        return max(settings.PLUS_RESOURCE_LIMIT, settings.FREE_RESOURCE_LIMIT + 1)
    return settings.FREE_RESOURCE_LIMIT


def monthly_booking_limit(studio: Studio) -> int | None:
    if studio.tariff == TARIFF_FREE:
        return settings.FREE_BOOKINGS_PER_MONTH
    return None


def tariff_label(tariff: str) -> str:
    if tariff == TARIFF_STARTER:
        return f"Старт {settings.TARIFF_STARTER_RUB} ₽/мес"
    if tariff == TARIFF_PLUS:
        return f"Плюс {settings.TARIFF_PLUS_RUB} ₽/мес"
    return "Free"


def is_subscription_active(studio: Studio, now: datetime | None = None) -> bool:
    if studio.tariff == TARIFF_FREE:
        return True
    until = studio.subscription_until
    if until is None:
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until > (now or utcnow())


async def count_resources(session: AsyncSession, studio_id: int) -> int:
    value = await session.scalar(
        select(func.count()).select_from(Resource).where(Resource.studio_id == studio_id)
    )
    return int(value or 0)


async def count_month_bookings(session: AsyncSession, studio_id: int) -> int:
    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    value = await session.scalar(
        select(func.count())
        .select_from(Booking)
        .where(
            Booking.studio_id == studio_id,
            Booking.status.in_((STATUS_HOLD, STATUS_PAID)),
            Booking.created_at >= month_start,
        )
    )
    return int(value or 0)


async def can_add_resource(session: AsyncSession, studio: Studio) -> tuple[bool, str]:
    limit = resource_limit_for(studio.tariff)
    current = await count_resources(session, studio.id)
    if current < limit:
        return True, ""
    if studio.tariff != TARIFF_PLUS:
        return (
            False,
            f"На тарифе «{tariff_label(studio.tariff)}» доступен 1 зал. "
            f"До 6 залов — тариф Плюс {settings.TARIFF_PLUS_RUB} ₽/мес.",
        )
    return False, "Лимит ресурсов исчерпан."


async def can_create_booking(session: AsyncSession, studio: Studio) -> tuple[bool, str]:
    limit = monthly_booking_limit(studio)
    if limit is None:
        return True, ""
    used = await count_month_bookings(session, studio.id)
    if used < limit:
        return True, ""
    return (
        False,
        f"На Free исчерпан лимит {limit} записей в месяц. "
        f"Тариф Старт — {settings.TARIFF_STARTER_RUB} ₽/мес.",
    )
