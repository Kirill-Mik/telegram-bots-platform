"""Слой БД файлового хранилища: дерево папок и файлы в них.

Модель простая и знакомая по файловому менеджеру:
  - папка может лежать внутри другой папки (parent_id, NULL = корень);
  - файл лежит в папке (folder_id, NULL = корень);
  - имена уникальны внутри своей папки — при совпадении добавляется «(2)».

Сами байты файлов на диске (см. services/storage.py), в БД только метаданные
и путь. Так хранилище можно скопировать, забэкапить и посмотреть без бота.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    parent_id  INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_folder_unique
    ON folders(user_id, IFNULL(parent_id, 0), name);
CREATE INDEX IF NOT EXISTS idx_folder_parent ON folders(user_id, parent_id);

CREATE TABLE IF NOT EXISTS files (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    folder_id  INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    name       TEXT    NOT NULL,
    size       INTEGER NOT NULL,
    tg_file_id TEXT,
    disk_path  TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_file_unique
    ON files(user_id, IFNULL(folder_id, 0), name);
CREATE INDEX IF NOT EXISTS idx_file_folder ON files(user_id, folder_id);

-- текущая папка пользователя: куда кладём присланный файл
CREATE TABLE IF NOT EXISTS cwd (
    user_id   INTEGER PRIMARY KEY,
    folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL
);
"""


@dataclass(frozen=True)
class Folder:
    id: int
    parent_id: int | None
    name: str


