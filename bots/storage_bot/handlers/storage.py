"""Хендлеры файлового хранилища.

Навигация построена на inline-клавиатуре: одно сообщение-«окно», которое
перерисовывается при переходах по папкам. Загрузка — обычной отправкой файла
в чат: он попадает в открытую сейчас папку. Выгрузка — кнопкой у файла или
архивом для папки целиком.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from ..services.database import Database, File
from ..services.storage import Storage, human_size, safe_name
from . import ui

router = Router()
log = logging.getLogger("storage-bot")

# заполняется в main.py при старте
db: Database = None  # type: ignore[assignment]
storage: Storage = None  # type: ignore[assignment]

# Telegram отдаёт ботам файлы не больше 20 МБ и принимает от них не больше 50 МБ
DOWNLOAD_LIMIT = 20 * 1024 * 1024
UPLOAD_LIMIT = 50 * 1024 * 1024


class Ask(StatesGroup):
    folder_name = State()
    rename_folder = State()
    rename_file = State()


# ---------- показ папки ----------
async def _render(target: Message | CallbackQuery, user_id: int, page: int = 0) -> None:
    cwd = db.get_cwd(user_id)
    chain = db.breadcrumbs(user_id, cwd)
    folders = db.list_folders(user_id, cwd)
    files = db.list_files(user_id, cwd)
    text = ui.folder_view(chain, folders, files, page, db.total_size(user_id))
    markup = ui.browser_keyboard(chain, folders, files, page)
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=markup)
        except Exception:  # сообщение не изменилось — Telegram ругается, это не ошибка
            pass
    else:
        await target.answer(text, reply_markup=markup)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    db.set_cwd(message.from_user.id, None)
    await message.answer(ui.WELCOME)
    await _render(message, message.from_user.id)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(ui.HELP)


@router.message(Command("tree"))
async def cmd_tree(message: Message):
    uid = message.from_user.id
    lines: list[str] = ["📦 Хранилище"]

    def walk(parent: int | None, depth: int) -> None:
        pad = "   " * depth
        for f in db.list_folders(uid, parent):
            lines.append(f"{pad}📁 {f.name}")
            walk(f.id, depth + 1)
        for fl in db.list_files(uid, parent):
            lines.append(f"{pad}📄 {fl.name} · {human_size(fl.size)}")

    walk(None, 1)
    if len(lines) == 1:
        lines.append("   (пусто)")
    await message.answer("<pre>" + "\n".join(lines[:200]) + "</pre>")


@router.message(Command("find"))
async def cmd_find(message: Message):
    query = message.text.partition(" ")[2].strip()
    if not query:
        await message.answer("Формат: /find часть имени файла")
        return
    files = db.search(message.from_user.id, query)
    await message.answer(ui.search_results(files, query), reply_markup=ui.search_keyboard(files))


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()


@router.callback_query(F.data == "refresh")
async def cb_refresh(cb: CallbackQuery):
    await cb.answer()
    await _render(cb, cb.from_user.id)


@router.callback_query(F.data.startswith("page:"))
async def cb_page(cb: CallbackQuery):
    await cb.answer()
    await _render(cb, cb.from_user.id, page=int(cb.data.split(":")[1]))


@router.callback_query(F.data.startswith("cd:"))
async def cb_cd(cb: CallbackQuery):
    folder_id = int(cb.data.split(":")[1]) or None
    if folder_id is not None and db.get_folder(cb.from_user.id, folder_id) is None:
        folder_id = None
    db.set_cwd(cb.from_user.id, folder_id)
    await cb.answer()
    await _render(cb, cb.from_user.id)


# ---------- создание и переименование ----------
@router.callback_query(F.data == "mkdir")
async def cb_mkdir(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Ask.folder_name)
    await cb.answer()
    await cb.message.answer("Название новой папки? (/cancel — отмена)")


@router.callback_query(F.data.startswith("renfo:"))
async def cb_rename_folder(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Ask.rename_folder)
    await state.update_data(folder_id=int(cb.data.split(":")[1]))
    await cb.answer()
    await cb.message.answer("Новое название папки? (/cancel — отмена)")


@router.callback_query(F.data.startswith("renfi:"))
async def cb_rename_file(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Ask.rename_file)
    await state.update_data(file_id=int(cb.data.split(":")[1]))
    await cb.answer()
    await cb.message.answer("Новое имя файла? (/cancel — отмена)")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменил.")
    await _render(message, message.from_user.id)


@router.message(Ask.folder_name, F.text)
async def got_folder_name(message: Message, state: FSMContext):
    if message.text.startswith("/"):
        await cmd_cancel(message, state)
        return
    await state.clear()
    uid = message.from_user.id
    folder = db.create_folder(uid, db.get_cwd(uid), safe_name(message.text))
    await message.answer(f"Создана папка «{folder.name}».")
    await _render(message, uid)


@router.message(Ask.rename_folder, F.text)
async def got_folder_rename(message: Message, state: FSMContext):
    if message.text.startswith("/"):
        await cmd_cancel(message, state)
        return
    data = await state.get_data()
    await state.clear()
    name = db.rename_folder(message.from_user.id, data["folder_id"], safe_name(message.text))
    await message.answer(f"Теперь папка называется «{name}».")
    await _render(message, message.from_user.id)


@router.message(Ask.rename_file, F.text)
async def got_file_rename(message: Message, state: FSMContext):
    if message.text.startswith("/"):
        await cmd_cancel(message, state)
        return
    data = await state.get_data()
    await state.clear()
    name = db.rename_file(message.from_user.id, data["file_id"], safe_name(message.text))
    await message.answer(f"Теперь файл называется «{name}».")
    await _render(message, message.from_user.id)


# ---------- карточка файла ----------
@router.callback_query(F.data.startswith("file:"))
async def cb_file(cb: CallbackQuery):
    f = db.get_file(cb.from_user.id, int(cb.data.split(":")[1]))
    if f is None:
        await cb.answer("Файл уже удалён", show_alert=True)
        return
    chain = db.breadcrumbs(cb.from_user.id, f.folder_id)
    await cb.answer()
    await cb.message.edit_text(ui.file_card(f, chain), reply_markup=ui.file_keyboard(f))


@router.callback_query(F.data.startswith("dl:"))
async def cb_download(cb: CallbackQuery):
    f = db.get_file(cb.from_user.id, int(cb.data.split(":")[1]))
    if f is None:
        await cb.answer("Файл уже удалён", show_alert=True)
        return
    await cb.answer("Отправляю…")
    if f.tg_file_id:
        # быстрый путь: Telegram отдаёт свой же файл, без выгрузки с диска
        await cb.message.answer_document(f.tg_file_id, caption=f.name)
        return
    if not storage.exists(f.disk_path):
        await cb.message.answer("Файл потерян на диске — восстановить не получится.")
        return
    data = await asyncio.to_thread(storage.read, f.disk_path)
    await cb.message.answer_document(BufferedInputFile(data, filename=f.name))


# ---------- перемещение ----------
@router.callback_query(F.data.startswith("mv:"))
async def cb_move(cb: CallbackQuery):
    file_id = int(cb.data.split(":")[1])
    await _move_picker(cb, file_id, None)


@router.callback_query(F.data.startswith("mvnav:"))
async def cb_move_nav(cb: CallbackQuery):
    _, file_id, folder_id = cb.data.split(":")
    await _move_picker(cb, int(file_id), int(folder_id) or None)


async def _move_picker(cb: CallbackQuery, file_id: int, folder_id: int | None) -> None:
    uid = cb.from_user.id
    chain = db.breadcrumbs(uid, folder_id)
    folders = db.list_folders(uid, folder_id)
    await cb.answer()
    await cb.message.edit_text(
        f"Куда переместить?\nСейчас: <b>{ui.path_title(chain)}</b>",
        reply_markup=ui.move_keyboard(file_id, chain, folders),
    )


@router.callback_query(F.data.startswith("mvto:"))
async def cb_move_to(cb: CallbackQuery):
    _, file_id, folder_id = cb.data.split(":")
    db.move_file(cb.from_user.id, int(file_id), int(folder_id) or None)
    await cb.answer("Перемещено")
    db.set_cwd(cb.from_user.id, int(folder_id) or None)
    await _render(cb, cb.from_user.id)


# ---------- удаление ----------
@router.callback_query(F.data.startswith("rmfi:"))
async def cb_rm_file_ask(cb: CallbackQuery):
    f = db.get_file(cb.from_user.id, int(cb.data.split(":")[1]))
    if f is None:
        await cb.answer("Файл уже удалён", show_alert=True)
        return
    await cb.answer()
    await cb.message.edit_text(
        f"Удалить файл «{f.name}»? Это необратимо.",
        reply_markup=ui.confirm_keyboard("rmfi", f.id),
    )


@router.callback_query(F.data.startswith("rmfi!:"))
async def cb_rm_file(cb: CallbackQuery):
    f = db.delete_file(cb.from_user.id, int(cb.data.split(":")[1]))
    if f:
        await asyncio.to_thread(storage.remove, f.disk_path)
    await cb.answer("Удалено")
    await _render(cb, cb.from_user.id)


@router.callback_query(F.data.startswith("rmfo:"))
async def cb_rm_folder_ask(cb: CallbackQuery):
    folder_id = int(cb.data.split(":")[1])
    uid = cb.from_user.id
    f = db.get_folder(uid, folder_id)
    if f is None:
        await cb.answer("Папки уже нет", show_alert=True)
        return
    inside = len(db.walk_files(uid, folder_id))
    await cb.answer()
    await cb.message.edit_text(
        f"Удалить папку «{f.name}» вместе с содержимым?\n"
        f"Внутри файлов: {inside}. Это необратимо.",
        reply_markup=ui.confirm_keyboard("rmfo", folder_id),
    )


@router.callback_query(F.data.startswith("rmfo!:"))
async def cb_rm_folder(cb: CallbackQuery):
    uid = cb.from_user.id
    folder_id = int(cb.data.split(":")[1])
    folder = db.get_folder(uid, folder_id)
    parent = folder.parent_id if folder else None
    victims = db.delete_folder(uid, folder_id)
    for v in victims:
        await asyncio.to_thread(storage.remove, v.disk_path)
    db.set_cwd(uid, parent)
    await cb.answer(f"Удалено файлов: {len(victims)}")
    await _render(cb, uid)


# ---------- выгрузка папки архивом ----------
@router.callback_query(F.data == "zip")
async def cb_zip(cb: CallbackQuery):
    uid = cb.from_user.id
    cwd = db.get_cwd(uid)
    pairs = db.relative_paths(uid, cwd)
    if not pairs:
        await cb.answer("Здесь нечего выгружать", show_alert=True)
        return
    total = sum(f.size for _, f in pairs)
    if total > UPLOAD_LIMIT:
        await cb.answer(
            f"Слишком много: {human_size(total)}. Telegram примет архив до 50 МБ.",
            show_alert=True,
        )
        return
    await cb.answer("Собираю архив…")
    items = [(rel, f.disk_path) for rel, f in pairs]
    data = await asyncio.to_thread(storage.zip_files, items)
    chain = db.breadcrumbs(uid, cwd)
    name = (chain[-1].name if chain else "Хранилище") + ".zip"
    await cb.message.answer_document(
        BufferedInputFile(data, filename=safe_name(name)),
        caption=f"Файлов в архиве: {len(items)} · {human_size(len(data))}",
    )


# ---------- загрузка ----------
@router.message(F.document | F.photo | F.video | F.audio | F.voice)
async def on_upload(message: Message):
    uid = message.from_user.id
    incoming = _incoming(message)
    if incoming is None:
        return
    file_id, filename, size = incoming

    if size and size > DOWNLOAD_LIMIT:
        await message.answer(
            f"Файл {human_size(size)} — боту доступны файлы до {human_size(DOWNLOAD_LIMIT)}. "
            "Это ограничение Telegram, не хранилища."
        )
        return

    cwd = db.get_cwd(uid)
    chain = db.breadcrumbs(uid, cwd)
    rel_dir = "/".join(f.name for f in chain)

    buf = await message.bot.download(file_id)
    data = buf.read()

    path = await asyncio.to_thread(storage.path_for, uid, rel_dir, filename)
    await asyncio.to_thread(storage.write, path, data)
    saved = db.add_file(uid, cwd, safe_name(filename), len(data), str(path), file_id)

    await message.answer(
        f"Сохранено: <b>{saved.name}</b> ({human_size(saved.size)})\n"
        f"Папка: {ui.path_title(chain)}"
    )
    await _render(message, uid)


def _incoming(message: Message) -> tuple[str, str, int] | None:
    """(file_id, имя файла, размер) для любого типа вложения."""
    if message.document:
        d = message.document
        return d.file_id, d.file_name or "документ", d.file_size or 0
    if message.photo:
        p = message.photo[-1]
        return p.file_id, f"photo_{p.file_unique_id}.jpg", p.file_size or 0
    if message.video:
        v = message.video
        return v.file_id, v.file_name or f"video_{v.file_unique_id}.mp4", v.file_size or 0
    if message.audio:
        a = message.audio
        return a.file_id, a.file_name or f"audio_{a.file_unique_id}.mp3", a.file_size or 0
    if message.voice:
        v = message.voice
        return v.file_id, f"voice_{v.file_unique_id}.ogg", v.file_size or 0
    return None


@router.message(F.text)
async def fallback(message: Message):
    await message.answer(
        "Пришлите файл, чтобы сохранить его в открытую папку, "
        "или откройте хранилище командой /start."
    )


__all__ = ["File", "router"]
