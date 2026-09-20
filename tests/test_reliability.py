import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.database import get_session_maker
from src.database.models.booking import STATUS_CANCELLED, STATUS_HOLD, STATUS_PAID, Booking
from src.database.models.payment import (
    KIND_SLOT_PREPAY,
    PAYMENT_PENDING,
    PAYMENT_REFUND_PENDING,
    PAYMENT_REFUNDED,
    Payment,
)
from src.database.models.studio import Resource, Studio
from src.services.ical import feed_token, feed_token_ok
from src.services.payments import (
    amount_matches,
    apply_paid_order,
    apply_refund,
    create_slot_invoice,
    find_payment_for_webhook,
)
from src.services.slots import create_hold, expire_holds
from tests.test_booking import _seed_resource, _slot_start


async def test_invoice_reused_for_same_booking(session):
    resource = await _seed_resource(session, slug="reuse-inv", telegram_id=12001)
    booking = await create_hold(
        session,
        resource=resource,
        starts_at=_slot_start(),
        ends_at=_slot_start() + timedelta(hours=1),
        client_telegram_id=9,
        client_name="Клиент",
        client_phone=None,
        client_user_id=None,
    )
    first = await create_slot_invoice(session, booking, 1000)
    second = await create_slot_invoice(session, booking, 1000)
    assert first.id == second.id
    assert first.prodamus_invoice_id == second.prodamus_invoice_id


async def test_webhook_does_not_guess_unique_hold(session):
    resource = await _seed_resource(session, slug="two-holds", telegram_id=12002)
    a = await create_hold(
        session,
        resource=resource,
        starts_at=_slot_start(),
        ends_at=_slot_start() + timedelta(hours=1),
        client_telegram_id=1,
        client_name="A",
        client_phone=None,
        client_user_id=None,
    )
    b = await create_hold(
        session,
        resource=resource,
        starts_at=_slot_start() + timedelta(hours=1),
        ends_at=_slot_start() + timedelta(hours=2),
        client_telegram_id=2,
        client_name="B",
        client_phone=None,
        client_user_id=None,
    )
    await create_slot_invoice(session, a, 500)
    await create_slot_invoice(session, b, 500)
    found = await find_payment_for_webhook(session, {"order_id": "unknown-uuid", "sum": "500"})
    assert found is None


async def test_paid_after_expire_restores_free_slot(session):
    resource = await _seed_resource(session, slug="late-ok", telegram_id=12003)
    booking = await create_hold(
        session,
        resource=resource,
        starts_at=_slot_start(),
        ends_at=_slot_start() + timedelta(hours=1),
        client_telegram_id=9,
        client_name="Клиент",
        client_phone=None,
        client_user_id=None,
    )
    payment = await create_slot_invoice(session, booking, 1000)
    booking.hold_expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    await session.commit()
    expired = await expire_holds(session)
    assert len(expired) == 1
    await session.refresh(booking)
    assert booking.status == STATUS_CANCELLED
    paid = await apply_paid_order(session, payment.prodamus_invoice_id)
    await session.refresh(booking)
    await session.refresh(paid)
    assert paid.status == "paid"
    assert booking.status == STATUS_PAID


async def test_paid_after_expire_refunds_if_taken(session):
    resource = await _seed_resource(session, slug="late-taken", telegram_id=12004)
    start = _slot_start()
    booking = await create_hold(
        session,
        resource=resource,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        client_telegram_id=9,
        client_name="Клиент",
        client_phone=None,
        client_user_id=None,
    )
    payment = await create_slot_invoice(session, booking, 1000)
    booking.hold_expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    await session.commit()
    await expire_holds(session)
    other = await create_hold(
        session,
        resource=resource,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        client_telegram_id=8,
        client_name="Другой",
        client_phone=None,
        client_user_id=None,
    )
    assert other is not None
    paid = await apply_paid_order(session, payment.prodamus_invoice_id)
    await session.refresh(booking)
    await session.refresh(paid)
    assert paid.status == PAYMENT_REFUNDED
    assert booking.status == STATUS_CANCELLED


