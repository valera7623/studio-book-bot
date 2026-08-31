"""Саппорт платформы: сводка, не контент."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.models.booking import Booking
from src.database.models.payment import Payment
from src.database.models.studio import Studio
from src.database.models.user import User
from src.services import prodamus

router = Router()


def _count_lines(rows: list[tuple[str, int]], empty: str = "—") -> str:
    if not rows:
        return empty
    return ", ".join(f"{status} {n}" for status, n in rows)


async def platform_support_text(session: AsyncSession) -> str:
    users_n = await session.scalar(select(func.count()).select_from(User)) or 0
    studios_n = await session.scalar(select(func.count()).select_from(Studio)) or 0
    pay_rows = (
        await session.execute(
            select(Payment.status, func.count()).group_by(Payment.status)
        )
    ).all()
    book_rows = (
        await session.execute(
            select(Booking.status, func.count()).group_by(Booking.status)
        )
    ).all()
    payform = "да" if prodamus.is_configured() else "нет"
    webhook = ""
    if settings.PUBLIC_BASE_URL.strip():
        webhook = settings.PUBLIC_BASE_URL.rstrip("/") + "/prodamus/webhook"
    return (
        "🛠️ <b>Саппорт платформы</b>\n\n"
        f"Касса Prodamus: <b>{payform}</b>\n"
        f"Webhook: <code>{webhook or 'задайте PUBLIC_BASE_URL'}</code>\n"
        f"👥 Пользователей: <b>{users_n}</b>\n"
        f"🏠 Студий: <b>{studios_n}</b>\n"
        f"Платежи: {_count_lines([(str(s), int(n)) for s, n in pay_rows])}\n"
        f"Брони: {_count_lines([(str(s), int(n)) for s, n in book_rows])}\n\n"
        "<i>Только для ID из ADMINS. Это не кабинет владельца студии.</i>"
    )


@router.message(Command("admin"), F.from_user.id.in_(settings.ADMINS))
async def cmd_admin(message: Message, session: AsyncSession):
    await message.answer(await platform_support_text(session))
