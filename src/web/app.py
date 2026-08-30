"""HTTP: webhook Prodamus, iCal, лендинг, health. Не веб-кабинет."""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
from sqlalchemy import select

from src.config import PROJECT_ROOT, settings
from src.database.models.booking import STATUS_BLOCKED, STATUS_PAID, Booking
from src.services import prodamus
from src.services.ical import build_calendar
from src.services.payments import apply_paid_order
from src.services.studios import get_studio_by_slug, list_active_resources

logger = logging.getLogger(__name__)

LANDING_DIR = PROJECT_ROOT / "landing"
LANDING_PATH = LANDING_DIR / "index.html"


def _form_to_dict(data: dict) -> dict:
    return {str(k): (v[0] if isinstance(v, list) and v else v) for k, v in data.items()}


def _render_landing(path: Path) -> str:
    html = path.read_text(encoding="utf-8") if path.exists() else "<p>studio-book</p>"
    bot_username = settings.BOT_USERNAME.strip() or "your_bot"
    html = html.replace("{{BOT_USERNAME}}", bot_username)
    html = html.replace("{{BOT_LINK}}", f"https://t.me/{bot_username}")
    html = html.replace("{{TARIFF_STARTER_RUB}}", str(settings.TARIFF_STARTER_RUB))
    html = html.replace("{{TARIFF_PLUS_RUB}}", str(settings.TARIFF_PLUS_RUB))
    html = html.replace("{{FREE_BOOKINGS_PER_MONTH}}", str(settings.FREE_BOOKINGS_PER_MONTH))
    return html


async def health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def landing(_request: web.Request) -> web.Response:
    return web.Response(text=_render_landing(LANDING_PATH), content_type="text/html", charset="utf-8")


async def offer_page(_request: web.Request) -> web.Response:
    path = LANDING_DIR / "offer.html"
    if not path.exists():
        raise web.HTTPNotFound()
    return web.Response(text=_render_landing(path), content_type="text/html", charset="utf-8")


async def offer_pdf(_request: web.Request) -> web.StreamResponse:
    path = LANDING_DIR / "offer.pdf"
    if not path.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Content-Type": "application/pdf"})


async def pay_stub(request: web.Request) -> web.Response:
    return web.Response(
        text="Оплата принята платёжной системой. Вернитесь в Telegram — бронь подтвердится автоматически.",
        content_type="text/plain",
        charset="utf-8",
    )


async def ical_feed(request: web.Request) -> web.Response:
    slug = request.match_info["slug"]
    session_maker = request.app["session_maker"]
    async with session_maker() as session:
        studio = await get_studio_by_slug(session, slug)
        if studio is None:
            raise web.HTTPNotFound()
        resources = await list_active_resources(session, studio.id)
        if not resources:
            raise web.HTTPNotFound()
        rows = (
            await session.execute(
                select(Booking).where(
                    Booking.studio_id == studio.id,
                    Booking.status.in_((STATUS_PAID, STATUS_BLOCKED)),
                )
            )
        ).scalars().all()
        body = build_calendar(studio, resources, list(rows))
    return web.Response(
        text=body,
        content_type="text/calendar",
        charset="utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}.ics"'},
    )


async def prodamus_webhook(request: web.Request) -> web.Response:
    if request.content_type and "json" in request.content_type:
        payload = await request.json()
    else:
        post = await request.post()
        payload = _form_to_dict(dict(post))
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest()

    signature = (
        request.headers.get("Sign")
        or request.headers.get("X-Signature")
        or str(payload.get("signature") or payload.get("sign") or "")
    )
    check = {k: v for k, v in payload.items() if k not in {"signature", "sign"}}
    if prodamus.is_configured() and not prodamus.verify_signature(
        check, signature, settings.PRODAMUS_SECRET
    ):
        logger.warning("prodamus webhook: bad signature")
        raise web.HTTPForbidden()

    order_id = str(payload.get("order_id") or payload.get("orderId") or "")
    status = str(payload.get("payment_status") or payload.get("status") or "").lower()
    if not order_id:
        raise web.HTTPBadRequest(text="order_id required")
    if status and status not in {"success", "paid", "ok", "1"}:
        return web.Response(text="ignored")

    session_maker = request.app["session_maker"]
    bot = request.app["bot"]
    async with session_maker() as session:
        payment = await apply_paid_order(session, order_id)
        if payment is None:
            logger.info("prodamus webhook: unknown order %s", order_id)
            return web.Response(text="unknown")
        if payment.kind == "slot_prepay" and payment.booking_id:
            from src.database.models.studio import Resource, Studio

            booking = await session.get(Booking, payment.booking_id)
            if booking:
                studio = await session.get(Studio, booking.studio_id)
                resource = await session.get(Resource, booking.resource_id)
                if studio and resource:
                    from src.keyboards.inline import client_booking_keyboard
                    from src.services.formatters import booking_summary

                    text = "✅ Оплата получена.\n" + booking_summary(booking, studio, resource)
                    try:
                        await bot.send_message(
                            booking.client_telegram_id,
                            text,
                            reply_markup=client_booking_keyboard(booking.id),
                        )
                        await bot.send_message(studio.owner_telegram_id, text)
                    except Exception:
                        logger.exception("notify after payment")
        if payment.kind == "owner_subscription" and payment.studio_id:
            from src.database.models.studio import Studio

            studio = await session.get(Studio, payment.studio_id)
            if studio:
                try:
                    await bot.send_message(
                        studio.owner_telegram_id,
                        f"✅ Подписка оплачена. Тариф: {studio.tariff}.",
                    )
                except Exception:
                    logger.exception("notify subscription")
    return web.Response(text="ok")


def create_web_app(bot, session_maker) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app["session_maker"] = session_maker
    app.router.add_get("/health", health)
    app.router.add_get("/", landing)
    app.router.add_get("/offer", offer_page)
    app.router.add_get("/offer/", offer_page)
    app.router.add_get("/offer.pdf", offer_pdf)
    app.router.add_get("/pay/success", pay_stub)
    app.router.add_get("/pay/return", pay_stub)
    app.router.add_get("/ical/{slug}.ics", ical_feed)
    app.router.add_post("/prodamus/webhook", prodamus_webhook)
    return app


async def start_http(bot, session_maker) -> web.AppRunner | None:
    if settings.HTTP_PORT <= 0:
        logger.info("HTTP_PORT=0 — веб (лендинг/webhook/iCal) выключен")
        return None
    app = create_web_app(bot, session_maker)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.HTTP_PORT)
    await site.start()
    logger.info("HTTP слушает 0.0.0.0:%s", settings.HTTP_PORT)
    return runner
