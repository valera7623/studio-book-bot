from __future__ import annotations

from datetime import time

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.models.booking import STATUS_HOLD, STATUS_PAID, Booking
from src.database.models.studio import TARIFF_PLUS, TARIFF_STARTER, Resource, Studio
from src.database.models.user import User
from src.keyboards.inline import (
    owner_cabinet_keyboard,
    pay_keyboard,
    tariff_keyboard,
    bookings_keyboard,
)
from src.services import payments as payment_svc
from src.services import prodamus
from src.services.formatters import format_slot_local
from src.services.ical import build_calendar
from src.services.slots import parse_hours
from src.services.studios import get_owner_studio, get_primary_resource, unique_slug
from src.services.tariffs import can_add_resource, tariff_label
from src.states.booking import OwnerStates
from src.utils.qr_code import generate_booking_qr, resolve_bot_username

router = Router()


async def show_cabinet(message: Message, session: AsyncSession, user: User) -> None:
    studio = await get_owner_studio(session, user)
    if studio is None:
        await message.answer(
            "Студии ещё нет. Нажмите «Создать студию» или /studio.",
        )
        return
    resource = await get_primary_resource(session, studio.id)
    res_name = resource.name if resource else "—"
    hours = "—"
    if resource:
        hours = f"{resource.work_start.strftime('%H:%M')}–{resource.work_end.strftime('%H:%M')}"
    price = resource.price_rub if resource else 0
    text = (
        f"🏠 <b>{studio.name}</b>\n"
        f"slug: <code>{studio.slug}</code>\n"
        f"Тариф: {tariff_label(studio.tariff)}\n"
        f"Ресурс: {res_name}\n"
        f"Часы: {hours}\n"
        f"Цена часа: {price} ₽\n\n"
        "Клиенты записываются по ссылке. Это не CRM."
    )
    await message.answer(text, reply_markup=owner_cabinet_keyboard())


@router.message(Command("studio"))
async def cmd_studio(message: Message, session: AsyncSession, user: User, state: FSMContext):
    await state.clear()
    studio = await get_owner_studio(session, user)
    if studio is None:
        await message.answer("Как называется студия?")
        await state.set_state(OwnerStates.waiting_studio_name)
        return
    await show_cabinet(message, session, user)


@router.callback_query(F.data == "ow:new")
async def cb_new_studio(callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext):
    if await get_owner_studio(session, user):
        await callback.answer("Студия уже создана")
        await show_cabinet(callback.message, session, user)
        return
    await state.set_state(OwnerStates.waiting_studio_name)
    await callback.message.answer("Как называется студия?")
    await callback.answer()


@router.callback_query(F.data == "ow:cab")
async def cb_cabinet(callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext):
    await state.clear()
    await show_cabinet(callback.message, session, user)
    await callback.answer()


@router.message(OwnerStates.waiting_studio_name)
async def owner_studio_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Название слишком короткое.")
        return
    await state.update_data(studio_name=name)
    await state.set_state(OwnerStates.waiting_resource_name)
    await message.answer("Название зала / ресурса? Например: Циклорама. Или «Зал».")


@router.message(OwnerStates.waiting_resource_name)
async def owner_resource_name(message: Message, state: FSMContext):
    name = (message.text or "").strip() or "Зал"
    await state.update_data(resource_name=name)
    await state.set_state(OwnerStates.waiting_hours)
    await message.answer("Часы работы в будни, например: 10:00 22:00")


@router.message(OwnerStates.waiting_hours)
async def owner_hours(message: Message, state: FSMContext):
    parsed = parse_hours(message.text or "")
    if parsed is None:
        await message.answer("Формат: 10:00 22:00")
        return
    start, end = parsed
    await state.update_data(work_start=start.isoformat(), work_end=end.isoformat())
    await state.set_state(OwnerStates.waiting_price)
    await message.answer("Цена часа в рублях (число). 0 — пока без предоплаты.")


@router.message(OwnerStates.waiting_price)
async def owner_price(
    message: Message,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    bot: Bot,
):
    raw = (message.text or "").strip().replace(" ", "")
    if not raw.isdigit():
        await message.answer("Введите целое число рублей.")
        return
    price = int(raw)
    data = await state.get_data()
    slug = await unique_slug(session, data["studio_name"])
    studio = Studio(
        slug=slug,
        name=data["studio_name"],
        owner_id=user.id,
        owner_telegram_id=user.telegram_id,
        timezone="Europe/Moscow",
        resource_limit=1,
    )
    session.add(studio)
    await session.flush()
    start = time.fromisoformat(data["work_start"])
    end = time.fromisoformat(data["work_end"])
    resource = Resource(
        studio_id=studio.id,
        name=data["resource_name"],
        duration_min=60,
        timezone="Europe/Moscow",
        work_start=start,
        work_end=end,
        price_rub=price,
    )
    session.add(resource)
    await session.commit()
    await state.clear()
    await message.answer("Студия создана. Free: 1 ресурс, 30 записей в месяц.")
    await _send_booking_link(message, bot, studio)
    await show_cabinet(message, session, user)


