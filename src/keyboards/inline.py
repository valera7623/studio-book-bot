from datetime import date, datetime
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.database.models.studio import Resource
from src.services.formatters import format_day_label
from src.services.slots import Slot, allowed_durations, parse_weekdays, quote_price_rub


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
    builder.button(text="❓ Шпаргалка", callback_data="ow:guide")
    builder.button(text="📋 Брони", callback_data="ow:book")
    builder.button(text="🔗 Ссылка записи", callback_data="ow:link")
    builder.button(text="📣 Тексты", callback_data="ow:txt")
    builder.button(text="🕒 Часы работы", callback_data="ow:hr")
    builder.button(text="🗓 Дни недели", callback_data="ow:days")
    builder.button(text="💰 Цена часа", callback_data="ow:price")
    builder.button(text="📐 Сетка цен", callback_data="ow:grid")
    builder.button(text="⚙️ Правила", callback_data="ow:rules")
    builder.button(text="⏱ Слоты", callback_data="ow:slot")
    builder.button(text="🚫 Закрыть интервал", callback_data="ow:block")
    builder.button(text="➕ Зал", callback_data="ow:res")
    builder.button(text="✏️ Залы", callback_data="ow:hall")
    builder.button(text="💳 Тариф", callback_data="ow:tariff")
    builder.button(text="📅 iCal", callback_data="ow:ical")
    builder.adjust(1, 2)
    return builder.as_markup()


def hall_manage_keyboard(resource: Resource) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Переименовать", callback_data=f"ow:ren:{resource.id}")
    builder.button(text="⏹ Выключить", callback_data=f"ow:off:{resource.id}")
    builder.button(text="↩️ Кабинет", callback_data="ow:cab")
    builder.adjust(1)
    return builder.as_markup()


