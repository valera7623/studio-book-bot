from datetime import datetime, timedelta, timezone

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
from src.services.studios import list_active_resources

SUBSCRIPTION_REMIND_DAYS = 3


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def resource_limit_for(tariff: str) -> int:
    if tariff == TARIFF_PLUS:
        return max(settings.PLUS_RESOURCE_LIMIT, settings.FREE_RESOURCE_LIMIT + 1)
    return settings.FREE_RESOURCE_LIMIT


def tariff_label(tariff: str) -> str:
    if tariff == TARIFF_STARTER:
        return f"Старт {settings.TARIFF_STARTER_RUB} ₽/мес"
    if tariff == TARIFF_PLUS:
        return f"Плюс {settings.TARIFF_PLUS_RUB} ₽/мес"
    return "Free"


def is_paid_tariff(tariff: str) -> bool:
    return tariff in (TARIFF_STARTER, TARIFF_PLUS)


def is_subscription_active(studio: Studio, now: datetime | None = None) -> bool:
    if studio.tariff == TARIFF_FREE:
        return True
    until = _as_utc(studio.subscription_until)
    if until is None:
        return False
    return until > (now or utcnow())


def is_paid_subscription_active(studio: Studio, now: datetime | None = None) -> bool:
    return is_paid_tariff(studio.tariff) and is_subscription_active(studio, now)


def effective_tariff(studio: Studio, now: datetime | None = None) -> str:
    if is_paid_subscription_active(studio, now):
        return studio.tariff
    return TARIFF_FREE


def monthly_booking_limit(studio: Studio, now: datetime | None = None) -> int | None:
    if effective_tariff(studio, now) == TARIFF_FREE:
        return settings.FREE_BOOKINGS_PER_MONTH
    return None


def until_label(studio: Studio) -> str:
    until = _as_utc(studio.subscription_until)
    if until is None:
        return "—"
    return until.strftime("%d.%m.%Y")


def tariff_cabinet_line(studio: Studio, now: datetime | None = None) -> str:
    current = effective_tariff(studio, now)
    label = tariff_label(current)
    if is_paid_subscription_active(studio, now):
        return f"Тариф: {label} до {until_label(studio)}"
    until = _as_utc(studio.subscription_until)
    if until is not None and until <= (now or utcnow()):
        return f"Тариф: Free (подписка истекла {until_label(studio)})"
    return f"Тариф: {label}"


def subscription_remind_text(studio: Studio) -> str:
    return (
        f"⏰ Подписка «{tariff_label(studio.tariff)}» действует до {until_label(studio)} "
        f"(осталось меньше {SUBSCRIPTION_REMIND_DAYS} дней).\n"
        f"Потом студия станет Free: 1 зал, {settings.FREE_BOOKINGS_PER_MONTH} записей/мес.\n"
        "Продлить: /studio → Тариф."
    )


def subscription_downgrade_text(studio: Studio, extra_names: list[str] | None = None) -> str:
    extra = ""
    if extra_names:
        halls = ", ".join(f"«{name}»" for name in extra_names)
        extra = f"\nВыключены залы: {halls}. Снова включить — после оплаты Плюс."
    return (
        f"Подписка закончилась {until_label(studio)} — студия на Free.\n"
        f"Лимит: 1 зал, {settings.FREE_BOOKINGS_PER_MONTH} записей в месяц.{extra}\n"
        "Продлить: /studio → Тариф."
    )


async def list_active_paid_studios(
    session: AsyncSession, now: datetime | None = None
) -> list[Studio]:
    moment = now or utcnow()
    studios = list(
        (
            await session.execute(
                select(Studio)
                .where(Studio.tariff.in_((TARIFF_STARTER, TARIFF_PLUS)))
                .order_by(Studio.id.asc())
            )
        ).scalars().all()
    )
    return [studio for studio in studios if is_paid_subscription_active(studio, moment)]


async def count_resources(session: AsyncSession, studio_id: int) -> int:
    """Считаем только активные залы — выключенный освобождает слот лимита."""
    value = await session.scalar(
        select(func.count())
        .select_from(Resource)
        .where(Resource.studio_id == studio_id, Resource.is_active.is_(True))
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


async def sync_expired_subscription(
    session: AsyncSession, studio: Studio, now: datetime | None = None
) -> tuple[bool, list[str]]:
    """Просроченный Старт/Плюс → Free. Лишние залы выключаются."""
    if not is_paid_tariff(studio.tariff):
        return False, []
    if is_subscription_active(studio, now):
        return False, []
    studio.tariff = TARIFF_FREE
    studio.resource_limit = settings.FREE_RESOURCE_LIMIT
    resources = await list_active_resources(session, studio.id)
    extra_names = []
    for resource in resources[settings.FREE_RESOURCE_LIMIT :]:
        resource.is_active = False
        extra_names.append(resource.name)
    return True, extra_names


async def collect_due_subscription_notices(
    session: AsyncSession, now: datetime | None = None
) -> list[tuple[Studio, str]]:
    """Пары (студия, 'remind'|'downgrade') без повторных писем."""
    now = now or utcnow()
    remind_until = now + timedelta(days=SUBSCRIPTION_REMIND_DAYS)
    studios = list(
        (
            await session.execute(
                select(Studio)
                .where(Studio.subscription_until.is_not(None))
                .order_by(Studio.id.asc())
            )
        ).scalars().all()
    )
    due: list[tuple[Studio, str]] = []
    for studio in studios:
        until = _as_utc(studio.subscription_until)
        if until is None:
            continue
        if is_paid_subscription_active(studio, now):
            if now < until <= remind_until and studio.subscription_reminded_at is None:
                due.append((studio, "remind"))
            continue
        if until <= now and studio.subscription_downgrade_notice_at is None:
            due.append((studio, "downgrade"))
    return due


async def can_add_resource(session: AsyncSession, studio: Studio) -> tuple[bool, str]:
    changed, _extra = await sync_expired_subscription(session, studio)
    if changed:
        await session.commit()
    current_tariff = effective_tariff(studio)
    limit = resource_limit_for(current_tariff)
    current = await count_resources(session, studio.id)
    if current < limit:
        return True, ""
    if current_tariff != TARIFF_PLUS:
        return (
            False,
            f"На тарифе «{tariff_label(current_tariff)}» доступен 1 зал. "
            f"До 6 залов — тариф Плюс {settings.TARIFF_PLUS_RUB} ₽/мес.",
        )
    return False, "Лимит ресурсов исчерпан."


async def can_create_booking(session: AsyncSession, studio: Studio) -> tuple[bool, str]:
    changed, _extra = await sync_expired_subscription(session, studio)
    if changed:
        await session.commit()
    now = utcnow()
    limit = monthly_booking_limit(studio, now)
    if limit is None:
        return True, ""
    used = await count_month_bookings(session, studio.id)
    if used < limit:
        return True, ""
    until = _as_utc(studio.subscription_until)
    expired = until is not None and until <= now
    if expired:
        return (
            False,
            f"Подписка истекла — студия на Free ({limit} записей/мес). "
            f"Продлите Старт {settings.TARIFF_STARTER_RUB} ₽ в /studio → Тариф.",
        )
    return (
        False,
        f"На Free исчерпан лимит {limit} записей в месяц. "
        f"Тариф Старт — {settings.TARIFF_STARTER_RUB} ₽/мес.",
    )
