from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.booking import STATUS_HOLD, STATUS_PAID, Booking
from src.database.models.studio import Resource, Studio
from src.database.models.user import User
from src.keyboards.inline import (
    client_booking_keyboard,
    consent_keyboard,
    date_keyboard,
    duration_keyboard,
    pay_keyboard,
    resource_keyboard,
    slot_keyboard,
)
from src.services import payments as payment_svc
from src.services import prodamus
from src.services.cancellations import cancel_booking, cancel_rules_text
from src.services.consents import consent_text, record_consent
from src.services.formatters import booking_summary, format_interval_local
from src.services.slots import (
    allowed_durations,
    available_slots,
    clamp_hold_ttl,
    create_hold,
    generate_slots_for_day,
    prepay_amount_rub,
    quote_price_rub,
    shoot_minutes,
)
from src.services.studios import get_primary_resource, get_studio_by_slug, list_active_resources
from src.services.tariffs import can_create_booking
from src.states.booking import BookingStates
from src.utils.validators import validate_name, validate_phone

router = Router()
_NOT_COMMAND = F.text & ~F.text.startswith("/")


def _days_ahead(tz_name: str, n: int = 7) -> list[date]:
    today = datetime.now(ZoneInfo(tz_name)).date()
    return [today + timedelta(days=i) for i in range(n)]


async def _ask_dates(message: Message, studio: Studio, resource: Resource) -> None:
    tz_name = resource.timezone or studio.timezone
    await message.answer(
        f"📅 <b>{studio.name}</b>\nЗал: {resource.name}\nВыберите дату:",
        reply_markup=date_keyboard(resource.id, _days_ahead(tz_name), tz_name),
    )


async def start_public_booking(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    payload: str,
) -> bool:
    slug = payload
    if payload.startswith("book_"):
        slug = payload[5:]
    studio = await get_studio_by_slug(session, slug)
    if studio is None:
        return False
    resources = await list_active_resources(session, studio.id)
    if not resources:
        await message.answer("У студии пока нет зала для записи.")
        return True
    ok, reason = await can_create_booking(session, studio)
    if not ok:
        await message.answer(reason)
        return True
    await state.clear()
    await state.update_data(studio_id=studio.id)
    if len(resources) == 1:
        resource = resources[0]
        await state.update_data(resource_id=resource.id)
        await _ask_dates(message, studio, resource)
        return True
    await message.answer(
        f"📅 <b>{studio.name}</b>\nВыберите зал:",
        reply_markup=resource_keyboard(studio.id, resources),
    )
    return True