async def test_refund_pending_when_remote_fails(session, monkeypatch):
    from src.services import cancellations as cancel_mod
    from src.services.cancellations import cancel_booking

    resource = await _seed_resource(session, slug="ref-fail", telegram_id=12005)
    studio = await session.get(Studio, resource.studio_id)
    start = datetime.now(timezone.utc) + timedelta(days=5)
    booking = await create_hold(
        session,
        resource=resource,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        client_telegram_id=9,
        client_name="Клиент",
        client_phone=None,
        client_user_id=None,
        quoted_price_rub=1000,
        prepay_amount_rub=1000,
        studio=studio,
    )
    payment = await create_slot_invoice(session, booking, 1000)
    await apply_paid_order(session, payment.prodamus_invoice_id)
    await session.refresh(booking)

    async def _fail(*_args, **_kwargs):
        return False, "http_500"

    monkeypatch.setattr(cancel_mod.yookassa, "request_refund", _fail)
    monkeypatch.setattr(cancel_mod.prodamus, "request_refund", _fail)
    result = await cancel_booking(session, booking, studio, by="client")
    assert result.ok
    await session.refresh(payment)
    assert payment.status == PAYMENT_REFUND_PENDING


async def test_amount_matches():
    payment = Payment(kind=KIND_SLOT_PREPAY, amount_rub=490, status=PAYMENT_PENDING)
    assert amount_matches(payment, 490, required=True)
    assert not amount_matches(payment, 100, required=True)
    assert not amount_matches(payment, None, required=True)
    assert amount_matches(payment, None, required=False)


async def test_parallel_overlap_one_wins(engine):
    maker = get_session_maker(engine)
    async with maker() as session:
        resource = await _seed_resource(session, slug="par-ov", telegram_id=12006)
        resource_id = resource.id
        await session.commit()

    start = datetime(2026, 9, 1, 10, 0, tzinfo=ZoneInfo("Europe/Moscow")).astimezone(timezone.utc)

    async def _hold(telegram_id: int, hours: int):
        async with maker() as sess:
            resource = await sess.get(Resource, resource_id)
            assert resource is not None
            return await create_hold(
                sess,
                resource=resource,
                starts_at=start,
                ends_at=start + timedelta(hours=hours),
                client_telegram_id=telegram_id,
                client_name=str(telegram_id),
                client_phone=None,
                client_user_id=None,
            )

    first, second = await asyncio.gather(_hold(1, 2), _hold(2, 1))
    winners = [item for item in (first, second) if item is not None]
    assert len(winners) == 1


def test_ical_token_roundtrip():
    token = feed_token("demo-studio")
    assert feed_token_ok("demo-studio", token)
    assert not feed_token_ok("demo-studio", "deadbeef")
    assert not feed_token_ok("other", token)


def test_booking_summary_hold_status():
    from src.database.models.studio import Studio
    from src.services.formatters import booking_summary, format_day_label

    day = date(2026, 9, 21)
    assert "пн" in format_day_label(day)
    studio = Studio(slug="x", name="Студия", owner_id=1, owner_telegram_id=1)
    resource = Resource(studio_id=1, name="Зал", timezone="Europe/Moscow")
    booking = Booking(
        resource_id=1,
        studio_id=1,
        client_telegram_id=1,
        client_name="Анна",
        client_phone="+79991234567",
        starts_at=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc),
        status=STATUS_HOLD,
        hold_expires_at=datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc),
        quoted_price_rub=1000,
        prepay_amount_rub=1000,
    )
    text = booking_summary(booking, studio, resource)
    assert "Не оплачено" in text
    booking.status = STATUS_PAID
    assert "Оплачено" in booking_summary(booking, studio, resource)


def test_redact_phone():
    from src.middlewares.logging import redact_pii

    assert "[phone]" in redact_pii("Мой номер +79991234567")
    assert "79991234567" not in redact_pii("Мой номер +79991234567")


def test_backup_sqlite_valid(tmp_path, monkeypatch):
    import sqlite3

    from src.config import settings
    from src.services.jobs import backup_sqlite

    src = tmp_path / "studio_book.db"
    conn = sqlite3.connect(src)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(settings, "SQLITE_PATH", src)
    dest = backup_sqlite()
    assert dest is not None
    assert dest.exists()
    assert "-" in dest.stem
    check = sqlite3.connect(dest)
    assert check.execute("SELECT id FROM t").fetchone()[0] == 1
    check.close()
