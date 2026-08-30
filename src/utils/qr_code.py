"""QR и deep-link записи: t.me/bot?start=book_<slug>."""

from __future__ import annotations

import io
import re
from typing import Optional

import qrcode
from qrcode.constants import ERROR_CORRECT_M

_START_PAYLOAD_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_valid_start_payload(payload: str) -> bool:
    return bool(payload and _START_PAYLOAD_RE.fullmatch(payload))


def build_bot_deep_link(bot_username: str, payload: str) -> str:
    username = bot_username.lstrip("@").strip()
    if not username:
        raise ValueError("bot_username не может быть пустым")
    if not is_valid_start_payload(payload):
        raise ValueError("payload для /start: 1–64 символа (латиница, цифры, _ и -)")
    return f"https://t.me/{username}?start={payload}"


def generate_qr_png_bytes(data: str, *, box_size: int = 10, border: int = 2) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def generate_booking_qr(bot_username: str, payload: str) -> tuple[str, bytes]:
    deep_link = build_bot_deep_link(bot_username, payload)
    return deep_link, generate_qr_png_bytes(deep_link)


async def resolve_bot_username(bot, configured_username: Optional[str] = None) -> str:
    if configured_username and configured_username.strip():
        return configured_username.lstrip("@").strip()
    me = await bot.get_me()
    if not me.username:
        raise RuntimeError(
            "У бота нет username. Задайте в @BotFather или BOT_USERNAME в .env"
        )
    return me.username
