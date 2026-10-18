"""botcore — общее ядро платформы Telegram-ботов.

Модули:
  - nlp        : теги, summary, семантический поиск, классификация по темам
  - dates      : разбор человеко-читаемых дат, хранение в UTC
  - config     : загрузка конфигурации из .env
  - scheduling : обёртка над APScheduler для периодических джобов
  - errors     : единый error-handler для aiogram 3
  - telegram   : создание Bot с поддержкой прокси
"""

from botcore.config import Config, parse_admin_ids
from botcore.errors import setup_error_handler
from botcore.nlp import NLP, TfidfIndex, TopicClassifier
from botcore.scheduling import PeriodicScheduler
from botcore.telegram import build_bot, resolve_proxy

__all__ = [
    "NLP",
    "Config",
    "PeriodicScheduler",
    "TfidfIndex",
    "TopicClassifier",
    "build_bot",
    "parse_admin_ids",
    "resolve_proxy",
    "setup_error_handler",
]
