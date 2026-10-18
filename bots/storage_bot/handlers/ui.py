"""Клавиатуры и тексты файлового хранилища."""

from __future__ import annotations

import html

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..services.database import File, Folder
from ..services.storage import human_size

PAGE_SIZE = 8


def _esc(s) -> str:
    return html.escape(str(s) if s is not None else "")


def path_title(chain: list[Folder]) -> str:
    """Хлебные крошки: Хранилище / Клиенты / Договоры."""
    parts = ["📦 Хранилище", *[f.name for f in chain]]
    return " / ".join(_esc(p) for p in parts)


def folder_view(
    chain: list[Folder], folders: list[Folder], files: list[File], page: int, total_size: int
) -> str:
    lines = [f"<b>{path_title(chain)}</b>"]
    if not folders and not files:
        lines.append("\nПапка пуста. Пришлите файл — он ляжет сюда.")
    else:
        lines.append(f"\nПапок: {len(folders)} · файлов: {len(files)}")
        if files:
            lines.append(f"Объём файлов здесь: {human_size(sum(f.size for f in files))}")
    pages = _pages(folders, files)
    if pages > 1:
        lines.append(f"Страница {page + 1} из {pages}")
    lines.append(f"\n<i>Всего в хранилище: {human_size(total_size)}</i>")
    return "\n".join(lines)


def _pages(folders: list[Folder], files: list[File]) -> int:
    total = len(folders) + len(files)
    return max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)


def browser_keyboard(
    chain: list[Folder], folders: list[Folder], files: list[File], page: int
) -> InlineKeyboardMarkup:
    items: list[tuple[str, str]] = [(f"📁 {f.name}", f"cd:{f.id}") for f in folders]
    items += [(f"📄 {f.name}  ·  {human_size(f.size)}", f"file:{f.id}") for f in files]

    pages = _pages(folders, files)
    page = max(0, min(page, pages - 1))
    chunk = items[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    rows = [[InlineKeyboardButton(text=t[:60], callback_data=cb)] for t, cb in chunk]

    if pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀", callback_data=f"page:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton(text="▶", callback_data=f"page:{page + 1}"))
        rows.append(nav)

    actions = [InlineKeyboardButton(text="➕ Папка", callback_data="mkdir")]
    if folders or files:
        actions.append(InlineKeyboardButton(text="⬇️ Скачать всё (ZIP)", callback_data="zip"))
    rows.append(actions)

    tail = []
    if chain:
        parent = chain[-2].id if len(chain) > 1 else 0
        tail.append(InlineKeyboardButton(text="⬅️ Наверх", callback_data=f"cd:{parent}"))
        tail.append(InlineKeyboardButton(text="✏️ Имя папки", callback_data=f"renfo:{chain[-1].id}"))
        tail.append(InlineKeyboardButton(text="🗑", callback_data=f"rmfo:{chain[-1].id}"))
    rows.append(tail or [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def file_card(f: File, chain: list[Folder]) -> str:
    where = path_title(chain)
    return (
        f"📄 <b>{_esc(f.name)}</b>\n\n"
        f"Размер: {human_size(f.size)}\n"
        f"Папка: {where}\n"
        f"Загружен: {_esc(f.created_at[:10])}"
    )


def file_keyboard(f: File) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬇️ Скачать", callback_data=f"dl:{f.id}")],
            [
                InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"renfi:{f.id}"),
                InlineKeyboardButton(text="📂 Переместить", callback_data=f"mv:{f.id}"),
            ],
            [
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"rmfi:{f.id}"),
                InlineKeyboardButton(
                    text="⬅️ К папке", callback_data=f"cd:{f.folder_id or 0}"
                ),
            ],
        ]
    )


def confirm_keyboard(action: str, target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, удалить", callback_data=f"{action}!:{target_id}"),
                InlineKeyboardButton(text="Отмена", callback_data="refresh"),
            ]
        ]
    )


def move_keyboard(file_id: int, chain: list[Folder], folders: list[Folder]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"📁 {f.name}"[:60], callback_data=f"mvto:{file_id}:{f.id}")]
        for f in folders
    ]
    here = chain[-1].id if chain else 0
    rows.append(
        [InlineKeyboardButton(text="✅ Положить сюда", callback_data=f"mvto:{file_id}:{here}")]
    )
    if chain:
        parent = chain[-2].id if len(chain) > 1 else 0
        rows.append(
            [InlineKeyboardButton(text="⬅️ Наверх", callback_data=f"mvnav:{file_id}:{parent}")]
        )
    rows.append([InlineKeyboardButton(text="Отмена", callback_data=f"file:{file_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_results(files: list[File], query: str) -> str:
    if not files:
        return f"По запросу «{_esc(query)}» ничего не нашлось."
    lines = [f"Найдено файлов: {len(files)}"]
    return "\n".join(lines)


def search_keyboard(files: list[File]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"📄 {f.name}"[:60], callback_data=f"file:{f.id}")]
        for f in files
    ]
    rows.append([InlineKeyboardButton(text="⬅️ К хранилищу", callback_data="refresh")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


WELCOME = (
    "📦 <b>Файловое хранилище</b>\n\n"
    "Складывайте файлы в папки и забирайте их обратно в любой момент.\n\n"
    "• пришлите любой файл — он ляжет в открытую сейчас папку\n"
    "• «➕ Папка» — создать папку внутри текущей\n"
    "• нажмите на файл — скачать, переименовать, переместить или удалить\n"
    "• «⬇️ Скачать всё (ZIP)» — выгрузить папку целиком одним архивом\n"
    "• /find текст — найти файл по имени\n\n"
    "Ограничение Telegram: боту доступны файлы до 20 МБ."
)

HELP = (
    "<b>Команды</b>\n\n"
    "/start — открыть хранилище\n"
    "/tree — показать всё дерево папок\n"
    "/find текст — поиск файла по имени\n\n"
    "Чтобы загрузить файл, просто отправьте его в чат — он сохранится "
    "в той папке, которая открыта."
)
