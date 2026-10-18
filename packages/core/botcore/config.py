"""Конфигурация приложения. Загружает переменные окружения из .env.

Один модуль на все боты платформы: каждый бот передаёт свой путь к БД
по умолчанию, остальные переменные (BOT_TOKEN, DEFAULT_LANG, DB_PATH,
ADMIN_IDS) читаются одинаково.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: str
    default_lang: str

    @staticmethod
    def load(default_db_path: str = "data/bot.db", bot_dir: Path | str | None = None) -> Config:
        # Сначала общий .env в корне монорепо (боты запускаются оттуда),
        # затем .env самого бота — у каждого бота свой токен от @BotFather,
        # поэтому его значения перекрывают общие.
        load_dotenv(Path.cwd() / ".env")
        if bot_dir is not None:
            bot_env = Path(bot_dir) / ".env"
            if bot_env.exists():
                load_dotenv(bot_env, override=True)
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "BOT_TOKEN не задан. Скопируйте .env.example бота в .env "
                "и заполните токен (получить у @BotFather)."
            )
        return Config(
            bot_token=token,
            db_path=os.getenv("DB_PATH", default_db_path).strip(),
            default_lang=os.getenv("DEFAULT_LANG", "ru").strip().lower(),
        )


def parse_admin_ids(env_var: str = "ADMIN_IDS") -> set[int]:
    """ID администраторов из env-переменной (через запятую или точку с запятой)."""
    raw = os.getenv(env_var, "").strip()
    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids
