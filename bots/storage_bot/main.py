"""Точка входа файлового хранилища.

Запуск из корня монорепо:  python -m bots.storage_bot
Перед запуском заполните bots/storage_bot/.env (см. .env.example).
"""

import asyncio
import logging
from pathlib import Path

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from botcore import Config, build_bot, setup_error_handler

from .handlers import storage as storage_handlers
from .services.database import Database
from .services.storage import Storage


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    log = logging.getLogger("storage-bot")

    config = Config.load(default_db_path="data/storage.db", bot_dir=Path(__file__).parent)

    db = Database(config.db_path)
    files_root = Path(config.db_path).parent / "storage"
    storage = Storage(files_root)

    storage_handlers.db = db
    storage_handlers.storage = storage

    bot = build_bot(config.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(storage_handlers.router)
    setup_error_handler(dp, "storage-bot")

    log.info("Хранилище запущено (БД=%s, файлы=%s)", config.db_path, files_root)
    try:
        await dp.start_polling(bot)
    finally:
        db.close()
        await bot.session.close()
        log.info("Остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
