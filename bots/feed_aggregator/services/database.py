"""Слой БД агрегатора (SQLite).

Хранит:
  - sources  : RSS-ленты, на которые подписан пользователь
                (+ ETag / Last-Modified для условных запросов)
  - topics   : пользовательские темы (название + ключевые слова)
  - posts    : собранные и классифицированные записи (с дедупликацией)

Дедупликация постов — по уникальному хешу (источник + ссылка/заголовок),
чтобы повторный опрос ленты не плодил дубли.
"""

import hashlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT,
    etag          TEXT,             -- ETag последнего ответа (условные GET)
    last_modified TEXT,             -- Last-Modified последнего ответа
    added_at      TEXT NOT NULL,
    UNIQUE(user_id, url)
);

CREATE TABLE IF NOT EXISTS topics (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    name       TEXT NOT NULL,
    keywords   TEXT NOT NULL,         -- JSON-массив
    UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS posts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    source_id  INTEGER,
    uid        TEXT NOT NULL,         -- хеш для дедупликации
    title      TEXT NOT NULL,
    summary    TEXT NOT NULL,
    url        TEXT,
    topic      TEXT,                  -- назначенная тема или NULL
    score      REAL,
    published  TEXT,
    created_at TEXT NOT NULL,
    seen       INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, uid)
);

CREATE INDEX IF NOT EXISTS idx_posts_user   ON posts(user_id);
CREATE INDEX IF NOT EXISTS idx_posts_topic  ON posts(user_id, topic);
CREATE INDEX IF NOT EXISTS idx_posts_seen   ON posts(user_id, seen);
"""


def make_uid(source: str, link: str, title: str) -> str:
    raw = f"{source}|{link}|{title}".encode("utf-8", "ignore")
    return hashlib.sha1(raw).hexdigest()


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---- Источники ----
    def add_source(self, user_id: int, url: str, title: str | None) -> int | None:
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO sources (user_id, url, title, added_at) VALUES (?,?,?,?)",
                    (user_id, url, title, datetime.now(UTC).isoformat()),
                )
                self._conn.commit()
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None  # уже подписан

    def list_sources(self, user_id: int) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM sources WHERE user_id = ? ORDER BY id", (user_id,)
            ).fetchall()

    def remove_source(self, user_id: int, source_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM sources WHERE id = ? AND user_id = ?", (source_id, user_id)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def all_sources(self) -> list[sqlite3.Row]:
        """Все источники всех пользователей (для планировщика)."""
        with self._lock:
            return self._conn.execute("SELECT * FROM sources ORDER BY user_id").fetchall()

    def update_source_cache(
        self, source_id: int, etag: str | None, last_modified: str | None
    ) -> None:
        """Сохраняет ETag/Last-Modified для условных запросов при следующем опросе."""
        with self._lock:
            self._conn.execute(
                "UPDATE sources SET etag = ?, last_modified = ? WHERE id = ?",
                (etag, last_modified, source_id),
            )
            self._conn.commit()

    # ---- Темы ----
    def add_topic(self, user_id: int, name: str, keywords: list[str]) -> int | None:
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO topics (user_id, name, keywords) VALUES (?,?,?)",
                    (user_id, name, json.dumps(keywords, ensure_ascii=False)),
                )
                self._conn.commit()
                return cur.lastrowid
            except sqlite3.IntegrityError:
                # обновим ключевые слова, если тема существует
                self._conn.execute(
                    "UPDATE topics SET keywords = ? WHERE user_id = ? AND name = ?",
                    (json.dumps(keywords, ensure_ascii=False), user_id, name),
                )
                self._conn.commit()
                return None

    def get_topics(self, user_id: int) -> dict[str, list[str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, keywords FROM topics WHERE user_id = ?", (user_id,)
            ).fetchall()
        return {r["name"]: json.loads(r["keywords"]) for r in rows}

    def list_topics(self, user_id: int) -> list[sqlite3.Row]:
        """Строки тем с id — для клавиатур (в callback_data кладём числовой id)."""
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM topics WHERE user_id = ? ORDER BY id", (user_id,)
            ).fetchall()

    def get_topic(self, user_id: int, topic_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM topics WHERE id = ? AND user_id = ?",
                (topic_id, user_id),
            ).fetchone()

    def remove_topic(self, user_id: int, topic_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM topics WHERE id = ? AND user_id = ?", (topic_id, user_id)
            )
            self._conn.commit()
            return cur.rowcount > 0

    # ---- Посты ----
    def add_post(
        self,
        user_id: int,
        source_id: int | None,
        uid: str,
        title: str,
        summary: str,
        url: str | None,
        topic: str | None,
        score: float | None,
        published: str | None,
    ) -> int | None:
        with self._lock:
            try:
                cur = self._conn.execute(
                    """INSERT INTO posts
                       (user_id, source_id, uid, title, summary, url, topic, score,
                        published, created_at, seen)
                       VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
                    (
                        user_id, source_id, uid, title, summary, url, topic, score,
                        published, datetime.now(UTC).isoformat(),
                    ),
                )
                self._conn.commit()
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None  # дубль

    def unseen_posts(self, user_id: int, limit: int = 50) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """SELECT * FROM posts WHERE user_id = ? AND seen = 0
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()

    def posts_by_topic(self, user_id: int, topic: str, limit: int = 20) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """SELECT * FROM posts WHERE user_id = ? AND topic = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, topic, limit),
            ).fetchall()

    def recent_posts(self, user_id: int, limit: int = 20) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM posts WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()

    def mark_seen(self, user_id: int, post_ids: list[int]) -> None:
        if not post_ids:
            return
        with self._lock:
            self._conn.executemany(
                "UPDATE posts SET seen = 1 WHERE id = ? AND user_id = ?",
                [(pid, user_id) for pid in post_ids],
            )
            self._conn.commit()

    def stats(self, user_id: int) -> dict:
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) c FROM posts WHERE user_id = ?", (user_id,)
            ).fetchone()["c"]
            by_topic = self._conn.execute(
                """SELECT COALESCE(topic,'(без темы)') t, COUNT(*) c
                   FROM posts WHERE user_id = ? GROUP BY topic ORDER BY c DESC""",
                (user_id,),
            ).fetchall()
            src = self._conn.execute(
                "SELECT COUNT(*) c FROM sources WHERE user_id = ?", (user_id,)
            ).fetchone()["c"]
        return {
            "total": total,
            "sources": src,
            "by_topic": {r["t"]: r["c"] for r in by_topic},
        }

    def close(self):
        with self._lock:
            self._conn.close()
