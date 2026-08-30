from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

from src.database.models.booking import Booking
from src.database.models.studio import Resource, Studio


def format_slot_local(starts_at: datetime, tz_name: str = "Europe/Moscow") -> str:
    tz = ZoneInfo(tz_name)
    local = starts_at.astimezone(tz) if starts_at.tzinfo else starts_at.replace(tzinfo=timezone.utc).astimezone(tz)
    return local.strftime("%d.%m.%Y %H:%M")


def booking_summary(booking: Booking, studio: Studio, resource: Resource) -> str:
    when = format_slot_local(booking.starts_at, resource.timezone or studio.timezone)
    return (
        f"🏠 <b>{escape(studio.name)}</b>\n"
        f"🎬 {escape(resource.name)}\n"
        f"🕒 {when}\n"
        f"👤 {escape(booking.client_name)}\n"
        f"📞 {escape(booking.client_phone or '—')}"
    )
