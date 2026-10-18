"""Тесты файлового хранилища: дерево папок, коллизии имён, выгрузка архивом."""

from __future__ import annotations

import io
import zipfile

import pytest

from bots.storage_bot.services.database import Database
from bots.storage_bot.services.storage import Storage, human_size, safe_name

USER = 777


@pytest.fixture()
def db(tmp_path):
    d = Database(str(tmp_path / "storage.db"))
    yield d
    d.close()


@pytest.fixture()
def storage(tmp_path):
    return Storage(tmp_path / "files")


def _put(db: Database, storage: Storage, folder_id, name: str, body: bytes = b"x"):
    chain = db.breadcrumbs(USER, folder_id)
    rel = "/".join(f.name for f in chain)
    path = storage.path_for(USER, rel, name)
    storage.write(path, body)
    return db.add_file(USER, folder_id, name, len(body), str(path))


# ---------- дерево ----------
def test_nested_folders_and_breadcrumbs(db):
    clients = db.create_folder(USER, None, "Клиенты")
    contracts = db.create_folder(USER, clients.id, "Договоры")

    assert [f.name for f in db.list_folders(USER, None)] == ["Клиенты"]
    assert [f.name for f in db.list_folders(USER, clients.id)] == ["Договоры"]
    assert [f.name for f in db.breadcrumbs(USER, contracts.id)] == ["Клиенты", "Договоры"]


def test_files_live_in_their_folder(db, storage):
    folder = db.create_folder(USER, None, "Отчёты")
    _put(db, storage, folder.id, "март.pdf")
    _put(db, storage, None, "корневой.txt")

    assert [f.name for f in db.list_files(USER, folder.id)] == ["март.pdf"]
    assert [f.name for f in db.list_files(USER, None)] == ["корневой.txt"]


def test_users_do_not_see_each_other(db, storage):
    db.create_folder(USER, None, "Моя")
    db.create_folder(999, None, "Чужая")
    assert [f.name for f in db.list_folders(USER, None)] == ["Моя"]
    assert [f.name for f in db.list_folders(999, None)] == ["Чужая"]


# ---------- коллизии имён ----------
def test_duplicate_file_name_gets_suffix(db, storage):
    a = _put(db, storage, None, "отчёт.pdf")
    b = _put(db, storage, None, "отчёт.pdf")
    assert a.name == "отчёт.pdf"
    assert b.name == "отчёт (2).pdf"


def test_same_name_allowed_in_different_folders(db, storage):
    one = db.create_folder(USER, None, "Январь")
    two = db.create_folder(USER, None, "Февраль")
    assert _put(db, storage, one.id, "смета.xlsx").name == "смета.xlsx"
    assert _put(db, storage, two.id, "смета.xlsx").name == "смета.xlsx"


def test_duplicate_folder_name_gets_suffix(db):
    assert db.create_folder(USER, None, "Архив").name == "Архив"
    assert db.create_folder(USER, None, "Архив").name == "Архив (2)"


# ---------- операции ----------
def test_move_file_between_folders(db, storage):
    src = db.create_folder(USER, None, "Входящие")
    dst = db.create_folder(USER, None, "Обработано")
    f = _put(db, storage, src.id, "скан.jpg")

    db.move_file(USER, f.id, dst.id)

    assert db.list_files(USER, src.id) == []
    assert [x.name for x in db.list_files(USER, dst.id)] == ["скан.jpg"]


def test_rename_file_keeps_it_in_place(db, storage):
    folder = db.create_folder(USER, None, "Документы")
    f = _put(db, storage, folder.id, "старое.txt")
    new_name = db.rename_file(USER, f.id, "новое.txt")
    assert new_name == "новое.txt"
    assert [x.name for x in db.list_files(USER, folder.id)] == ["новое.txt"]


def test_delete_folder_removes_nested_files(db, storage):
    root = db.create_folder(USER, None, "Проект")
    sub = db.create_folder(USER, root.id, "Материалы")
    _put(db, storage, root.id, "бриф.pdf")
    _put(db, storage, sub.id, "лого.png")

    victims = db.delete_folder(USER, root.id)

    assert {v.name for v in victims} == {"бриф.pdf", "лого.png"}
    assert db.list_folders(USER, None) == []
    assert db.list_files(USER, None) == []


def test_search_by_name(db, storage):
    _put(db, storage, None, "договор_аренды.pdf")
    _put(db, storage, None, "смета.xlsx")
    assert [f.name for f in db.search(USER, "договор")] == ["договор_аренды.pdf"]
    assert db.search(USER, "накладная") == []


def test_total_size_sums_all_files(db, storage):
    _put(db, storage, None, "a.bin", b"12345")
    _put(db, storage, None, "b.bin", b"123")
    assert db.total_size(USER) == 8


# ---------- выгрузка ----------
def test_zip_preserves_folder_structure(db, storage):
    root = db.create_folder(USER, None, "Клиент")
    sub = db.create_folder(USER, root.id, "Договоры")
    _put(db, storage, root.id, "контакты.txt", b"phone")
    _put(db, storage, sub.id, "договор.pdf", b"pdf-bytes")

    pairs = db.relative_paths(USER, root.id)
    data = storage.zip_files([(rel, f.disk_path) for rel, f in pairs])

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert sorted(zf.namelist()) == ["Договоры/договор.pdf", "контакты.txt"]
        assert zf.read("Договоры/договор.pdf") == b"pdf-bytes"


def test_zip_skips_files_missing_on_disk(db, storage):
    f = _put(db, storage, None, "исчез.txt", b"data")
    storage.remove(f.disk_path)
    data = storage.zip_files([("исчез.txt", f.disk_path)])
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.namelist() == []


# ---------- имена и размеры ----------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("обычное.pdf", "обычное.pdf"),
        ("сле/ш\\и:*.txt", "сле_ш_и__.txt"),
        ("   ", "без_имени"),
        ("CON.txt", "_CON.txt"),
    ],
)
def test_safe_name(raw, expected):
    assert safe_name(raw) == expected


def test_safe_name_truncates_long_names():
    assert len(safe_name("я" * 500)) <= 120


def test_human_size():
    assert human_size(512) == "512 Б"
    assert human_size(2048) == "2.0 КБ"
    assert human_size(5 * 1024 * 1024) == "5.0 МБ"


# ---------- текущая папка ----------
def test_cwd_resets_when_folder_deleted(db):
    folder = db.create_folder(USER, None, "Временная")
    db.set_cwd(USER, folder.id)
    assert db.get_cwd(USER) == folder.id

    db.delete_folder(USER, folder.id)
    assert db.get_cwd(USER) is None
