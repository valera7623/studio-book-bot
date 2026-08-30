"""Саппорт платформы: сводка, не контент."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.models.studio import Studio
from src.database.models.user import User

router = Router()


@router.message(Command("admin"), F.from_user.id.in_(settings.ADMINS))
async def cmd_admin(message: Message, session: AsyncSession):
    users_n = await session.scalar(select(func.count()).select_from(User)) or 0
    studios_n = await session.scalar(select(func.count()).select_from(Studio)) or 0

    text = (
        "🛠️ <b>Саппорт платформы</b>\n\n"
        f"👥 Пользователей: <b>{users_n}</b>\n"
        f"🏠 Студий: <b>{studios_n}</b>\n\n"
        "<i>Только для ID из ADMINS. Это не кабинет владельца студии.</i>"
    )
    await message.answer(text)