async def _send_booking_link(message: Message, bot: Bot, studio: Studio) -> None:
    username = await resolve_bot_username(bot, settings.BOT_USERNAME)
    deep_link, png = generate_booking_qr(username, studio.slug)
    photo = BufferedInputFile(png, filename=f"{studio.slug}.png")
    await message.answer_photo(
        photo,
        caption=(
            f"Ссылка записи для клиентов:\n<code>{deep_link}</code>\n\n"
            "Отправьте её в чат студии или напечатайте QR."
        ),
    )


@router.callback_query(F.data == "ow:link")
async def cb_link(callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot):
    studio = await get_owner_studio(session, user)
    if not studio:
        await callback.answer("Нет студии", show_alert=True)
        return
    await _send_booking_link(callback.message, bot, studio)
    await callback.answer()


@router.callback_query(F.data == "ow:hr")
async def cb_hours(callback: CallbackQuery, state: FSMContext):
    await state.set_state(OwnerStates.waiting_hours_edit)
    await callback.message.answer("Новые часы, например 10:00 22:00")
    await callback.answer()


@router.message(OwnerStates.waiting_hours_edit)
async def owner_hours_edit(message: Message, session: AsyncSession, user: User, state: FSMContext):
    parsed = parse_hours(message.text or "")
    if parsed is None:
        await message.answer("Формат: 10:00 22:00")
        return
    studio = await get_owner_studio(session, user)
    resource = await get_primary_resource(session, studio.id) if studio else None
    if not resource:
        await message.answer("Ресурс не найден.")
        await state.clear()
        return
    resource.work_start, resource.work_end = parsed
    await session.commit()
    await state.clear()
    await message.answer("Часы обновлены.")
    await show_cabinet(message, session, user)


@router.callback_query(F.data == "ow:price")
async def cb_price(callback: CallbackQuery, state: FSMContext):
    await state.set_state(OwnerStates.waiting_price_edit)
    await callback.message.answer("Новая цена часа в рублях")
    await callback.answer()


