from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def profile_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="↩️ Закрыть", callback_data="profile_close")
    builder.adjust(1)
    return builder.as_markup()
