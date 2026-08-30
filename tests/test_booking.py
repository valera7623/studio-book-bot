from datetime import date, datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo

from src.database.models.booking import STATUS_CANCELLED, STATUS_HOLD, STATUS_PAID, Booking
from src.database.models.payment import PAYMENT_PAID
from src.database.models.studio import TARIFF_FREE, TARIFF_STARTER, Resource, Studio
from src.database.models.user import User
from src.services.payments import apply_paid_order, create_slot_invoice
from src.services.prodamus import sign_payload, verify_signature
from src.services.slots import available_slots, create_hold, expire_holds, generate_slots_for_day
from src.services.tariffs import can_create_booking
from src.utils.slug import slugify


def _slot_start() -> datetime:
    return datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


async def _seed_resource(session, *, slug="demo-studio", telegram_id=1001) -> Resource:
    owner = User(
        telegram_id=telegram_id,
        username="owner",
        first_name="Анна",
        language_code="ru",
    )
    session.add(owner)
    await session.flush()

    studio = Studio(
        slug=slug,
        name="Демо студия",
        owner_id=owner.id,
        owner_telegram_id=owner.telegram_id,
        timezone="Europe/Moscow",
    )
    session.add(studio)
    await session.flush()

    resource = Resource(
        studio_id=studio.id,
        name="Циклорама",
        duration_min=60,
        timezone="Europe/Moscow",
        work_start=time(10, 0),
        work_end=time(12, 0),
        weekdays="1,2,3,4,5,6,7",
        price_rub=1000,
    )
    session.add(resource)
    await session.flush()
    return resource


async def test_two_active_holds_same_slot_rejected(session):
    resource = await _seed_resource(session)
    start = _slot_start()
    end = start + timedelta(hours=1)

    first = await create_hold(
        session,
        resource=resource,
        starts_at=start,
        ends_at=end,
        client_telegram_id=2001,
        client_name="Клиент А",
        client_phone="+79990000001",
        client_user_id=None,
    )
    assert first is not None

    second = await create_hold(
        session,
        resource=resource,
        starts_at=start,
        ends_at=end,
        client_telegram_id=2002,
        client_name="Клиент Б",
        client_phone="+79990000002",
        client_user_id=None,
    )
    assert second is None


async def test_cancelled_slot_can_be_rebooked(session):
    resource = await _seed_resource(session)
    start = _slot_start()
    end = start + timedelta(hours=1)

    first = Booking(
        resource_id=resource.id,
        studio_id=resource.studio_id,
        client_telegram_id=2001,
        client_name="Клиент А",
        starts_at=start,
        ends_at=end,
        status=STATUS_CANCELLED,
    )
    session.add(first)
    await session.commit()

    second = await create_hold(
        session,
        resource=resource,
        starts_at=start,
        ends_at=end,
        client_telegram_id=2002,
        client_name="Клиент Б",
        client_phone=None,
        client_user_id=None,
    )
    assert second is not None


async def test_hold_ttl_expires(session):
    resource = await _seed_resource(session)
    start = _slot_start()
    booking = Booking(
        resource_id=resource.id,
        studio_id=resource.studio_id,
        client_telegram_id=2001,
        client_name="Клиент А",
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        status=STATUS_HOLD,
        hold_expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    session.add(booking)
    await session.commit()
    n = await expire_holds(session)
    assert n == 1
    await session.refresh(booking)
    assert booking.status == STATUS_CANCELLED
    again = await create_hold(
        session,
        resource=resource,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        client_telegram_id=2003,
        client_name="Другой",
        client_phone=None,
        client_user_id=None,
    )
    assert again is not None


async def test_generate_hourly_slots_moscow():
    resource = Resource(
        studio_id=1,
        name="Зал",
        duration_min=60,
        timezone="Europe/Moscow",
        work_start=time(10, 0),
        work_end=time(12, 0),
        weekdays="1,2,3,4,5,6,7",
    )
    day = date(2026, 9, 1)
    slots = generate_slots_for_day(resource, day)
    assert len(slots) == 2
    local0 = slots[0].starts_at.astimezone(ZoneInfo("Europe/Moscow"))
    assert local0.hour == 10


async def test_available_slots_skip_hold(session):
    resource = await _seed_resource(session)
    day = date(2026, 9, 2)
    tz = ZoneInfo("Europe/Moscow")
    start_local = datetime(2026, 9, 2, 10, 0, tzinfo=tz)
    await create_hold(
        session,
        resource=resource,
        starts_at=start_local,
        ends_at=start_local + timedelta(hours=1),
        client_telegram_id=1,
        client_name="A",
        client_phone=None,
        client_user_id=None,
    )
    free = await available_slots(session, resource, day)
    hours = {s.starts_at.astimezone(tz).hour for s in free}
    assert 10 not in hours
    assert 11 in hours


async def test_free_monthly_limit(session):
    resource = await _seed_resource(session)
    studio = await session.get(Studio, resource.studio_id)
    studio.tariff = TARIFF_FREE
    for i in range(30):
        session.add(
            Booking(
                resource_id=resource.id,
                studio_id=studio.id,
                client_telegram_id=3000 + i,
                client_name="x",
                starts_at=_slot_start() + timedelta(days=i),
                ends_at=_slot_start() + timedelta(days=i, hours=1),
                status=STATUS_PAID,
            )
        )
    await session.commit()
    ok, reason = await can_create_booking(session, studio)
    assert ok is False
    assert "лимит" in reason.lower()
    studio.tariff = TARIFF_STARTER
    ok, _ = await can_create_booking(session, studio)
    assert ok is True


async def test_webhook_idempotent(session):
    resource = await _seed_resource(session, slug="pay-studio", telegram_id=5001)
    booking = await create_hold(
        session,
        resource=resource,
        starts_at=_slot_start(),
        ends_at=_slot_start() + timedelta(hours=1),
        client_telegram_id=9,
        client_name="Клиент",
        client_phone="+79991112233",
        client_user_id=None,
    )
    payment = await create_slot_invoice(session, booking, 1000)
    order_id = payment.prodamus_invoice_id
    first = await apply_paid_order(session, order_id)
    second = await apply_paid_order(session, order_id)
    assert first.status == PAYMENT_PAID
    assert second.id == first.id
    await session.refresh(booking)
    assert booking.status == STATUS_PAID


async def test_prodamus_signature_roundtrip():
    secret = "test-secret"
    data = {"order_id": "slot-1-2", "sum": "1000"}
    sig = sign_payload(data, secret)
    assert verify_signature(data, sig, secret)
    assert not verify_signature(data, "deadbeef", secret)


def test_slugify_russian():
    assert slugify("Циклорама Свет") == "ciklorama-svet"
