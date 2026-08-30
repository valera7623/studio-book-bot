"""Генерация .ics без внешних парсеров."""

from datetime import datetime, timezone

from src.database.models.booking import Booking
from src.database.models.studio import Resource, Studio


def _fmt(dt: datetime) -> str:
    utc = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return utc.strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def booking_to_vevent(booking: Booking, studio: Studio, resource: Resource) -> str:
    uid = f"booking-{booking.id}@studio-book"
    summary = _escape(f"{studio.name}: {resource.name}")
    description = _escape(f"{booking.client_name} {booking.client_phone or ''}".strip())
    return "\n".join(
        [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_fmt(booking.created_at)}",
            f"DTSTART:{_fmt(booking.starts_at)}",
            f"DTEND:{_fmt(booking.ends_at)}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{description}",
            "END:VEVENT",
        ]
    )


def build_calendar(studio: Studio, resource: Resource, bookings: list[Booking]) -> str:
    events = "\n".join(booking_to_vevent(b, studio, resource) for b in bookings)
    return "\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//studio-book//photo studio//RU",
            "CALSCALE:GREGORIAN",
            f"X-WR-CALNAME:{_escape(studio.name)}",
            events,
            "END:VCALENDAR",
            "",
        ]
    )
