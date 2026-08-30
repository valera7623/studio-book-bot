from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.models.studio import Resource, Studio
from src.database.models.user import User
from src.keyboards.inline import consent_keyboard, date_keyboard, pay_keyboard, slot_keyboard
from src.services import payments as payment_svc
from src.services import prodamus
from src.services.consents import consent_text, record_consent
from src.services.formatters import booking_summary, format_slot_local
from src.services.slots import available_slots, create_hold
from src.services.studios import get_primary_resource, get_studio_by_slug
from src.services.tariffs import can_create_booking
from src.states.booking import BookingStates
from src.utils.validators import validate_name, validate_phone

router = Router()


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
    resource = await get_primary_resource(session, studio.id)
    if resource is None:
        await message.answer("У студии пока нет зала для записи.")
        return True
    ok, reason = await can_create_booking(session, studio)
    if not ok:
        await message.answer(reason)
        return True
    await state.clear()
    await state.update_data(studio_id=studio.id, resource_id=resource.id)
    tz_name = resource.timezone or studio.timezone
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    days = [today + timedelta(days=i) for i in range(7)]
    await message.answer(
        f"📅 <b>{studio.name}</b>\nРесурс: {resource.name}\nВыберите дату:",
        reply_markup=date_keyboard(studio.id, days, tz_name),
    )
    return True


@router.callback_query(F.data.startswith("bk:d:"))
async def cb_pick_date(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    _, _, studio_id_s, day_s = callback.data.split(":", 3)
    studio = await session.get(Studio, int(studio_id_s))
    resource = await get_primary_resource(session, int(studio_id_s)) if studio else None
    if not studio or not resource:
        await callback.answer("Студия недоступна", show_alert=True)
        return
    day = date.fromisoformat(day_s)
    slots = await available_slots(session, resource, day)
    if not slots:
        await callback.answer("На эту дату свободных слотов нет", show_alert=True)
        return
    await state.update_data(studio_id=studio.id, resource_id=resource.id, day=day_s)
    await callback.message.answer(
        f"Слоты на {day.strftime('%d.%m.%Y')}:",
        reply_markup=slot_keyboard(resource.id, slots, resource.timezone),
    )
    await callback.answer()


@router.callback_query(F.data == "bk:back")
async def cb_back_dates(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    studio_id = data.get("studio_id")
    studio = await session.get(Studio, studio_id) if studio_id else None
    resource = await get_primary_resource(session, studio.id) if studio else None
    if not studio or not resource:
        await callback.answer()
        return
    tz_name = resource.timezone
    today = datetime.now(ZoneInfo(tz_name)).date()
    days = [today + timedelta(days=i) for i in range(7)]
    await callback.message.answer(
        "Выберите дату:",
        reply_markup=date_keyboard(studio.id, days, tz_name),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bk:s:"))
async def cb_pick_slot(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    _, _, resource_id_s, ts_s = callback.data.split(":")
    resource = await session.get(Resource, int(resource_id_s))
    if resource is None:
        await callback.answer("Слот недоступен", show_alert=True)
        return
    starts_at = datetime.fromtimestamp(int(ts_s), tz=timezone.utc)
    await state.update_data(
        resource_id=resource.id,
        studio_id=resource.studio_id,
        starts_ts=int(ts_s),
    )
    when = format_slot_local(starts_at, resource.timezone)
    await state.set_state(BookingStates.waiting_name)
    await callback.message.answer(f"Слот {when}. Как вас зовут?")
    await callback.answer()


@router.message(BookingStates.waiting_name)
async def booking_name(message: Message, state: FSMContext):
    ok, value = validate_name(message.text or "")
    if not ok:
        await message.answer(value)
        return
    await state.update_data(client_name=value)
    await state.set_state(BookingStates.waiting_phone)
    await message.answer("Номер телефона (например +79991234567)")


@router.message(BookingStates.waiting_phone)
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
    duration = timedelta(minutes=resource.duration_min or 60)
    await record_consent(session, user, studio_id=studio.id)
    booking = await create_hold(
        session,
        resource=resource,
        starts_at=starts_at,
        ends_at=starts_at + duration,
        client_telegram_id=user.telegram_id,
        client_name=data["client_name"],
        client_phone=data.get("client_phone"),
        client_user_id=user.id,
    )
    await state.clear()
    if booking is None:
        await callback.message.answer("Этот слот только что заняли. Выберите другое время по ссылке записи.")
        await callback.answer()
        return
    summary = booking_summary(booking, studio, resource)
    await callback.message.answer(
        "⏳ Слот удерживается "
        f"{settings.HOLD_TTL_MINUTES} мин.\n\n{summary}"
    )
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
    from src.database.models.booking import STATUS_PAID

    price = resource.price_rub or 0
    if price <= 0:
        booking.status = STATUS_PAID
        booking.hold_expires_at = None
        await session.commit()
        await message.answer("✅ Бронь подтверждена (без предоплаты).")
        await _notify_owner(bot, studio, booking, resource, paid=True)
        return
    if not prodamus.is_configured():
        await message.answer(
            "Предоплата ещё не подключена у студии. Слот в hold: владелец видит бронь "
            "и подтвердит вручную."
        )
        await _notify_owner(bot, studio, booking, resource, paid=False)
        return
    payment = await payment_svc.create_slot_invoice(session, booking, price)
    url = payment_svc.payment_url(
        payment,
        phone=booking.client_phone,
        description=f"{studio.name} / {resource.name} / {format_slot_local(booking.starts_at, resource.timezone)}",
    )
    await message.answer(
        f"К оплате {price} ₽. Чек придёт от платёжной системы (54-ФЗ).\n"
        "После оплаты бронь подтвердится автоматически.",
        reply_markup=pay_keyboard(url),
    )
    await _notify_owner(bot, studio, booking, resource, paid=False)


async def _notify_owner(bot: Bot, studio: Studio, booking, resource: Resource, *, paid: bool) -> None:
    mark = "✅ Оплачена" if paid else "⏳ Hold"
    text = f"{mark}\n" + booking_summary(booking, studio, resource)
    try:
        await bot.send_message(studio.owner_telegram_id, text)
    except Exception:
        pass