def hall_off_confirm_keyboard(resource_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, выключить", callback_data=f"ow:ofok:{resource_id}")
    builder.button(text="Отмена", callback_data="ow:cab")
    builder.adjust(1)
    return builder.as_markup()


def resource_keyboard(studio_id: int, resources: list[Resource]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for resource in resources:
        builder.button(text=resource.name, callback_data=f"bk:r:{studio_id}:{resource.id}")
    builder.adjust(1)
    return builder.as_markup()


def date_keyboard(resource_id: int, days: list[date], tz_name: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for day in days:
        label = format_day_label(day)
        builder.button(text=label, callback_data=f"bk:d:{resource_id}:{day.isoformat()}")
    builder.adjust(2)
    return builder.as_markup()


def duration_keyboard(resource: Resource, day_iso: str, sample_start: datetime) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for minutes in allowed_durations(resource):
        hours = minutes / 60
        price = quote_price_rub(resource, sample_start, minutes)
        if hours == int(hours):
            label = f"{int(hours)} ч"
        else:
            label = f"{minutes} мин"
        if price:
            label = f"{label} · {price} ₽"
        if minutes < (resource.min_duration_min or 60):
            label = f"{label} *"
        builder.button(text=label, callback_data=f"bk:n:{resource.id}:{day_iso}:{minutes}")
    builder.button(text="↩️ Другая дата", callback_data="bk:back")
    builder.adjust(2)
    return builder.as_markup()


def slot_keyboard(
    resource_id: int,
    slots: list[Slot],
    tz_name: str,
    duration_min: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    tz = ZoneInfo(tz_name)
    for slot in slots[:20]:
        local: datetime = slot.starts_at.astimezone(tz)
        ts = int(slot.starts_at.timestamp())
        label = local.strftime("%H:%M")
        if slot.price_rub:
            label = f"{label} {slot.price_rub}₽"
        builder.button(
            text=label,
            callback_data=f"bk:s:{resource_id}:{ts}:{duration_min}",
        )
    builder.button(text="↩️ Другая дата", callback_data="bk:back")
    builder.adjust(3)
    return builder.as_markup()


def consent_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Согласен на обработку ПДн", callback_data="bk:consent")
    builder.button(text="❌ Отмена", callback_data="bk:cancel")
    builder.adjust(1)
    return builder.as_markup()


def pay_keyboard(url: str, booking_id: int | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Оплатить", url=url)
    if booking_id:
        builder.button(text="❌ Отменить бронь", callback_data=f"bk:cx:{booking_id}")
    builder.adjust(1)
    return builder.as_markup()


def client_booking_keyboard(
    booking_id: int,
    *,
    can_pay: bool = False,
    pay_url: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if pay_url:
        builder.button(text="💳 Оплатить", url=pay_url)
    elif can_pay:
        builder.button(text="💳 Оплатить", callback_data=f"bk:pay:{booking_id}")
    builder.button(text="❌ Отменить бронь", callback_data=f"bk:cx:{booking_id}")
    builder.adjust(1)
    return builder.as_markup()


def confirm_cancel_keyboard(booking_id: int, *, owner: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if owner:
        builder.button(text="✅ Да, отменить", callback_data=f"ow:cok:{booking_id}")
        builder.button(text="↩️ Назад", callback_data="ow:book")
    else:
        builder.button(text="✅ Да, отменить", callback_data=f"bk:cxok:{booking_id}")
        builder.button(text="↩️ Нет", callback_data=f"bk:cxno:{booking_id}")
    builder.adjust(1)
    return builder.as_markup()


def owner_hold_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить бронь", callback_data=f"ow:ok:{booking_id}")
    builder.button(text="❌ Отменить", callback_data=f"ow:c:{booking_id}")
    builder.adjust(1)
    return builder.as_markup()


def _bookings_nav_cb(mode: str, page: int, day: date | None = None) -> str:
    if mode == "d" and day is not None:
        return f"ow:bkd:{day.isoformat()}:{page}"
    return f"ow:bk:{mode}:{page}"


def bookings_keyboard(
    items: list[tuple[int, str, str]],
    *,
    mode: str = "a",
    page: int = 0,
    pages: int = 1,
    day: date | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    filters = (
        ("a", "Все"),
        ("t", "Сегодня"),
        ("n", "Завтра"),
        ("w", "7 дней"),
        ("c", "Отмены"),
    )
    for code, label in filters:
        mark = "· " if mode == code else ""
        builder.button(text=f"{mark}{label}", callback_data=_bookings_nav_cb(code, 0))
    date_label = "Дата…"
    if mode == "d" and day is not None:
        date_label = day.strftime("%d.%m")
    date_mark = "· " if mode == "d" else ""
    builder.button(text=f"{date_mark}{date_label}", callback_data="ow:bkp")

    item_buttons = 0
    cancelled = mode == "c"
    for booking_id, label, status in items:
        if cancelled:
            continue
        short = label[:24]
        if status == "hold":
            builder.button(text=f"Подтвердить {short}", callback_data=f"ow:ok:{booking_id}")
            item_buttons += 1
        builder.button(text=f"Отменить {short}", callback_data=f"ow:c:{booking_id}")
        item_buttons += 1

    nav = pages > 1
    if nav:
        prev_page = max(0, page - 1)
        next_page = min(pages - 1, page + 1)
        builder.button(text="‹", callback_data=_bookings_nav_cb(mode, prev_page, day))
        builder.button(text=f"{page + 1}/{pages}", callback_data="ow:bkn")
        builder.button(text="›", callback_data=_bookings_nav_cb(mode, next_page, day))

    builder.button(text="↩️ Кабинет", callback_data="ow:cab")
    sizes = [3, 3]
    sizes.extend([1] * item_buttons)
    if nav:
        sizes.append(3)
    sizes.append(1)
    builder.adjust(*sizes)
    return builder.as_markup()


def owner_resource_pick_keyboard(resources: list[Resource], prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for resource in resources:
        builder.button(text=resource.name, callback_data=f"{prefix}:{resource.id}")
    builder.button(text="↩️ Кабинет", callback_data="ow:cab")
    builder.adjust(1)
    return builder.as_markup()


def rules_keyboard(studio) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for minutes, label in ((20, "20 мин"), (60, "1 ч"), (720, "12 ч"), (1440, "24 ч")):
        mark = "· " if studio.hold_ttl_minutes == minutes else ""
        builder.button(text=f"{mark}оплата {label}", callback_data=f"ow:hold:{minutes}")
    builder.button(text=("· " if studio.prepay_percent == 50 else "") + "предоплата 50%", callback_data="ow:prepay:50")
    builder.button(text=("· " if studio.prepay_percent == 100 else "") + "предоплата 100%", callback_data="ow:prepay:100")
    for hours in (24, 72, 120):
        mark = "· " if studio.cancel_free_hours == hours else ""
        builder.button(text=f"{mark}отмена {hours} ч", callback_data=f"ow:cxh:{hours}")
    builder.button(text="↩️ Кабинет", callback_data="ow:cab")
    builder.adjust(2)
    return builder.as_markup()


def slot_settings_keyboard(resource: Resource) -> InlineKeyboardMarkup:
    rid = resource.id
    builder = InlineKeyboardBuilder()
    builder.button(
        text=("· " if resource.slot_step_min == 30 else "") + "шаг 30 мин",
        callback_data=f"ow:step:{rid}:30",
    )
    builder.button(
        text=("· " if resource.slot_step_min == 60 else "") + "шаг 60 мин",
        callback_data=f"ow:step:{rid}:60",
    )
    builder.button(
        text=("· " if resource.min_duration_min == 60 else "") + "мин. 1 ч",
        callback_data=f"ow:mind:{rid}:60",
    )
    builder.button(
        text=("· " if resource.min_duration_min == 120 else "") + "мин. 2 ч",
        callback_data=f"ow:mind:{rid}:120",
    )
    builder.button(
        text=("· " if resource.buffer_min == 5 else "") + "буфер 5",
        callback_data=f"ow:buf:{rid}:5",
    )
    builder.button(
        text=("· " if resource.buffer_min == 10 else "") + "буфер 10",
        callback_data=f"ow:buf:{rid}:10",
    )
    builder.button(text="↩️ Кабинет", callback_data="ow:cab")
    builder.adjust(2)
    return builder.as_markup()


_WD_BUTTONS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def weekdays_keyboard(resource: Resource) -> InlineKeyboardMarkup:
    allowed = parse_weekdays(resource.weekdays) or {1, 2, 3, 4, 5, 6, 7}
    builder = InlineKeyboardBuilder()
    for n, label in enumerate(_WD_BUTTONS, start=1):
        mark = "· " if n in allowed else ""
        builder.button(text=f"{mark}{label}", callback_data=f"ow:wd:{resource.id}:{n}")
    builder.button(text="↩️ Кабинет", callback_data="ow:cab")
    builder.adjust(7, 1)
    return builder.as_markup()


def grid_keyboard(resource_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Будни (база)", callback_data=f"ow:prp:{resource_id}")
    builder.button(text="Выходные", callback_data=f"ow:wknd:{resource_id}")
    builder.button(text="Ночь с 22:00", callback_data=f"ow:night:{resource_id}")
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
