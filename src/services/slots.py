from datetime import datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.base import utcnow
from src.database.models.booking import STATUS_HOLD, STATUS_PAID, Booking
from src.database.models.studio import Resource


class Slot:
    __slots__ = ("starts_at", "ends_at")

    def __init__(self, starts_at: datetime, ends_at: datetime):
        self.starts_at = starts_at
        self.ends_at = ends_at


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_hours(text: str) -> tuple[time, time] | None:
    raw = text.strip().replace("–", "-").replace("—", "-")
    parts = re.split(r"[\s-]+", raw)
    if len(parts) < 2:
        return None
    try:
        start_h, start_m = _parse_hm(parts[0])
        end_h, end_m = _parse_hm(parts[1])
        start = time(start_h, start_m)
        end = time(end_h, end_m)
    except ValueError:
        return None
    if start >= end:
        return None
    return start, end


def _parse_hm(value: str) -> tuple[int, int]:
    bits = value.replace(".", ":").split(":")
    hour = int(bits[0])
    minute = int(bits[1]) if len(bits) > 1 else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("bad time")
    return hour, minute


async def expire_holds(session: AsyncSession) -> int:
    now = utcnow()
    stmt = select(Booking).where(
        Booking.status == STATUS_HOLD,
        Booking.hold_expires_at.is_not(None),
        Booking.hold_expires_at <= now,
    )
    rows = (await session.execute(stmt)).scalars().all()
    for booking in rows:
        booking.status = "cancelled"
        booking.cancel_reason = "hold_expired"
    if rows:
        await session.commit()
    return len(rows)


async def occupied_starts(
    session: AsyncSession,
    resource_id: int,
    day_start: datetime,
    day_end: datetime,
) -> set[datetime]:
    stmt = select(Booking.starts_at).where(
        Booking.resource_id == resource_id,
        Booking.status.in_((STATUS_HOLD, STATUS_PAID)),
        Booking.starts_at >= day_start,
        Booking.starts_at < day_end,
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {_as_utc(item) for item in rows}


def generate_slots_for_day(resource: Resource, day) -> list[Slot]:
    tz = ZoneInfo(resource.timezone or "Europe/Moscow")
    weekday = str(day.isoweekday())
    allowed = {part.strip() for part in (resource.weekdays or "").split(",") if part.strip()}
    if allowed and weekday not in allowed:
        return []
    duration = timedelta(minutes=resource.duration_min or 60)
    cursor = datetime.combine(day, resource.work_start, tzinfo=tz)
    end_at = datetime.combine(day, resource.work_end, tzinfo=tz)
    slots: list[Slot] = []
    while cursor + duration <= end_at:
        slots.append(Slot(_as_utc(cursor), _as_utc(cursor + duration)))
        cursor += duration
    return slots


async def available_slots(
    session: AsyncSession,
    resource: Resource,
    day,
) -> list[Slot]:
    await expire_holds(session)
    tz = ZoneInfo(resource.timezone or "Europe/Moscow")
    day_start = datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)
    day_end = datetime.combine(day, time.max, tzinfo=tz).astimezone(timezone.utc)
    taken = await occupied_starts(session, resource.id, day_start, day_end)
    now = utcnow()
    result: list[Slot] = []
    for slot in generate_slots_for_day(resource, day):
        if slot.starts_at <= now:
            continue
        if slot.starts_at in taken:
            continue
        result.append(slot)
    return result


async def create_hold(
    session: AsyncSession,
    *,
    resource: Resource,
    starts_at: datetime,
    ends_at: datetime,
    client_telegram_id: int,
    client_name: str,
    client_phone: str | None,
    client_user_id: int | None,
) -> Booking | None:
    await expire_holds(session)
    booking = Booking(
        resource_id=resource.id,
        studio_id=resource.studio_id,
        client_user_id=client_user_id,
        client_telegram_id=client_telegram_id,
        client_name=client_name,
        client_phone=client_phone,
        starts_at=_as_utc(starts_at),
        ends_at=_as_utc(ends_at),
        status=STATUS_HOLD,
        hold_expires_at=utcnow() + timedelta(minutes=settings.HOLD_TTL_MINUTES),
    )
    session.add(booking)
    try:
        await session.commit()
        await session.refresh(booking)
        return booking
    except IntegrityError:
        await session.rollback()
        return None
