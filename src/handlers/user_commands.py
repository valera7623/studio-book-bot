from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.config import settings
from src.utils.text_formatter import format_welcome_message

router = Router()


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    user,
    state: FSMContext,
):
    await state.clear()
    payload = (command.args or "").strip()

    # Публичная запись: t.me/bot?start=<studio_slug> или start=book_<id>
    # FSM записи — следующий шаг (слоты + hold).
    if payload:
        await message.answer(
            "📅 Ссылка записи получена. Выбор слота появится в следующем шаге.\n\n"
            + format_welcome_message(user),
        )
        return

    await message.answer(format_welcome_message(user))


@router.message(Command("help"))
async def cmd_help(message: Message, user):
    parts = [
        "🤖 <b>Команды</b>\n",
        "/start — начало",
        "/help — эта справка",
        "/profile — профиль Telegram",
        "",
        "Клиент студии открывает ссылку записи — пароль не нужен.",
        "Владелец управляет студией в этом же боте после привязки Telegram.",
    ]
    if user.telegram_id in settings.admin_ids:
        parts.append("")
        parts.append("/admin — сводка платформы (саппорт)")
    await message.answer("\n".join(parts))
