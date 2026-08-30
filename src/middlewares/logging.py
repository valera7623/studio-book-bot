import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Update

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        if event.message:
            logger.info(
                "Message from %s: %s",
                event.message.from_user.id,
                event.message.text or event.message.content_type,
            )
        elif event.callback_query:
            logger.info(
                "Callback from %s: %s",
                event.callback_query.from_user.id,
                event.callback_query.data,
            )

        try:
            return await handler(event, data)
        except Exception:
            logger.exception("Error in handler")
            raise
