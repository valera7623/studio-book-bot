from __future__ import annotations

import logging
import shutil
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from src.config import settings
from src.database.base import utcnow
from src.database.models.booking import STATUS_PAID, Booking
from src.database.models.studio import Resource, Studio
from src.services.formatters import booking_summary
from src.services.slots import expire_holds

logger = logging.getLogger(__name__)


async def job_expire_holds(session_maker) -> None:
    async with session_maker() as session:
        n = await expire_holds(session)
        if n:
            logger.info("expired holds: %s", n)


async def job_reminders(bot, session_maker) -> None:
    horizon = utcnow() + timedelta(hours=settings.REMINDER_HOURS)
    now = utcnow()
    async with session_maker() as session:
        stmt = select(Booking).where(
            Booking.status == STATUS_PAID,
            Booking.reminder_sent_at.is_(None),
            Booking.starts_at > now,
            Booking.starts_at <= horizon,
        )
        rows = (await session.execute(stmt)).scalars().all()
        for booking in rows:
            studio = await session.get(Studio, booking.studio_id)
            resource = await session.get(Resource, booking.resource_id)
            if not studio or not resource:
                continue
            text = "🔔 Напоминание о съёмке\n" + booking_summary(booking, studio, resource)
            for chat_id in (booking.client_telegram_id, studio.owner_telegram_id):
                try:
                    await bot.send_message(chat_id, text)
                except Exception:
                    logger.exception("reminder send %s", chat_id)
            booking.reminder_sent_at = now
        if rows:
            await session.commit()


def backup_sqlite() -> Path | None:
    src = Path(settings.SQLITE_PATH)
    if not src.exists():
        return None
    dest_dir = src.parent / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%d")
    dest = dest_dir / f"studio_book-{stamp}.db"
    shutil.copy2(src, dest)
    keep = sorted(dest_dir.glob("studio_book-*.db"), reverse=True)
    for old in keep[14:]:
        old.unlink(missing_ok=True)
    logger.info("sqlite backup: %s", dest)
    return dest


def job_backup_sqlite() -> None:
    backup_sqlite()
