from html import escape


def format_welcome_message(user) -> str:
    name = user.first_name or "гость"
    return (
        f"👋 Привет, <b>{escape(name)}</b>!\n\n"
        "Это бот <b>записи в фотостудию</b>: свободный слот → бронь по ссылке → "
        "предоплата → напоминание.\n\n"
        "📸 <b>Клиенту</b> — откройте ссылку студии (её пришлёт владелец).\n"
        "🏠 <b>Владельцу</b> — кабинет появится после создания студии.\n\n"
        "Пока собираем MVP. Команды: /help"
    )


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix
