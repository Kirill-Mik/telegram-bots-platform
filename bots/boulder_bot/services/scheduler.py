"""Планировщик напоминаний о занятии.

Раз в N минут сканирует записи, по которым занятие наступает в ближайшем
окне (по умолчанию через ~24 часа), и шлёт напоминание клиенту.

Флаг reminded ставится ТОЛЬКО после успешной отправки: если Telegram
недоступен, напоминание повторится на следующем прогоне, а не потеряется.
Флаг в БД переживает перезапуск и исключает дубли.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from botcore import PeriodicScheduler

from .database import Database

log = logging.getLogger("boulder-reminders")

# notify(user_id, appt) -> None; при неудаче отправки — исключение
NotifyFn = Callable[[int, object], Awaitable[None]]


class ReminderScheduler:
    def __init__(
        self,
        db: Database,
        notify: NotifyFn,
        lead_hours: int = 24,
        window_minutes: int = 30,
        interval_minutes: int = 15,
    ):
        self.db = db
        self.notify = notify
        self.lead = timedelta(hours=lead_hours)
        self.window = timedelta(minutes=window_minutes)
        self.interval = interval_minutes
        self._scheduler = PeriodicScheduler()

    def start(self):
        self._scheduler.add_interval_job(
            self._scan, job_id="appt_reminders", minutes=self.interval
        )
        self._scheduler.start()
        log.info(
            "Напоминания о занятии запущены (за %s ч, окно %s)",
            self.lead, self.window,
        )

    async def _scan(self):
        now = datetime.now(UTC)
        target_from = (now + self.lead).isoformat()
        target_to = (now + self.lead + self.window).isoformat()
        for appt in self.db.due_reminders(target_from, target_to):
            try:
                await self.notify(appt["user_id"], appt)
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "Напоминание по записи %s не отправлено (%s) — повторим позже",
                    appt["id"], e,
                )
                continue
            self.db.mark_reminded(appt["id"])

    def shutdown(self):
        self._scheduler.shutdown()
