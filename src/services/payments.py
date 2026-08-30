from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.base import utcnow
from src.database.models.booking import STATUS_HOLD, STATUS_PAID, Booking
from src.database.models.payment import (
    KIND_OWNER_SUBSCRIPTION,
    KIND_SLOT_PREPAY,
    PAYMENT_PAID,
    PAYMENT_PENDING,
    PAYMENT_REFUNDED,
    Payment,
)
from src.database.models.studio import TARIFF_PLUS, TARIFF_STARTER, Studio
from src.services import prodamus
from src.services.tariffs import resource_limit_for


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def create_slot_invoice(
    session: AsyncSession,
    booking: Booking,
    amount_rub: int,
) -> Payment:
    payment = Payment(
        kind=KIND_SLOT_PREPAY,
        booking_id=booking.id,
        studio_id=booking.studio_id,
        amount_rub=amount_rub,
        status=PAYMENT_PENDING,
    )
    session.add(payment)
    await session.flush()
    payment.prodamus_invoice_id = f"slot-{booking.id}-{payment.id}"
    await session.commit()
    await session.refresh(payment)
    return payment


async def create_subscription_invoice(
    session: AsyncSession,
    studio: Studio,
    *,
    tariff: str,
    amount_rub: int,
) -> Payment:
    payment = Payment(
        kind=KIND_OWNER_SUBSCRIPTION,
        studio_id=studio.id,
        amount_rub=amount_rub,
        status=PAYMENT_PENDING,
    )
    session.add(payment)
    await session.flush()
    payment.prodamus_invoice_id = f"sub-{studio.id}-{tariff}-{payment.id}"
    await session.commit()
    await session.refresh(payment)
    return payment


def payment_url(payment: Payment, *, phone: str | None = None, description: str) -> str:
    order_id = payment.prodamus_invoice_id or f"pay-{payment.id}"
    return prodamus.build_payment_url(
        order_id=order_id,
        amount_rub=payment.amount_rub,
        description=description,
        customer_phone=phone,
        extra={"kind": payment.kind, "payment_id": str(payment.id)},
    )


async def apply_paid_order(session: AsyncSession, order_id: str) -> Payment | None:
    """Идемпотентно: повторный webhook не меняет уже paid."""
    stmt = select(Payment).where(Payment.prodamus_invoice_id == order_id)
    payment = (await session.execute(stmt)).scalar_one_or_none()
    if payment is None:
        return None
    if payment.status in (PAYMENT_PAID, PAYMENT_REFUNDED):
        return payment

    payment.status = PAYMENT_PAID
    payment.paid_at = utcnow()

    if payment.kind == KIND_SLOT_PREPAY and payment.booking_id:
        booking = await session.get(Booking, payment.booking_id)
        if booking and booking.status == STATUS_HOLD:
            booking.status = STATUS_PAID
            booking.hold_expires_at = None

    if payment.kind == KIND_OWNER_SUBSCRIPTION and payment.studio_id:
        studio = await session.get(Studio, payment.studio_id)
        if studio:
            tariff = TARIFF_PLUS if payment.amount_rub >= settings.TARIFF_PLUS_RUB else TARIFF_STARTER
            if payment.prodamus_invoice_id and "-plus-" in payment.prodamus_invoice_id:
                tariff = TARIFF_PLUS
            elif payment.prodamus_invoice_id and "-starter-" in payment.prodamus_invoice_id:
                tariff = TARIFF_STARTER
            studio.tariff = tariff
            studio.resource_limit = resource_limit_for(tariff)
            from datetime import timedelta

            base = _as_utc(studio.subscription_until)
            now = utcnow()
            start = base if base and base > now else now
            studio.subscription_until = start + timedelta(days=30)

    await session.commit()
    await session.refresh(payment)
    return payment


async def apply_refund(
    session: AsyncSession,
    payment: Payment,
    amount_rub: int,
    *,
    commit: bool = True,
) -> Payment:
    if payment.status == PAYMENT_REFUNDED:
        return payment
    payment.status = PAYMENT_REFUNDED
    payment.refunded_at = utcnow()
    payment.refund_amount_rub = amount_rub
    if commit:
        await session.commit()
        await session.refresh(payment)
    return payment
