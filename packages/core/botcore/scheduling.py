"""Обёртка над APScheduler для периодических фоновых джобов.

Единая точка для всех ботов платформы. Ключевая деталь: первый запуск
джоба планируется через короткую задержку после старта, а НЕ передаётся
next_run_time=None — None в APScheduler означает «джоб на паузе навсегда»
и молча отключает фоновую работу.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

log = logging.getLogger("botcore.scheduling")

DEFAULT_FIRST_RUN_DELAY = 15.0  # секунд после старта до первого прогона


class PeriodicScheduler:
    """Планировщик интервальных джобов с гарантированным первым запуском."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()

    def add_interval_job(
        self,
        fn: Callable,
        *,
        job_id: str,
        minutes: int | None = None,
        seconds: int | None = None,
        first_run_delay: float = DEFAULT_FIRST_RUN_DELAY,
    ) -> None:
        if minutes is None and seconds is None:
            raise ValueError("Укажите minutes или seconds")
        first_run = datetime.now(UTC) + timedelta(seconds=first_run_delay)
        kwargs: dict = {"id": job_id, "next_run_time": first_run}
        if minutes is not None:
            kwargs["minutes"] = minutes
        if seconds is not None:
            kwargs["seconds"] = seconds
        self._scheduler.add_job(fn, "interval", **kwargs)
        log.debug("Джоб %s: интервал %s мин / %s с, первый запуск %s",
                  job_id, minutes, seconds, first_run.isoformat())

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
