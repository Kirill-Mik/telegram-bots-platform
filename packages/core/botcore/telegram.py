"""Создание объекта Bot с единой сетевой настройкой.

Зачем отдельный модуль: aiohttp, на котором работает aiogram, по умолчанию
НЕ читает системные настройки прокси (в отличие от urllib/requests). Если доступ
к api.telegram.org идёт через локальный прокси или VPN-клиент, бот молча висит
в таймауте и падает с ClientConnectorError — при том что тот же адрес прекрасно
открывается браузером.

Прокси берётся из BOT_PROXY, иначе из стандартных HTTPS_PROXY / HTTP_PROXY.
Если ни одна переменная не задана, соединение идёт напрямую.
"""

from __future__ import annotations

import logging
import os

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

__all__ = ["build_bot", "resolve_proxy"]

_PROXY_VARS = ("BOT_PROXY", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")

log = logging.getLogger("botcore.telegram")


def resolve_proxy() -> str | None:
    """Первый непустой прокси из переменных окружения."""
    for name in _PROXY_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def build_bot(token: str, parse_mode: ParseMode = ParseMode.HTML) -> Bot:
    """Bot с HTML-разметкой по умолчанию и прокси, если он задан в окружении."""
    proxy = resolve_proxy()
    session = AiohttpSession(proxy=proxy) if proxy else AiohttpSession()
    if proxy:
        log.info("Подключение к Telegram через прокси %s", proxy)
    return Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=parse_mode),
    )
