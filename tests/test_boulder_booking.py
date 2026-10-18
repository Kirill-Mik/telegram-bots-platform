"""Тесты атомарности брони boulder_bot: два конкурентных бронирования
одного слота — проходит ровно одно. БД — SQLite во временной папке."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from bots.boulder_bot.services.database import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(str(tmp_path / "boulder.db"))
    yield database
    database.close()


@pytest.fixture()
def slot_id(db):
    service_id = db.add_service("Пробное занятие", 60, 1200)
    return db.add_slot(service_id, "2030-01-01T12:00:00+00:00")


class TestAtomicBooking:
    def test_first_booking_succeeds(self, db, slot_id):
        appt_id = db.book(slot_id, user_id=1, client="Анна", phone=None)
        assert appt_id is not None
        assert db.get_slot(slot_id)["booked"] == 1

    def test_second_booking_rejected(self, db, slot_id):
        assert db.book(slot_id, 1, "Анна", None) is not None
        assert db.book(slot_id, 2, "Борис", None) is None

    def test_concurrent_booking_exactly_one_wins(self, db, slot_id):
        """Два потока бронируют один слот одновременно — победитель один."""
        barrier = threading.Barrier(2)

        def try_book(user_id: int):
            barrier.wait()  # стартуем максимально одновременно
            return db.book(slot_id, user_id, f"user{user_id}", None)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(try_book, [101, 102]))

        winners = [r for r in results if r is not None]
        assert len(winners) == 1, f"ожидали ровно одну успешную бронь, got {results}"
        # и в БД ровно одна запись со статусом booked
        appts = db.all_upcoming("2000-01-01T00:00:00+00:00")
        assert len(appts) == 1

    def test_nonexistent_slot(self, db):
        assert db.book(99999, 1, "Анна", None) is None

    def test_cancel_frees_slot_for_rebooking(self, db, slot_id):
        appt_id = db.book(slot_id, 1, "Анна", None)
        assert db.cancel(appt_id, user_id=1) is True
        assert db.get_slot(slot_id)["booked"] == 0
        # слот снова можно забронировать
        assert db.book(slot_id, 2, "Борис", None) is not None

    def test_cancel_foreign_appointment_rejected(self, db, slot_id):
        appt_id = db.book(slot_id, 1, "Анна", None)
        assert db.cancel(appt_id, user_id=999) is False
        assert db.get_slot(slot_id)["booked"] == 1
