"""Точка входа ИИ-агрегатора новостей.

Запуск из корня монорепо:  python -m bots.feed_aggregator
Перед запуском заполните .env (см. .env.example в папке бота).
"""

import asyncio
import logging
import os
from pathlib import Path

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from botcore import NLP, Config, build_bot, setup_error_handler

from .handlers import aggregator, ui
from .services.database import Database
from .services.fetcher import FeedFetcher
from .services.scheduler import PollScheduler


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    log = logging.getLogger("aggregator-bot")

    config = Config.load(default_db_path="data/feeds.db", bot_dir=Path(__file__).parent)
    interval = int(os.getenv("POLL_INTERVAL_MIN", "30"))

    db = Database(config.db_path)
    nlp = NLP(config.default_lang)
    fetcher = FeedFetcher(db, nlp)

    bot = build_bot(config.bot_token)

    # Колбэк уведомления: при автоматическом сборе шлём краткий дайджест
    async def notify(user_id: int, new_count: int):
        posts = db.unseen_posts(user_id, limit=50)
        if not posts:
            return
        try:
            await bot.send_message(user_id, ui.format_digest(posts))
            db.mark_seen(user_id, [p["id"] for p in posts])
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось отправить дайджест user=%s: %s", user_id, e)

    scheduler = PollScheduler(db, fetcher, notify, interval_minutes=interval)

    # Внедрение зависимостей в хендлеры
    aggregator.db = db
    aggregator.fetcher = fetcher
    aggregator.scheduler = scheduler

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(aggregator.router)
    setup_error_handler(dp, "aggregator-bot")

    scheduler.start()
    log.info("Агрегатор запущен (интервал %d мин, lang=%s)", interval, config.default_lang)
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        db.close()
        await bot.session.close()
        log.info("Остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
