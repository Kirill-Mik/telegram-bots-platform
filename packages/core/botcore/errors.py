"""Единый error-handler для aiogram 3.

Без него исключение в хендлере — это тишина для пользователя и трейс
в логах. С ним: инцидент логируется, а пользователь получает понятное
сообщение вместо «бот завис».
"""

from __future__ import annotations

import logging

from aiogram import Dispatcher
from aiogram.types.error_event import ErrorEvent

USER_MESSAGE = "⚠️ Что-то пошло не так. Попробуйте ещё раз чуть позже."


def setup_error_handler(dp: Dispatcher, logger_name: str = "bot") -> None:
    """Вешает на диспетчер обработчик всех необработанных исключений."""
    log = logging.getLogger(logger_name)

    @dp.errors()
    async def _on_error(event: ErrorEvent) -> bool:
        log.exception("Необработанная ошибка в хендлере: %s", event.exception)
        update = event.update
        try:
            if update.callback_query:
                await update.callback_query.answer(USER_MESSAGE, show_alert=True)
            elif update.message:
                await update.message.answer(USER_MESSAGE)
        except Exception as notify_error:  # noqa: BLE001
            log.warning("Не удалось сообщить пользователю об ошибке: %s", notify_error)
        return True  # ошибка обработана, не роняем polling
