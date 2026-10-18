"""Планировщик периодического опроса лент.

Построен на PeriodicScheduler из botcore: первый прогон стартует через
короткую задержку после запуска бота (а не «никогда», как это было бы
с next_run_time=None), дальше — по интервалу.

После сбора новых постов вызывает колбэк notify(user_id, new_count),
через который бот присылает дайджест.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from botcore import PeriodicScheduler

from .database import Database
from .fetcher import FeedFetcher

log = logging.getLogger("scheduler")


class PollScheduler:
    def __init__(
        self,
        db: Database,
        fetcher: FeedFetcher,
        notify: Callable[[int, int], Awaitable[None]],
        interval_minutes: int = 30,
    ):
        self.db = db
        self.fetcher = fetcher
        self.notify = notify
        self.interval = interval_minutes
        self._scheduler = PeriodicScheduler()

    def start(self):
        self._scheduler.add_interval_job(
            self._poll_all,
            job_id="poll_all",
            minutes=self.interval,
        )
        self._scheduler.start()
        log.info(
            "Планировщик запущен: первый опрос через несколько секунд, далее каждые %d мин",
            self.interval,
        )

    async def _poll_all(self):
        """Опрашивает источники всех пользователей (в отдельном потоке,
        чтобы синхронные HTTP-запросы и парсинг не блокировали event loop)."""
        sources = self.db.all_sources()
        users = sorted({s["user_id"] for s in sources})
        for user_id in users:
            try:
                new_count = await asyncio.to_thread(self.fetcher.poll_user, user_id)
                if new_count:
                    await self.notify(user_id, new_count)
            except Exception as e:  # noqa: BLE001
                log.warning("Опрос для user=%s упал: %s", user_id, e)

    async def poll_now(self, user_id: int) -> int:
        """Немедленный опрос одного пользователя (по команде из бота)."""
        return await asyncio.to_thread(self.fetcher.poll_user, user_id)

    def shutdown(self):
        self._scheduler.shutdown()
