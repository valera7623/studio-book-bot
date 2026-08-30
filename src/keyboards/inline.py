from datetime import date, datetime
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.services.slots import Slot


def profile_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="↩️ Закрыть", callback_data="profile_close")
    builder.adjust(1)
    return builder.as_markup()


def welcome_keyboard(*, has_studio: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_studio:
        builder.button(text="🏠 Кабинет студии", callback_data="ow:cab")
    else:
        builder.button(text="🏠 Создать студию", callback_data="ow:new")
    builder.adjust(1)
    return builder.as_markup()


def owner_cabinet_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Брони", callback_data="ow:book")
    builder.button(text="🔗 Ссылка записи", callback_data="ow:link")
    builder.button(text="🕒 Часы работы", callback_data="ow:hr")
    builder.button(text="💰 Цена часа", callback_data="ow:price")
    builder.button(text="➕ Второй ресурс", callback_data="ow:res")
    builder.button(text="💳 Тариф", callback_data="ow:tariff")
    builder.button(text="📅 iCal", callback_data="ow:ical")
    builder.adjust(2)
    return builder.as_markup()


def date_keyboard(studio_id: int, days: list[date], tz_name: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for day in days:
        label = day.strftime("%d.%m (%a)")
        builder.button(text=label, callback_data=f"bk:d:{studio_id}:{day.isoformat()}")
    builder.adjust(2)
    return builder.as_markup()


def slot_keyboard(resource_id: int, slots: list[Slot], tz_name: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    tz = ZoneInfo(tz_name)
    for slot in slots[:20]:
        local: datetime = slot.starts_at.astimezone(tz)
        ts = int(slot.starts_at.timestamp())
        builder.button(text=local.strftime("%H:%M"), callback_data=f"bk:s:{resource_id}:{ts}")
    builder.button(text="↩️ Другая дата", callback_data="bk:back")
    builder.adjust(4)
    return builder.as_markup()


def consent_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Согласен на обработку ПДн", callback_data="bk:consent")
    builder.button(text="❌ Отмена", callback_data="bk:cancel")
    builder.adjust(1)
    return builder.as_markup()


def pay_keyboard(url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Оплатить", url=url)
    return builder.as_markup()


def bookings_keyboard(items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for booking_id, label in items:
        builder.button(text=f"❌ {label}", callback_data=f"ow:c:{booking_id}")
    builder.button(text="↩️ Кабинет", callback_data="ow:cab")
    builder.adjust(1)
    return builder.as_markup()


def tariff_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Старт 490 ₽/мес", callback_data="ow:pay:starter")
    builder.button(text="Плюс 990 ₽/мес", callback_data="ow:pay:plus")
    builder.button(text="↩️ Кабинет", callback_data="ow:cab")
    builder.adjust(1)
    return builder.as_markup()
