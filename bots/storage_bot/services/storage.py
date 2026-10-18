"""Файлы на диске.

БД хранит метаданные, байты лежат здесь. Раскладка на диске повторяет
дерево папок пользователя, поэтому хранилище можно открыть проводником
и понять, что где лежит, даже без бота:

    data/storage/<user_id>/<Папка>/<Подпапка>/файл.pdf

Имена подчищаются от символов, недопустимых в путях Windows и Linux.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

# запрещённые в именах файлов символы + управляющие
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_NAME = 120


def safe_name(name: str) -> str:
    """Имя, пригодное и для файловой системы, и для показа пользователю."""
    cleaned = _BAD.sub("_", (name or "").strip()).strip(". ")
    cleaned = cleaned[:MAX_NAME].strip()
    if not cleaned:
        return "без_имени"
    stem = cleaned.split(".")[0].upper()
    return f"_{cleaned}" if stem in _RESERVED else cleaned


class Storage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, user_id: int, rel_dir: str, filename: str) -> Path:
        """Куда положить файл: корень / пользователь / путь папок / имя."""
        base = self.root / str(user_id)
        for part in filter(None, rel_dir.split("/")):
            base = base / safe_name(part)
        base.mkdir(parents=True, exist_ok=True)
        target = base / safe_name(filename)
        # на диске имена могут столкнуться иначе, чем в БД — разводим суффиксом
        n = 2
        while target.exists():
            target = base / f"{target.stem} ({n}){target.suffix}"
            n += 1
        return target

    @staticmethod
    def write(path: Path, data: bytes) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return len(data)

    @staticmethod
    def read(path: str | Path) -> bytes:
        return Path(path).read_bytes()

    @staticmethod
    def exists(path: str | Path) -> bool:
        return Path(path).exists()

    @staticmethod
    def remove(path: str | Path) -> None:
        p = Path(path)
        if p.exists():
            p.unlink()

    @staticmethod
    def zip_files(items: list[tuple[str, str]]) -> bytes:
        """Архив из пар «путь внутри архива → путь на диске».

        Пропущенные (удалённые вручную) файлы молча игнорируются: лучше отдать
        архив без одного файла, чем не отдать ничего.
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for arcname, disk_path in items:
                p = Path(disk_path)
                if p.exists():
                    zf.write(p, arcname=arcname)
        return buf.getvalue()


def human_size(size: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} ГБ"
