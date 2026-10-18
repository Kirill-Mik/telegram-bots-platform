"""Тесты разбора человеко-читаемых дат (botcore.dates). Офлайн."""

from datetime import UTC, datetime, timedelta

import pytest
from botcore import dates


@pytest.fixture(autouse=True)
def moscow_tz(monkeypatch):
    monkeypatch.setenv("TZ_OFFSET_HOURS", "3")


class TestParseDatetime:
    def test_tomorrow_evening(self):
        dt = dates.parse_datetime("завтра 18:00")
        assert dt is not None
        assert dt.tzinfo == UTC
        local = dt.astimezone(dates.local_tz())
        expected_date = (datetime.now(dates.local_tz()) + timedelta(days=1)).date()
        assert local.date() == expected_date
        assert (local.hour, local.minute) == (18, 0)
        # хранение в UTC: 18:00 МСК == 15:00 UTC
        assert dt.hour == 15

    def test_in_two_hours(self):
        dt = dates.parse_datetime("через 2 часа")
        assert dt is not None
        expected = datetime.now(UTC) + timedelta(hours=2)
        assert abs((dt - expected).total_seconds()) < 300  # допуск 5 минут

    def test_explicit_date_time(self):
        dt = dates.parse_datetime("25.12 14:30")
        assert dt is not None
        local = dt.astimezone(dates.local_tz())
        assert (local.day, local.month) == (25, 12)
        assert (local.hour, local.minute) == (14, 30)

    def test_garbage_returns_none(self):
        assert dates.parse_datetime("это вообще не дата ни разу") is None

    def test_empty_returns_none(self):
        assert dates.parse_datetime("") is None
        assert dates.parse_datetime(None) is None


class TestFormatting:
    def test_fmt_local_applies_offset(self):
        assert dates.fmt_local("2026-01-01T12:00:00+00:00") == "01.01.2026 15:00"

    def test_fmt_local_none(self):
        assert dates.fmt_local(None) == "—"

    def test_to_local_naive_treated_as_utc(self):
        local = dates.to_local("2026-06-01T10:00:00")
        assert (local.hour, local.minute) == (13, 0)

    def test_tz_offset_env_respected(self, monkeypatch):
        monkeypatch.setenv("TZ_OFFSET_HOURS", "5")
        assert dates.fmt_local("2026-01-01T12:00:00+00:00") == "01.01.2026 17:00"


class TestDefaultRemind:
    def test_remind_one_hour_before(self):
        deadline = datetime.now(UTC) + timedelta(days=1)
        remind = dates.default_remind_before(deadline, hours=1)
        assert remind == deadline - timedelta(hours=1)

    def test_remind_never_in_past(self):
        deadline = datetime.now(UTC) + timedelta(minutes=10)
        remind = dates.default_remind_before(deadline, hours=1)
        assert remind > datetime.now(UTC)