@router.callback_query(F.data.startswith("bk:r:"))
async def cb_pick_resource(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    _, _, studio_id_s, resource_id_s = callback.data.split(":")
    studio = await session.get(Studio, int(studio_id_s))
    resource = await session.get(Resource, int(resource_id_s))
    if not studio or not resource or resource.studio_id != studio.id:
        await callback.answer("Зал недоступен", show_alert=True)
        return
    await state.update_data(studio_id=studio.id, resource_id=resource.id)
    await _ask_dates(callback.message, studio, resource)
    await callback.answer()


@router.callback_query(F.data.startswith("bk:d:"))
async def cb_pick_date(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    _, _, resource_id_s, day_s = callback.data.split(":", 3)
    resource = await session.get(Resource, int(resource_id_s))
    studio = await session.get(Studio, resource.studio_id) if resource else None
    if not studio or not resource:
        await callback.answer("Студия недоступна", show_alert=True)
        return
    day = date.fromisoformat(day_s)
    await state.update_data(studio_id=studio.id, resource_id=resource.id, day=day_s)
    durations = allowed_durations(resource)
    sample_slots = generate_slots_for_day(resource, day, durations[0])
    if not sample_slots:
        await callback.answer("На эту дату слотов нет", show_alert=True)
        return
    sample_start = sample_slots[0].starts_at
    if len(durations) == 1:
        await _show_slots(callback.message, session, resource, day, durations[0])
        await callback.answer()
        return
    await callback.message.answer(
        f"Длительность на {day.strftime('%d.%m.%Y')} "
        f"(* — час с наценкой, если минимум 2 ч):",
        reply_markup=duration_keyboard(resource, day_s, sample_start),
    )
    await callback.answer()


async def _show_slots(message: Message, session: AsyncSession, resource: Resource, day, duration_min: int) -> None:
    slots = await available_slots(session, resource, day, duration_min)
    if not slots:
        await message.answer("На эту дату свободных слотов нет.")
        return
    shoot = shoot_minutes(resource, duration_min)
    buffer = int(resource.buffer_min or 0)
    hint = f"{duration_min} мин"
    if buffer:
        hint = f"{shoot} мин съёмки + {buffer} мин уборка"
    await message.answer(
        f"Слоты на {day.strftime('%d.%m.%Y')} ({hint}):",
        reply_markup=slot_keyboard(resource.id, slots, resource.timezone, duration_min),
    )


@router.callback_query(F.data.startswith("bk:n:"))
async def cb_pick_duration(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    _, _, resource_id_s, day_s, dur_s = callback.data.split(":")
    resource = await session.get(Resource, int(resource_id_s))
    if resource is None:
        await callback.answer("Слот недоступен", show_alert=True)
        return
    day = date.fromisoformat(day_s)
    duration_min = int(dur_s)
    await state.update_data(resource_id=resource.id, studio_id=resource.studio_id, day=day_s, duration_min=duration_min)
    slots = await available_slots(session, resource, day, duration_min)
    if not slots:
        await callback.answer("На эту длительность свободных слотов нет", show_alert=True)
        return
    await _show_slots(callback.message, session, resource, day, duration_min)
    await callback.answer()


@router.callback_query(F.data == "bk:back")
async def cb_back_dates(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    resource = await session.get(Resource, data["resource_id"]) if data.get("resource_id") else None
    studio = await session.get(Studio, data["studio_id"]) if data.get("studio_id") else None
    if not studio or not resource:
        await callback.answer()
        return
    await _ask_dates(callback.message, studio, resource)
    await callback.answer()


@router.callback_query(F.data.startswith("bk:s:"))
async def cb_pick_slot(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    parts = callback.data.split(":")
    resource_id_s, ts_s = parts[2], parts[3]
    duration_min = int(parts[4]) if len(parts) > 4 else 0
    resource = await session.get(Resource, int(resource_id_s))
    if resource is None:
        await callback.answer("Слот недоступен", show_alert=True)
        return
    if not duration_min:
        duration_min = resource.duration_min or 60
    starts_at = datetime.fromtimestamp(int(ts_s), tz=timezone.utc)
    await state.update_data(
        resource_id=resource.id,
        studio_id=resource.studio_id,
        starts_ts=int(ts_s),
        duration_min=duration_min,
    )
    when = format_interval_local(starts_at, starts_at + timedelta(minutes=duration_min), resource.timezone)
    price = quote_price_rub(resource, starts_at, duration_min)
    extra = f" ({price} ₽)" if price else ""
    await state.set_state(BookingStates.waiting_name)
    await callback.message.answer(f"Слот {when}{extra}. Как вас зовут?")
    await callback.answer()


@router.message(BookingStates.waiting_name, _NOT_COMMAND)
async def booking_name(message: Message, state: FSMContext):
    ok, value = validate_name(message.text or "")
    if not ok:
        await message.answer(value)
        return
    await state.update_data(client_name=value)
    await state.set_state(BookingStates.waiting_phone)
    await message.answer("Номер телефона (например +79991234567)")


@router.message(BookingStates.waiting_phone, _NOT_COMMAND)
async def booking_phone(message: Message, state: FSMContext):
    ok, value = validate_phone(message.text or "")
    if not ok:
        await message.answer(value)
        return
    await state.update_data(client_phone=value)
    await state.set_state(BookingStates.waiting_consent)
    await message.answer(consent_text(), reply_markup=consent_keyboard())


@router.callback_query(F.data == "bk:cancel")
async def cb_booking_abort(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Запись отменена.")
    await callback.answer()


@router.callback_query(F.data == "bk:consent", BookingStates.waiting_consent)
async def cb_consent(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    bot: Bot,
):
    data = await state.get_data()
    resource = await session.get(Resource, data.get("resource_id"))
    studio = await session.get(Studio, data.get("studio_id")) if data.get("studio_id") else None
    if not resource or not studio:
        await state.clear()
        await callback.answer("Сессия устарела", show_alert=True)
        return
    ok, reason = await can_create_booking(session, studio)
    if not ok:
        await callback.message.answer(reason)
        await state.clear()
        await callback.answer()
        return
    starts_at = datetime.fromtimestamp(int(data["starts_ts"]), tz=timezone.utc)
    duration_min = int(data.get("duration_min") or resource.duration_min or 60)
    ends_at = starts_at + timedelta(minutes=duration_min)
    price = quote_price_rub(resource, starts_at, duration_min)
    prepay = prepay_amount_rub(studio, price)
    await record_consent(session, user, studio_id=studio.id)
    booking = await create_hold(
        session,
        resource=resource,
        starts_at=starts_at,
        ends_at=ends_at,
        client_telegram_id=user.telegram_id,
        client_name=data["client_name"],
        client_phone=data.get("client_phone"),
        client_user_id=user.id,
        quoted_price_rub=price,
        prepay_amount_rub=prepay,
        studio=studio,
    )
    await state.clear()
    if booking is None:
        await callback.message.answer("Этот слот только что заняли. Выберите другое время по ссылке записи.")
        await callback.answer()
        return
    ttl = clamp_hold_ttl(studio.hold_ttl_minutes)
    summary = booking_summary(booking, studio, resource)
    await callback.message.answer(f"⏳ Слот удерживается {ttl} мин.\n\n{summary}")
    await _offer_payment_or_confirm(callback.message, session, bot, booking, studio, resource)
    await callback.answer()


async def _offer_payment_or_confirm(
    message: Message,
    session: AsyncSession,
    bot: Bot,
    booking,
    studio: Studio,
    resource: Resource,
) -> None:
    price = booking.quoted_price_rub or resource.price_rub or 0
    prepay = booking.prepay_amount_rub if booking.prepay_amount_rub else prepay_amount_rub(studio, price)
    if prepay <= 0:
        booking.status = STATUS_PAID
        booking.hold_expires_at = None
        await session.commit()
        await message.answer(
            "✅ Бронь подтверждена (без предоплаты).",
            reply_markup=client_booking_keyboard(booking.id),
        )
        await _notify_owner(bot, studio, booking, resource, paid=True)
        return
    if not prodamus.is_configured():
        await message.answer(
            "Предоплата ещё не подключена у студии. Слот в hold: владелец видит бронь "
            "и подтвердит вручную.",
            reply_markup=client_booking_keyboard(booking.id),
        )
        await _notify_owner(bot, studio, booking, resource, paid=False)
        return
    payment = await payment_svc.create_slot_invoice(session, booking, prepay)
    url = payment_svc.payment_url(
        payment,
        phone=booking.client_phone,
        description=f"{studio.name} / {resource.name} / {format_interval_local(booking.starts_at, booking.ends_at, resource.timezone)}",
    )
    pct = studio.prepay_percent or 100
    await message.answer(
        f"К оплате {prepay} ₽ ({pct}% от {price} ₽). Чек придёт от платёжной системы (54-ФЗ).\n"
        "После оплаты бронь подтвердится автоматически.",
        reply_markup=pay_keyboard(url, booking.id),
    )
    await _notify_owner(bot, studio, booking, resource, paid=False)


async def _notify_owner(bot: Bot, studio: Studio, booking, resource: Resource, *, paid: bool) -> None:
    mark = "✅ Оплачена" if paid else "⏳ Hold"
    text = f"{mark}\n" + booking_summary(booking, studio, resource)
    try:
        await bot.send_message(studio.owner_telegram_id, text)
    except Exception:
        pass


@router.message(Command("my"))
async def cmd_my(message: Message, session: AsyncSession, user: User):
    stmt = (
        select(Booking)
        .where(
            Booking.client_telegram_id == user.telegram_id,
            Booking.status.in_((STATUS_HOLD, STATUS_PAID)),
        )
        .order_by(Booking.starts_at.asc())
        .limit(10)
    )
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        await message.answer("Активных броней нет.")
        return
    for booking in rows:
        studio = await session.get(Studio, booking.studio_id)
        resource = await session.get(Resource, booking.resource_id)
        if not studio or not resource:
            continue
        await message.answer(
            booking_summary(booking, studio, resource),
            reply_markup=client_booking_keyboard(booking.id),
        )


@router.callback_query(F.data.startswith("bk:cx:"))
async def cb_client_cancel(callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot):
    booking_id = int(callback.data.split(":")[2])
    booking = await session.get(Booking, booking_id)
    if not booking or booking.client_telegram_id != user.telegram_id:
        await callback.answer("Не найдено", show_alert=True)
        return
    studio = await session.get(Studio, booking.studio_id)
    resource = await session.get(Resource, booking.resource_id)
    if not studio:
        await callback.answer("Студия недоступна", show_alert=True)
        return
    result = await cancel_booking(session, booking, studio, by="client")
    await callback.message.answer(result.message)
    if result.ok and studio.owner_telegram_id:
        try:
            extra = booking_summary(booking, studio, resource) if resource else ""
            await bot.send_message(studio.owner_telegram_id, f"Клиент отменил бронь.\n{extra}")
        except Exception:
            pass
    await callback.answer()


@router.message(Command("rules"))
async def cmd_rules(message: Message):
    await message.answer(cancel_rules_text()[:3500])
