"""Разбор человеко-читаемых дат для дедлайнов и напоминаний.

Принимает фразы вроде «завтра 18:00», «через 2 часа», «25.12 14:30».
Возвращает datetime в UTC (для хранения) либо None.

Хранение в UTC, отображение — в локальной зоне пользователя. Зона задаётся
в .env через TZ_OFFSET_HOURS (смещение от UTC), чтобы не тянуть базу tzdata
и не усложнять деплой на слабом сервере.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta, timezone

import dateparser


def local_tz() -> timezone:
    """Зона пользователя из env (читается при каждом вызове — удобно для тестов)."""
    offset = float(os.getenv("TZ_OFFSET_HOURS", "3"))
    return timezone(timedelta(hours=offset))


def parse_datetime(text: str) -> datetime | None:
    """Парсит фразу в осведомлённый о зоне datetime (UTC). None если не вышло."""
    text = (text or "").strip()
    if not text:
        return None
    tz = local_tz()
    now_local = datetime.now(tz)
    parsed = dateparser.parse(
        text,
        languages=["ru", "en"],
        settings={
            "RELATIVE_BASE": now_local.replace(tzinfo=None),
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": False,
        },
    )
    if not parsed:
        return None
    # трактуем результат как локальное время пользователя -> переводим в UTC
    local_dt = parsed.replace(tzinfo=tz)
    return local_dt.astimezone(UTC)


def to_local(dt_utc_iso: str | None) -> datetime | None:
    if not dt_utc_iso:
        return None
    dt = datetime.fromisoformat(dt_utc_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(local_tz())


def fmt_local(dt_utc_iso: str | None) -> str:
    local = to_local(dt_utc_iso)
    if not local:
        return "—"
    return local.strftime("%d.%m.%Y %H:%M")


def default_remind_before(deadline_utc: datetime, hours: int = 1) -> datetime:
    """Время напоминания по умолчанию — за N часов до дедлайна (но не в прошлом)."""
    remind = deadline_utc - timedelta(hours=hours)
    now = datetime.now(UTC)
    return remind if remind > now else now + timedelta(minutes=1)
