"""Список броней владельца: страницы, фильтр по дате, отмены. Не календарь."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.base import utcnow
from src.database.models.booking import (
    ACTIVE_STATUSES,
    STATUS_BLOCKED,
    STATUS_CANCELLED,
    STATUS_HOLD,
    Booking,
)
from src.services.formatters import format_day_label, format_slot_local

PAGE_SIZE = 8
MODE_ALL = "a"
MODE_TODAY = "t"
MODE_TOMORROW = "n"
MODE_WEEK = "w"
MODE_CANCELLED = "c"
MODE_DATE = "d"
MODES = (MODE_ALL, MODE_TODAY, MODE_TOMORROW, MODE_WEEK, MODE_CANCELLED, MODE_DATE)

_MODE_TITLE = {
    MODE_ALL: "все",
    MODE_TODAY: "сегодня",
    MODE_TOMORROW: "завтра",
    MODE_WEEK: "7 дней",
    MODE_CANCELLED: "отмены",
}


@dataclass
class BookingsPage:
    rows: list[Booking]
    total: int
    page: int
    pages: int
    mode: str
    day: date | None


def parse_owner_date(text: str, *, today: date) -> date | None:
    raw = (text or "").strip()
    if not raw:
        return None
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%d.%m", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt)
            if fmt == "%d.%m":
                parsed = parsed.replace(year=today.year)
            return parsed.date()
        except ValueError:
            continue
    return None


def local_day_range(day: date, tz_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def bookings_callback(mode: str, page: int, day: date | None = None) -> str:
    if mode == MODE_DATE and day is not None:
        return f"ow:bkd:{day.isoformat()}:{page}"
    return f"ow:bk:{mode}:{page}"


def format_cancel_reason(reason: str | None) -> str:
    if not reason:
        return "отмена"
    if reason == "hold_expired":
        return "hold истёк"
    by, _, code = reason.partition(":")
    who = {"owner": "владелец", "client": "клиент"}.get(by, by or "отмена")
    extra = {
        "free_cancel": "в срок",
        "late_cancel": "поздно",
        "owner_cancel": "",
        "no_payment": "без оплаты",
        "already": "",
        "bad_status": "",
    }.get(code, code)
    if extra:
        return f"{who}, {extra}"
    return who


def _window(
    mode: str,
    day: date | None,
    tz_name: str,
    now: datetime,
) -> tuple[datetime | None, datetime | None]:
    tz = ZoneInfo(tz_name)
    today = now.astimezone(tz).date()
    if mode == MODE_DATE and day is not None:
        return local_day_range(day, tz_name)
    if mode == MODE_TODAY:
        return local_day_range(today, tz_name)
    if mode == MODE_TOMORROW:
        return local_day_range(today + timedelta(days=1), tz_name)
    if mode == MODE_WEEK:
        start, _ = local_day_range(today, tz_name)
        _, end = local_day_range(today + timedelta(days=6), tz_name)
        return start, end
    if mode == MODE_ALL:
        start, _ = local_day_range(today, tz_name)
        return start, None
    return None, None


async def list_owner_bookings(
    session: AsyncSession,
    studio_id: int,
    *,
    mode: str = MODE_ALL,
    day: date | None = None,
    page: int = 0,
    tz_name: str,
    now: datetime | None = None,
    page_size: int | None = None,
) -> BookingsPage:
    if mode not in MODES:
        mode = MODE_ALL
    if mode == MODE_DATE and day is None:
        mode = MODE_ALL
    now = now or utcnow()
    size = page_size or PAGE_SIZE
    start, end = _window(mode, day, tz_name, now)
    cancelled = mode == MODE_CANCELLED
    filters = [Booking.studio_id == studio_id]
    if cancelled:
        filters.append(Booking.status == STATUS_CANCELLED)
    else:
        filters.append(Booking.status.in_(ACTIVE_STATUSES))
    if start is not None:
        filters.append(Booking.starts_at >= start)
    if end is not None:
        filters.append(Booking.starts_at < end)

    total = int(
        (await session.execute(select(func.count(Booking.id)).where(*filters))).scalar_one()
    )
    pages = max(1, math.ceil(total / size)) if total else 1
    page = max(0, min(int(page), pages - 1))
    order = Booking.starts_at.desc() if cancelled else Booking.starts_at.asc()
    stmt = (
        select(Booking)
        .options(selectinload(Booking.resource))
        .where(*filters)
        .order_by(order)
        .offset(page * size)
        .limit(size)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return BookingsPage(
        rows=rows,
        total=total,
        page=page,
        pages=pages,
        mode=mode,
        day=day if mode == MODE_DATE else None,
    )


def bookings_heading(page_data: BookingsPage) -> str:
    if page_data.mode == MODE_DATE and page_data.day is not None:
        title = format_day_label(page_data.day)
    else:
        title = _MODE_TITLE.get(page_data.mode, "все")
    if page_data.mode == MODE_CANCELLED:
        head = "📋 <b>Отмены</b>"
    else:
        head = f"📋 <b>Брони</b> · {escape(title)}"
    if page_data.total == 0:
        if page_data.mode == MODE_CANCELLED:
            empty = "Отменённых броней нет."
        elif page_data.mode in (MODE_DATE, MODE_TODAY, MODE_TOMORROW, MODE_WEEK):
            empty = "На эти даты броней нет."
        else:
            empty = "Активных броней нет."
        return f"{head}\n{empty}"
    pages_bit = ""
    if page_data.pages > 1:
        pages_bit = f", стр. {page_data.page + 1} из {page_data.pages}"
    return f"{head}\n{page_data.total} записей{pages_bit}"


def format_booking_line(booking: Booking, tz_name: str, *, cancelled: bool = False) -> str:
    resource = booking.resource
    hall = resource.name if resource else "зал"
    tz = (resource.timezone if resource and resource.timezone else None) or tz_name
    when = format_slot_local(booking.starts_at, tz)
    name = escape(booking.client_name)
    phone = escape(booking.client_phone or "—")
    if cancelled:
        reason = format_cancel_reason(booking.cancel_reason)
        return f"❌ {escape(hall)} {when} — {name}\n   {escape(reason)}"
    if booking.status == STATUS_HOLD:
        mark = "⏳"
    elif booking.status == STATUS_BLOCKED:
        mark = "🚫"
    else:
        mark = "✅"
    return f"{mark} {escape(hall)} {when} — {name} ({phone})"