@dataclass(frozen=True)
class File:
    id: int
    folder_id: int | None
    name: str
    size: int
    tg_file_id: str | None
    disk_path: str
    created_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(path, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA foreign_keys = ON")
        self._con.executescript(SCHEMA)
        self._con.commit()

    def close(self) -> None:
        self._con.close()

    # ---------- навигация ----------
    def list_folders(self, user_id: int, parent_id: int | None) -> list[Folder]:
        rows = self._con.execute(
            "SELECT id, parent_id, name FROM folders "
            "WHERE user_id = ? AND IFNULL(parent_id, 0) = IFNULL(?, 0) "
            "ORDER BY name COLLATE NOCASE",
            (user_id, parent_id),
        ).fetchall()
        return [Folder(r["id"], r["parent_id"], r["name"]) for r in rows]

    def list_files(self, user_id: int, folder_id: int | None) -> list[File]:
        rows = self._con.execute(
            "SELECT * FROM files WHERE user_id = ? AND IFNULL(folder_id, 0) = IFNULL(?, 0) "
            "ORDER BY name COLLATE NOCASE",
            (user_id, folder_id),
        ).fetchall()
        return [self._file(r) for r in rows]

    def get_folder(self, user_id: int, folder_id: int) -> Folder | None:
        r = self._con.execute(
            "SELECT id, parent_id, name FROM folders WHERE id = ? AND user_id = ?",
            (folder_id, user_id),
        ).fetchone()
        return Folder(r["id"], r["parent_id"], r["name"]) if r else None

    def get_file(self, user_id: int, file_id: int) -> File | None:
        r = self._con.execute(
            "SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, user_id)
        ).fetchone()
        return self._file(r) if r else None

    def breadcrumbs(self, user_id: int, folder_id: int | None) -> list[Folder]:
        """Путь от корня до папки: [Клиенты, Договоры]."""
        chain: list[Folder] = []
        seen: set[int] = set()
        cur = folder_id
        while cur is not None and cur not in seen:
            seen.add(cur)
            f = self.get_folder(user_id, cur)
            if f is None:
                break
            chain.append(f)
            cur = f.parent_id
        return list(reversed(chain))

    # ---------- изменения ----------
    def create_folder(self, user_id: int, parent_id: int | None, name: str) -> Folder:
        name = self.unique_folder_name(user_id, parent_id, name)
        cur = self._con.execute(
            "INSERT INTO folders(user_id, parent_id, name, created_at) VALUES (?, ?, ?, ?)",
            (user_id, parent_id, name, _now()),
        )
        self._con.commit()
        return Folder(cur.lastrowid, parent_id, name)

    def add_file(
        self, user_id: int, folder_id: int | None, name: str,
        size: int, disk_path: str, tg_file_id: str | None = None,
    ) -> File:
        name = self.unique_file_name(user_id, folder_id, name)
        cur = self._con.execute(
            "INSERT INTO files(user_id, folder_id, name, size, tg_file_id, disk_path, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, folder_id, name, size, tg_file_id, disk_path, _now()),
        )
        self._con.commit()
        return File(cur.lastrowid, folder_id, name, size, tg_file_id, disk_path, _now())

    def rename_folder(self, user_id: int, folder_id: int, name: str) -> str:
        f = self.get_folder(user_id, folder_id)
        if f is None:
            raise ValueError("папка не найдена")
        name = self.unique_folder_name(user_id, f.parent_id, name, exclude_id=folder_id)
        self._con.execute(
            "UPDATE folders SET name = ? WHERE id = ? AND user_id = ?", (name, folder_id, user_id)
        )
        self._con.commit()
        return name

    def rename_file(self, user_id: int, file_id: int, name: str) -> str:
        f = self.get_file(user_id, file_id)
        if f is None:
            raise ValueError("файл не найден")
        name = self.unique_file_name(user_id, f.folder_id, name, exclude_id=file_id)
        self._con.execute(
            "UPDATE files SET name = ? WHERE id = ? AND user_id = ?", (name, file_id, user_id)
        )
        self._con.commit()
        return name

    def move_file(self, user_id: int, file_id: int, folder_id: int | None) -> None:
        f = self.get_file(user_id, file_id)
        if f is None:
            raise ValueError("файл не найден")
        name = self.unique_file_name(user_id, folder_id, f.name)
        self._con.execute(
            "UPDATE files SET folder_id = ?, name = ? WHERE id = ? AND user_id = ?",
            (folder_id, name, file_id, user_id),
        )
        self._con.commit()

    def delete_file(self, user_id: int, file_id: int) -> File | None:
        f = self.get_file(user_id, file_id)
        if f is None:
            return None
        self._con.execute("DELETE FROM files WHERE id = ? AND user_id = ?", (file_id, user_id))
        self._con.commit()
        return f

    def delete_folder(self, user_id: int, folder_id: int) -> list[File]:
        """Удаляет папку со всем содержимым. Возвращает удалённые файлы —
        вызывающий код стирает их с диска."""
        victims = self.walk_files(user_id, folder_id)
        self._con.execute("DELETE FROM folders WHERE id = ? AND user_id = ?", (folder_id, user_id))
        self._con.commit()
        return victims

    # ---------- обход ----------
    def walk_files(self, user_id: int, folder_id: int | None) -> list[File]:
        """Все файлы папки и всех вложенных папок."""
        out = list(self.list_files(user_id, folder_id))
        for sub in self.list_folders(user_id, folder_id):
            out.extend(self.walk_files(user_id, sub.id))
        return out

    def relative_paths(self, user_id: int, folder_id: int | None) -> list[tuple[str, File]]:
        """Пары «путь внутри папки → файл» — для выгрузки архивом."""
        out: list[tuple[str, File]] = [(f.name, f) for f in self.list_files(user_id, folder_id)]
        for sub in self.list_folders(user_id, folder_id):
            for rel, f in self.relative_paths(user_id, sub.id):
                out.append((f"{sub.name}/{rel}", f))
        return out

    def counts(self, user_id: int, folder_id: int | None) -> tuple[int, int]:
        """(папок, файлов) непосредственно внутри."""
        return (
            len(self.list_folders(user_id, folder_id)),
            len(self.list_files(user_id, folder_id)),
        )

    def total_size(self, user_id: int) -> int:
        r = self._con.execute(
            "SELECT COALESCE(SUM(size), 0) AS s FROM files WHERE user_id = ?", (user_id,)
        ).fetchone()
        return int(r["s"])

    def search(self, user_id: int, query: str, limit: int = 20) -> list[File]:
        """Поиск по имени файла — обычное подстрочное совпадение, без магии."""
        rows = self._con.execute(
            "SELECT * FROM files WHERE user_id = ? AND name LIKE ? COLLATE NOCASE "
            "ORDER BY name COLLATE NOCASE LIMIT ?",
            (user_id, f"%{query}%", limit),
        ).fetchall()
        return [self._file(r) for r in rows]

    # ---------- текущая папка ----------
    def get_cwd(self, user_id: int) -> int | None:
        r = self._con.execute("SELECT folder_id FROM cwd WHERE user_id = ?", (user_id,)).fetchone()
        if r is None or r["folder_id"] is None:
            return None
        # папку могли удалить, пока пользователь в ней стоял
        return r["folder_id"] if self.get_folder(user_id, r["folder_id"]) else None

    def set_cwd(self, user_id: int, folder_id: int | None) -> None:
        self._con.execute(
            "INSERT INTO cwd(user_id, folder_id) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET folder_id = excluded.folder_id",
            (user_id, folder_id),
        )
        self._con.commit()

    # ---------- служебное ----------
    def unique_folder_name(
        self, user_id: int, parent_id: int | None, name: str, exclude_id: int | None = None
    ) -> str:
        taken = {
            f.name.lower()
            for f in self.list_folders(user_id, parent_id)
            if f.id != exclude_id
        }
        return _dedupe(name, taken)

    def unique_file_name(
        self, user_id: int, folder_id: int | None, name: str, exclude_id: int | None = None
    ) -> str:
        taken = {
            f.name.lower()
            for f in self.list_files(user_id, folder_id)
            if f.id != exclude_id
        }
        return _dedupe(name, taken)

    @staticmethod
    def _file(r: sqlite3.Row) -> File:
        return File(
            r["id"], r["folder_id"], r["name"], r["size"],
            r["tg_file_id"], r["disk_path"], r["created_at"],
        )


def _dedupe(name: str, taken: set[str]) -> str:
    """«отчёт.pdf» → «отчёт (2).pdf», если имя занято."""
    if name.lower() not in taken:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    n = 2
    while True:
        candidate = f"{stem} ({n}){dot}{ext}" if dot else f"{stem} ({n})"
        if candidate.lower() not in taken:
            return candidate
        n += 1
