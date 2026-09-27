import math
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from src.config import settings
from src.database.base import utcnow
from src.database.models.booking import STATUS_CANCELLED, STATUS_HOLD, STATUS_PAID, Booking
from src.database.models.payment import (
    KIND_OWNER_SUBSCRIPTION,
    PAYMENT_PAID,
    PAYMENT_PENDING,
    PAYMENT_REFUND_PENDING,
    PAYMENT_REFUNDED,
    Payment,
)
from src.database.models.studio import Resource, Studio
from src.services.slots import shoot_minutes


WEEKDAYS_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def format_day_label(day) -> str:
    return f"{day.strftime('%d.%m')} ({WEEKDAYS_RU[day.weekday()]})"


def format_slot_local(starts_at: datetime, tz_name: str = "Europe/Moscow") -> str:
    tz = ZoneInfo(tz_name)
    local = starts_at.astimezone(tz) if starts_at.tzinfo else starts_at.replace(tzinfo=timezone.utc).astimezone(tz)
    return local.strftime("%d.%m.%Y %H:%M")


def format_interval_local(starts_at: datetime, ends_at: datetime, tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    start = starts_at.astimezone(tz) if starts_at.tzinfo else starts_at.replace(tzinfo=timezone.utc).astimezone(tz)
    end = ends_at.astimezone(tz) if ends_at.tzinfo else ends_at.replace(tzinfo=timezone.utc).astimezone(tz)
    return f"{start.strftime('%d.%m.%Y %H:%M')}–{end.strftime('%H:%M')}"


def hold_minutes_left(booking: Booking, now: datetime | None = None) -> int | None:
    if booking.status != STATUS_HOLD or booking.hold_expires_at is None:
        return None
    now = now or utcnow()
    exp = booking.hold_expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = (exp.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()
    if delta <= 0:
        return 0
    return int(math.ceil(delta / 60.0))


def hold_pay_line(booking: Booking, now: datetime | None = None) -> str:
    minutes = hold_minutes_left(booking, now)
    if minutes is None:
        return "⏳ Не оплачено"
    if minutes <= 0:
        return "⏳ Время на оплату вышло"
    return f"⏳ Осталось {minutes} мин на оплату"


def cashier_return_url(order_id: str) -> str:
    root = settings.PUBLIC_BASE_URL.strip().rstrip("/") or "https://studiobook.com.ru"
    return f"{root}/pay/success?{urlencode({'order': order_id})}"


def pay_result_copy(
    payment: Payment | None,
    booking: Booking | None,
    *,
    now: datetime | None = None,
) -> tuple[str, str, bool]:
    """Заголовок, статус брони, ждать ли подтверждение кассы."""
    if payment is None:
        return "Платёж не найден", "Статус брони неизвестен", False
    if payment.kind == KIND_OWNER_SUBSCRIPTION:
        if payment.status == PAYMENT_PAID:
            return "Подписка оплачена", "Статус: оплачено", False
        return "Подписка", "Статус: оплата ещё не подтверждена", payment.status == PAYMENT_PENDING
    if payment.status in (PAYMENT_REFUNDED, PAYMENT_REFUND_PENDING):
        return "Бронь не закреплена", "Статус: слот занят, деньги возвращаем", False
    if booking is None:
        if payment.status == PAYMENT_PAID:
            return "Оплата получена", "Статус: оплачено", False
        return "Оплата", "Статус: ещё не подтверждена", payment.status == PAYMENT_PENDING
    if booking.status == STATUS_PAID:
        return "Бронь подтверждена", "Статус: оплачено", False
    if booking.status == STATUS_CANCELLED:
        return "Бронь не подтверждена", "Статус: отменена", False
    if booking.status == STATUS_HOLD:
        minutes = hold_minutes_left(booking, now)
        if minutes is None:
            status = "Статус: ждёт оплату"
        elif minutes <= 0:
            status = "Статус: время на оплату вышло"
        else:
            status = f"Статус: ждёт оплату, осталось {minutes} мин на оплату"
        return "Бронь ещё не подтверждена", status, True
    return "Бронь", f"Статус: {booking.status}", False


def booking_summary(
    booking: Booking,
    studio: Studio,
    resource: Resource,
    *,
    now: datetime | None = None,
) -> str:
    tz = resource.timezone or studio.timezone
    when = format_interval_local(booking.starts_at, booking.ends_at, tz)
    duration = int((booking.ends_at - booking.starts_at).total_seconds() // 60) or 60
    shoot = shoot_minutes(resource, duration)
    buffer = int(resource.buffer_min or 0)
    studio_hour = ""
    if buffer:
        studio_hour = f"\n⏱ Съёмка {shoot} мин + {buffer} мин уборка"
    price_line = ""
    if booking.quoted_price_rub:
        prepay = booking.prepay_amount_rub or booking.quoted_price_rub
        price_line = f"\n💳 {booking.quoted_price_rub} ₽, предоплата {prepay} ₽"
    status_line = ""
    if booking.status == STATUS_HOLD:
        status_line = "\n" + hold_pay_line(booking, now)
    elif booking.status == STATUS_PAID:
        status_line = "\n✅ Оплачено"
    elif booking.status == STATUS_CANCELLED:
        status_line = "\n❌ Отменена"
    return (
        f"🏠 <b>{escape(studio.name)}</b>\n"
        f"🎬 {escape(resource.name)}\n"
        f"🕒 {when}{studio_hour}\n"
        f"👤 {escape(booking.client_name)}\n"
        f"📞 {escape(booking.client_phone or '—')}"
        f"{price_line}"
        f"{status_line}"
    )
