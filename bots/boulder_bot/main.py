"""Точка входа бота записи в скалодром.

Запуск из корня монорепо:  python -m bots.boulder_bot
Демо-данные (опционально):  python -m bots.boulder_bot.seed
Заполните .env (BOT_TOKEN, ADMIN_IDS, TZ_OFFSET_HOURS) — см. .env.example.
"""

import asyncio
import logging
from pathlib import Path

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from botcore import NLP, Config, build_bot, dates, parse_admin_ids, setup_error_handler

from .handlers import admin, booking
from .services.database import Database
from .services.faq import FAQMatcher
from .services.scheduler import ReminderScheduler


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    log = logging.getLogger("boulder-bot")

    config = Config.load(default_db_path="data/boulder.db", bot_dir=Path(__file__).parent)

    db = Database(config.db_path)
    nlp = NLP(config.default_lang)
    faq = FAQMatcher(db, nlp)

    bot = build_bot(config.bot_token)

    async def notify(user_id: int, appt) -> None:
        """Напоминание клиенту. При неудаче — исключение наружу: планировщик
        пометит запись «напомнили» только после успешной отправки."""
        text = (
            "🔔 <b>Напоминание о занятии</b>\n\n"
            f"🧗 {appt['service_name']}\n"
            f"📅 {dates.fmt_local(appt['starts_at'])}\n\n"
            "Если планы изменились — отмените запись в разделе «Мои записи»."
        )
        await bot.send_message(user_id, text)

    scheduler = ReminderScheduler(db, notify, lead_hours=24, interval_minutes=15)

    # Внедрение зависимостей
    admin_ids = parse_admin_ids()
    booking.db = db
    booking.faq = faq
    booking.ADMIN_IDS = admin_ids
    admin.db = db
    admin.ADMIN_IDS = admin_ids

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin.router)
    dp.include_router(booking.router)
    setup_error_handler(dp, "boulder-bot")

    scheduler.start()
    log.info("Бот скалодрома запущен (админов: %d)", len(admin_ids))
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
