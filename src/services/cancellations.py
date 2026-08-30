"""Отмена брони и расчёт возврата предоплаты."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.base import utcnow
from src.database.models.booking import STATUS_CANCELLED, STATUS_HOLD, STATUS_PAID, Booking
from src.database.models.payment import (
    KIND_SLOT_PREPAY,
    PAYMENT_PAID,
    Payment,
)
from src.database.models.studio import Studio
from src.services import prodamus
from src.services.payments import apply_refund


@dataclass
class CancelResult:
    ok: bool
    message: str
    refund_rub: int = 0
    reason: str = ""


def cancel_rules_text() -> str:
    path = settings.cancel_rules_path
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return "Отмена в боте. Полный возврат, если до слота хватает срока студии."


def refund_for_cancel(
    studio: Studio,
    booking: Booking,
    paid_amount: int,
    *,
    by: str,
    now: datetime | None = None,
) -> tuple[int, str]:
    if paid_amount <= 0:
        return 0, "no_payment"
    if by == "owner":
        return paid_amount, "owner_cancel"
    now = now or utcnow()
    start = booking.starts_at
    if start.tzinfo is None:
        from datetime import timezone

        start = start.replace(tzinfo=timezone.utc)
    hours_left = (start - now).total_seconds() / 3600.0
    free_hours = int(studio.cancel_free_hours or 72)
    if hours_left >= free_hours:
        return paid_amount, "free_cancel"
    retain = int(studio.late_cancel_retain_percent or 50)
    retain = min(100, max(0, retain))
    refund = int(paid_amount * (100 - retain) / 100)
    return refund, "late_cancel"


async def paid_slot_payment(session: AsyncSession, booking_id: int) -> Payment | None:
    stmt = (
        select(Payment)
        .where(
            Payment.booking_id == booking_id,
            Payment.kind == KIND_SLOT_PREPAY,
            Payment.status == PAYMENT_PAID,
        )
        .order_by(Payment.id.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def cancel_booking(
    session: AsyncSession,
    booking: Booking,
    studio: Studio,
    *,
    by: str,
    now: datetime | None = None,
) -> CancelResult:
    if booking.status == STATUS_CANCELLED:
        return CancelResult(ok=False, message="Бронь уже отменена.", reason="already")
    if booking.status not in (STATUS_HOLD, STATUS_PAID, "blocked"):
        return CancelResult(ok=False, message="Эту бронь нельзя отменить.", reason="bad_status")

    payment = await paid_slot_payment(session, booking.id)
    paid_amount = payment.amount_rub if payment else int(booking.prepay_amount_rub or 0)
    refund_rub, reason = refund_for_cancel(
        studio, booking, paid_amount if booking.status == STATUS_PAID else 0, by=by, now=now
    )

    booking.status = STATUS_CANCELLED
    booking.cancel_reason = f"{by}:{reason}"

    remote_note = ""
    if payment and refund_rub > 0:
        order_id = payment.prodamus_invoice_id or ""
        ok, detail = await prodamus.request_refund(order_id, refund_rub)
        await apply_refund(session, payment, refund_rub, commit=False)
        if not ok:
            remote_note = (
                f" Кассу не удалось дернуть автоматически ({detail}). "
                "Верните сумму в кабинете Prodamus."
            )

    await session.commit()

    if booking.status == STATUS_CANCELLED and refund_rub <= 0:
        text = "Бронь отменена, слот свободен."
    elif reason == "free_cancel" or by == "owner":
        text = f"Бронь отменена. К возврату {refund_rub} ₽.{remote_note}"
    else:
        retain = studio.late_cancel_retain_percent or 50
        hours = studio.cancel_free_hours or 72
        text = (
            f"Бронь отменена (до слота меньше {hours} ч). "
            f"Удержание {retain}%, к возврату {refund_rub} ₽.{remote_note}"
        )
    return CancelResult(ok=True, message=text, refund_rub=refund_rub, reason=reason)
