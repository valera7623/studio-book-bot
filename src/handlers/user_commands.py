from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.handlers.booking import start_public_booking
from src.keyboards.inline import welcome_keyboard
from src.services.studios import get_owner_studio
from src.utils.text_formatter import format_welcome_message

router = Router()


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    user,
    session: AsyncSession,
    state: FSMContext,
):
    payload = (command.args or "").strip()
    if payload:
        found = await start_public_booking(message, session, state, payload)
        if found:
            return
        await message.answer("Студия по этой ссылке не найдена.")

    await state.clear()
    studio = await get_owner_studio(session, user)
    text = format_welcome_message(user)
    if studio:
        text += f"\n\nВаша студия: <b>{escape(studio.name)}</b>."
    await message.answer(text, reply_markup=welcome_keyboard(has_studio=studio is not None))


@router.message(Command("help"))
async def cmd_help(message: Message, user):
    parts = [
        "🤖 <b>Команды</b>\n",
        "/start — начало",
        "/help — эта справка",
        "/studio — кабинет владельца (создать студию, слоты, брони)",
        "/profile — профиль Telegram",
        "",
        "Клиент студии открывает ссылку записи — пароль не нужен.",
        "Владелец управляет студией в этом же боте.",
    ]
    if user.telegram_id in settings.admin_ids:
        parts.append("")
        parts.append("/admin — сводка платформы (саппорт)")
    await message.answer("\n".join(parts))
