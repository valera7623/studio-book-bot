"""Готовые тексты для сторис, канала и клиентов (онбординг за вечер)."""

from html import escape

from src.database.models.studio import Studio


def client_broadcast(studio: Studio, deep_link: str) -> str:
    return (
        f"Теперь записаться в {studio.name} можно через бот:\n"
        f"{deep_link}\n"
        "Выберите зал и время, внесите предоплату — слот закрепится сам. "
        "Напомним за сутки и за 2 часа."
    )


def stories_text(studio: Studio, deep_link: str) -> str:
    return f"Свободные окна и запись без переписки — {studio.name}: {deep_link}"


def channel_text(studio: Studio, deep_link: str) -> str:
    return (
        f"Запись в {studio.name} по ссылке, без «напишите в личку»:\n"
        f"{deep_link}"
    )


def owner_copy_pack(studio: Studio, deep_link: str) -> str:
    return (
        "📣 <b>Тексты для клиентов</b>\n"
        "Скопируйте и отправьте как есть.\n\n"
        "<b>Клиентам</b>\n"
        f"<code>{escape(client_broadcast(studio, deep_link))}</code>\n\n"
        "<b>Сторис</b>\n"
        f"<code>{escape(stories_text(studio, deep_link))}</code>\n\n"
        "<b>Канал / чат студии</b>\n"
        f"<code>{escape(channel_text(studio, deep_link))}</code>\n\n"
        f"Ссылка: <code>{escape(deep_link)}</code>"
    )