@router.message(OwnerStates.waiting_price_edit)
async def owner_price_edit(message: Message, session: AsyncSession, user: User, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Введите число.")
        return
    studio = await get_owner_studio(session, user)
    resource = await get_primary_resource(session, studio.id) if studio else None
    if not resource:
        await message.answer("Ресурс не найден.")
        await state.clear()
        return
    resource.price_rub = int(raw)
    await session.commit()
    await state.clear()
    await message.answer("Цена обновлена.")
    await show_cabinet(message, session, user)


@router.callback_query(F.data == "ow:book")
async def cb_bookings(callback: CallbackQuery, session: AsyncSession, user: User):
    studio = await get_owner_studio(session, user)
    if not studio:
        await callback.answer("Нет студии", show_alert=True)
        return
    stmt = (
        select(Booking)
        .where(
            Booking.studio_id == studio.id,
            Booking.status.in_((STATUS_HOLD, STATUS_PAID)),
        )
        .order_by(Booking.starts_at.asc())
        .limit(20)
    )
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        await callback.message.answer("Активных броней нет.", reply_markup=owner_cabinet_keyboard())
        await callback.answer()
        return
    resource = await get_primary_resource(session, studio.id)
    tz = resource.timezone if resource else studio.timezone
    lines = ["📋 <b>Брони</b>\n"]
    buttons: list[tuple[int, str]] = []
    for booking in rows:
        when = format_slot_local(booking.starts_at, tz)
        mark = "⏳" if booking.status == STATUS_HOLD else "✅"
        lines.append(f"{mark} {when} — {booking.client_name} ({booking.client_phone or '—'})")
        buttons.append((booking.id, when))
    await callback.message.answer("\n".join(lines), reply_markup=bookings_keyboard(buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("ow:c:"))
async def cb_cancel_booking(callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot):
    studio = await get_owner_studio(session, user)
    booking_id = int(callback.data.split(":")[2])
    booking = await session.get(Booking, booking_id)
    if not studio or not booking or booking.studio_id != studio.id:
        await callback.answer("Не найдено", show_alert=True)
        return
    if booking.status == "cancelled":
        await callback.answer("Уже отменена")
        return
    booking.status = "cancelled"
    booking.cancel_reason = "owner"
    await session.commit()
    await callback.message.answer("Бронь отменена, слот свободен.")
    try:
        await bot.send_message(
            booking.client_telegram_id,
            "Владелец студии отменил вашу бронь. Выберите другой слот по ссылке записи.",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "ow:res")
async def cb_add_resource(callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext):
    studio = await get_owner_studio(session, user)
    if not studio:
        await callback.answer("Нет студии", show_alert=True)
        return
    ok, reason = await can_add_resource(session, studio)
    if not ok:
        await callback.message.answer(reason, reply_markup=tariff_keyboard())
        await callback.answer()
        return
    await state.set_state(OwnerStates.waiting_extra_resource)
    await callback.message.answer("Название второго ресурса?")
    await callback.answer()


@router.message(OwnerStates.waiting_extra_resource)
async def owner_extra_resource(message: Message, session: AsyncSession, user: User, state: FSMContext):
    studio = await get_owner_studio(session, user)
    if not studio:
        await state.clear()
        return
    ok, reason = await can_add_resource(session, studio)
    if not ok:
        await message.answer(reason, reply_markup=tariff_keyboard())
        await state.clear()
        return
    primary = await get_primary_resource(session, studio.id)
    name = (message.text or "").strip() or "Зал 2"
    resource = Resource(
        studio_id=studio.id,
        name=name,
        duration_min=primary.duration_min if primary else 60,
        timezone=studio.timezone,
        work_start=primary.work_start if primary else time(10, 0),
        work_end=primary.work_end if primary else time(22, 0),
        price_rub=primary.price_rub if primary else 0,
    )
    session.add(resource)
    await session.commit()
    await state.clear()
    await message.answer(f"Ресурс «{name}» добавлен.")
    await show_cabinet(message, session, user)


@router.callback_query(F.data == "ow:tariff")
async def cb_tariff(callback: CallbackQuery, session: AsyncSession, user: User):
    studio = await get_owner_studio(session, user)
    if not studio:
        await callback.answer("Нет студии", show_alert=True)
        return
    until = studio.subscription_until.strftime("%d.%m.%Y") if studio.subscription_until else "—"
    text = (
        f"Текущий тариф: <b>{tariff_label(studio.tariff)}</b>\n"
        f"Оплачен до: {until}\n\n"
        f"Free — 1 ресурс, {settings.FREE_BOOKINGS_PER_MONTH} записей/мес.\n"
        f"Старт {settings.TARIFF_STARTER_RUB} ₽ — 1 ресурс, без лимита записей.\n"
        f"Плюс {settings.TARIFF_PLUS_RUB} ₽ — 2 ресурса.\n\n"
        "Оплата подписки — Prodamus (чек 54-ФЗ)."
    )
    await callback.message.answer(text, reply_markup=tariff_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("ow:pay:"))
async def cb_pay_tariff(callback: CallbackQuery, session: AsyncSession, user: User):
    studio = await get_owner_studio(session, user)
    if not studio:
        await callback.answer("Нет студии", show_alert=True)
        return
    kind = callback.data.split(":")[2]
    if kind == "plus":
        tariff, amount = TARIFF_PLUS, settings.TARIFF_PLUS_RUB
    else:
        tariff, amount = TARIFF_STARTER, settings.TARIFF_STARTER_RUB
    if not prodamus.is_configured():
        await callback.message.answer(
            "Prodamus ещё не настроен (PRODAMUS_PAYFORM_URL / SECRET в .env на VPS). "
            "Тариф в коде заложен, оплату включим после ключей."
        )
        await callback.answer()
        return
    payment = await payment_svc.create_subscription_invoice(
        session, studio, tariff=tariff, amount_rub=amount
    )
    url = payment_svc.payment_url(
        payment,
        description=f"Подписка studio-book {tariff} {studio.slug}",
    )
    await callback.message.answer(
        f"Счёт на {amount} ₽. После оплаты тариф обновится автоматически.",
        reply_markup=pay_keyboard(url),
    )
    await callback.answer()


@router.callback_query(F.data == "ow:ical")
async def cb_ical(callback: CallbackQuery, session: AsyncSession, user: User):
    studio = await get_owner_studio(session, user)
    if not studio:
        await callback.answer("Нет студии", show_alert=True)
        return
    resource = await get_primary_resource(session, studio.id)
    stmt = select(Booking).where(
        Booking.studio_id == studio.id,
        Booking.status == STATUS_PAID,
    )
    rows = (await session.execute(stmt)).scalars().all()
    if resource is None:
        await callback.message.answer("Нет ресурса для календаря.")
        await callback.answer()
        return
    ics = build_calendar(studio, resource, list(rows))
    document = BufferedInputFile(ics.encode("utf-8"), filename=f"{studio.slug}.ics")
    caption = "Импортируйте файл в Google Calendar."
    if settings.PUBLIC_BASE_URL.strip() and resource:
        url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/ical/{studio.slug}.ics"
        caption += f"\nПодписка: {url}"
    await callback.message.answer_document(document, caption=caption)
    await callback.answer()
