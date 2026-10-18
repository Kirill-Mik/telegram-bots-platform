"""Слой БД бота записи в скалодром (SQLite).

Сущности:
  - services      : занятия (название, длительность, цена)
  - slots         : доступные временные слоты (привязаны к занятию/дате)
  - appointments  : записи клиентов (бронь слота)
  - faq           : база вопрос-ответ для ИИ-помощника

Защита от двойной брони — честно атомарная, на уровне SQL:
UPDATE slots SET booked = 1 WHERE id = ? AND booked = 0 — проверка и
захват слота происходят одним оператором; выигрывает ровно один запрос
(rowcount = 1), второй получает rowcount = 0 и понятный отказ.
"""

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path


def _now() -> str:
    return datetime.now(UTC).isoformat()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS services (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    duration    INTEGER NOT NULL DEFAULT 30,   -- минут
    price       INTEGER,                       -- руб, может быть NULL
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS slots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id  INTEGER NOT NULL,
    starts_at   TEXT NOT NULL,                 -- ISO datetime (UTC)
    booked      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(service_id, starts_at),
    FOREIGN KEY(service_id) REFERENCES services(id)
);

CREATE INDEX IF NOT EXISTS idx_slots_lookup ON slots(service_id, booked, starts_at);

CREATE TABLE IF NOT EXISTS appointments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,             -- клиент (telegram id)
    client      TEXT NOT NULL,                -- имя
    phone       TEXT,
    status      TEXT NOT NULL DEFAULT 'booked', -- booked | cancelled | done
    reminded    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    FOREIGN KEY(slot_id) REFERENCES slots(id)
);

CREATE INDEX IF NOT EXISTS idx_appt_user ON appointments(user_id, status);

CREATE TABLE IF NOT EXISTS faq (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL
);
"""


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---- Услуги ----
    def add_service(self, name: str, duration: int = 30, price: int | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO services (name, duration, price) VALUES (?,?,?)",
                (name, duration, price),
            )
            self._conn.commit()
            return cur.lastrowid

    def list_services(self, active_only: bool = True) -> list[sqlite3.Row]:
        with self._lock:
            q = "SELECT * FROM services"
            if active_only:
                q += " WHERE active = 1"
            q += " ORDER BY name"
            return self._conn.execute(q).fetchall()

    def get_service(self, service_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM services WHERE id = ?", (service_id,)
            ).fetchone()

    # ---- Слоты ----
    def add_slot(self, service_id: int, starts_at_iso: str) -> int | None:
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO slots (service_id, starts_at) VALUES (?,?)",
                    (service_id, starts_at_iso),
                )
                self._conn.commit()
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None  # слот уже существует

    def free_dates(self, service_id: int, now_iso: str) -> list[str]:
        """Уникальные даты (YYYY-MM-DD), где есть свободные будущие слоты."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT DISTINCT substr(starts_at,1,10) d FROM slots
                   WHERE service_id = ? AND booked = 0 AND starts_at >= ?
                   ORDER BY d""",
                (service_id, now_iso),
            ).fetchall()
        return [r["d"] for r in rows]

    def free_slots(self, service_id: int, date_prefix: str, now_iso: str) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """SELECT * FROM slots
                   WHERE service_id = ? AND booked = 0
                     AND substr(starts_at,1,10) = ? AND starts_at >= ?
                   ORDER BY starts_at""",
                (service_id, date_prefix, now_iso),
            ).fetchall()

    def get_slot(self, slot_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM slots WHERE id = ?", (slot_id,)
            ).fetchone()

    # ---- Записи ----
    def book(
        self, slot_id: int, user_id: int, client: str, phone: str | None
    ) -> int | None:
        """Бронирует слот атомарно. None, если слот уже занят.

        Захват слота — одним UPDATE с условием booked = 0: проверка
        занятости и пометка происходят в одном операторе, гонка
        «прочитали свободный — оба записали» невозможна. rowcount = 0
        означает, что слот забрали раньше нас (или его нет).
        """
        with self._lock:
            cur = self._conn.execute(
                "UPDATE slots SET booked = 1 WHERE id = ? AND booked = 0",
                (slot_id,),
            )
            if cur.rowcount == 0:
                self._conn.rollback()
                return None
            cur = self._conn.execute(
                """INSERT INTO appointments (slot_id, user_id, client, phone, created_at)
                   VALUES (?,?,?,?,?)""",
                (slot_id, user_id, client, phone, _now()),
            )
            self._conn.commit()
            return cur.lastrowid

    def my_appointments(self, user_id: int) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """SELECT a.*, s.starts_at, s.service_id, srv.name AS service_name,
                          srv.price, srv.duration
                   FROM appointments a
                   JOIN slots s ON a.slot_id = s.id
                   JOIN services srv ON s.service_id = srv.id
                   WHERE a.user_id = ? AND a.status = 'booked'
                   ORDER BY s.starts_at""",
                (user_id,),
            ).fetchall()

    def cancel(self, appt_id: int, user_id: int) -> bool:
        with self._lock:
            appt = self._conn.execute(
                "SELECT * FROM appointments WHERE id = ? AND user_id = ?",
                (appt_id, user_id),
            ).fetchone()
            if not appt or appt["status"] != "booked":
                return False
            self._conn.execute(
                "UPDATE appointments SET status = 'cancelled' WHERE id = ?", (appt_id,)
            )
            self._conn.execute(
                "UPDATE slots SET booked = 0 WHERE id = ?", (appt["slot_id"],)
            )
            self._conn.commit()
            return True

    # ---- Для планировщика напоминаний ----
    def due_reminders(self, from_iso: str, to_iso: str) -> list[sqlite3.Row]:
        """Записи, занятие по которым наступает в окне [from, to] и ещё не напоминали."""
        with self._lock:
            return self._conn.execute(
                """SELECT a.*, s.starts_at, srv.name AS service_name
                   FROM appointments a
                   JOIN slots s ON a.slot_id = s.id
                   JOIN services srv ON s.service_id = srv.id
                   WHERE a.status = 'booked' AND a.reminded = 0
                     AND s.starts_at BETWEEN ? AND ?""",
                (from_iso, to_iso),
            ).fetchall()

    def mark_reminded(self, appt_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE appointments SET reminded = 1 WHERE id = ?", (appt_id,)
            )
            self._conn.commit()

    # ---- Админ: просмотр записей ----
    def all_upcoming(self, now_iso: str, limit: int = 100) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """SELECT a.*, s.starts_at, srv.name AS service_name
                   FROM appointments a
                   JOIN slots s ON a.slot_id = s.id
                   JOIN services srv ON s.service_id = srv.id
                   WHERE a.status = 'booked' AND s.starts_at >= ?
                   ORDER BY s.starts_at LIMIT ?""",
                (now_iso, limit),
            ).fetchall()

    # ---- FAQ ----
    def add_faq(self, question: str, answer: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO faq (question, answer) VALUES (?,?)", (question, answer)
            )
            self._conn.commit()
            return cur.lastrowid

    def all_faq(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute("SELECT * FROM faq ORDER BY id").fetchall()

    def close(self):
        with self._lock:
            self._conn.close()
