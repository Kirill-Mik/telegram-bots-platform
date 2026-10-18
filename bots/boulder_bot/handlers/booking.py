"""Хендлеры бота записи в скалодром (клиентская часть).

Сценарий записи (callback-навигация):
  занятие -> дата -> время -> ввод имени -> ввод телефона (опц.) -> бронь.

Прочее:
  - «Мои записи»: список будущих сессий с возможностью отмены;
  - «Задать вопрос»: ИИ-помощник по FAQ (семантический поиск).

Админ-панель — в handlers/admin.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..services.database import Database
from ..services.faq import FAQMatcher
from . import ui

router = Router()

db: Database | None = None
faq: FAQMatcher | None = None

ADMIN_IDS: set[int] = set()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Booking(StatesGroup):
    name = State()
    phone = State()


class Ask(StatesGroup):
    waiting = State()


WELCOME = (
    "🧗 <b>Скалодром «Зацеп»</b>\n\n"
    "Здесь можно записаться на занятие, посмотреть свои сессии и задать "
    "вопрос — на частые вопросы я отвечаю сам.\n\n"
    "• «📅 Записаться» — выбрать занятие и время\n"
    "• «🗂 Мои записи» — посмотреть и отменить сессию\n"
    "• «❓ Задать вопрос» — быстрый ответ по занятиям, ценам, режиму"
)

HELP = (
    "<b>Как пользоваться</b>\n\n"
    "📅 <b>Записаться</b> — выберите занятие, затем дату и время. "
    "Понадобится имя и (по желанию) телефон.\n"
    "🗂 <b>Мои записи</b> — список будущих сессий; здесь же можно отменить.\n"
    "❓ <b>Задать вопрос</b> — спросите про цены, режим работы, прокат, оплату. "
    "Если не найду ответ — подскажу, как связаться с администратором.\n\n"
    "🔔 За сутки до занятия пришлю напоминание."
)


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(WELCOME, reply_markup=ui.main_menu(_is_admin(message.from_user.id)))


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    await message.answer(HELP, reply_markup=ui.main_menu(_is_admin(message.from_user.id)))


# ---------- Запись: выбор занятия ----------
@router.message(F.text == "📅 Записаться")
async def book_start(message: Message, state: FSMContext):
    await state.clear()
    services = db.list_services()
    if not services:
        await message.answer("Пока нет доступных занятий. Загляните позже.")
        return
    await message.answer("Выберите занятие:", reply_markup=ui.services_keyboard(services))


@router.callback_query(F.data == "back:svc")
async def back_to_services(cb: CallbackQuery):
    services = db.list_services()
    await cb.message.edit_text("Выберите занятие:", reply_markup=ui.services_keyboard(services))
    await cb.answer()


@router.callback_query(F.data.startswith("svc:"))
async def choose_service(cb: CallbackQuery):
    service_id = int(cb.data.split(":", 1)[1])
    date_list = db.free_dates(service_id, _now_iso())
    if not date_list:
        await cb.answer("На это занятие пока нет свободного времени", show_alert=True)
        return
    svc = db.get_service(service_id)
    await cb.message.edit_text(
        f"<b>{ui._esc(svc['name'])}</b>\nВыберите дату:",
        reply_markup=ui.dates_keyboard(service_id, date_list),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("date:"))
async def choose_date(cb: CallbackQuery):
    _, service_id, date_prefix = cb.data.split(":")
    slots = db.free_slots(int(service_id), date_prefix, _now_iso())
    if not slots:
        await cb.answer("Это время уже разобрали, выберите другую дату", show_alert=True)
        return
    await cb.message.edit_text(
        "Выберите время:",
        reply_markup=ui.slots_keyboard(int(service_id), date_prefix, slots),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("back:date:"))
async def back_to_dates(cb: CallbackQuery):
    service_id = int(cb.data.split(":")[2])
    date_list = db.free_dates(service_id, _now_iso())
    svc = db.get_service(service_id)
    await cb.message.edit_text(
        f"<b>{ui._esc(svc['name'])}</b>\nВыберите дату:",
        reply_markup=ui.dates_keyboard(service_id, date_list),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("slot:"))
async def choose_slot(cb: CallbackQuery, state: FSMContext):
    slot_id = int(cb.data.split(":", 1)[1])
    slot = db.get_slot(slot_id)
    if not slot or slot["booked"]:
        await cb.answer("Это время только что заняли. Выберите другое.", show_alert=True)
        return
    await state.update_data(slot_id=slot_id)
    await state.set_state(Booking.name)
    await cb.message.edit_text("Как вас зовут? Напишите имя для записи:")
    await cb.answer()


@router.message(Booking.name, F.text)
async def booking_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Введите имя (минимум 2 символа).")
        return
    await state.update_data(name=name)
    await state.set_state(Booking.phone)
    await message.answer(
        "Оставьте телефон для связи или напишите «-», чтобы пропустить:"
    )


@router.message(Booking.phone, F.text)
async def booking_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if phone in {"-", "—", "нет", "skip"}:
        phone = None
    data = await state.get_data()
    await state.clear()

    appt_id = db.book(data["slot_id"], message.from_user.id, data["name"], phone)
    if appt_id is None:
        await message.answer(
            "К сожалению, это время только что заняли. Попробуйте записаться заново.",
            reply_markup=ui.main_menu(_is_admin(message.from_user.id)),
        )
        return
    appt = _appt_by_id(message.from_user.id, appt_id)
    await message.answer(
        "✅ <b>Вы записаны!</b>\n\n" + ui.format_appt(appt),
        reply_markup=ui.main_menu(_is_admin(message.from_user.id)),
    )


def _appt_by_id(user_id: int, appt_id: int):
    for a in db.my_appointments(user_id):
        if a["id"] == appt_id:
            return a
    return None


# ---------- Мои записи ----------
@router.message(F.text == "🗂 Мои записи")
async def my_appts(message: Message):
    appts = db.my_appointments(message.from_user.id)
    if not appts:
        await message.answer("У вас нет предстоящих записей. Нажмите «📅 Записаться».")
        return
    for a in appts:
        await message.answer(ui.format_appt(a), reply_markup=ui.appt_actions(a["id"]))


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_appt(cb: CallbackQuery):
    appt_id = int(cb.data.split(":", 1)[1])
    ok = db.cancel(appt_id, cb.from_user.id)
    await cb.answer("Запись отменена" if ok else "Не удалось отменить")
    if ok and cb.message:
        await cb.message.edit_text("✖️ Запись отменена. Время снова свободно для брони.")


# ---------- FAQ ----------
@router.message(F.text == "❓ Задать вопрос")
async def ask_start(message: Message, state: FSMContext):
    await state.set_state(Ask.waiting)
    await message.answer(
        "Напишите ваш вопрос — про цены, занятия, прокат, режим работы или оплату."
    )


@router.message(Ask.waiting, F.text)
async def ask_answer(message: Message, state: FSMContext):
    await state.clear()
    result = faq.answer(message.text.strip())
    if result:
        answer, _score = result
        await message.answer(
            f"{answer}\n\n<i>Если остались вопросы — напишите ещё раз или "
            f"свяжитесь с администратором.</i>",
            reply_markup=ui.main_menu(_is_admin(message.from_user.id)),
        )
    else:
        await message.answer(
            "Не нашёл точного ответа на этот вопрос. Лучше уточнить у "
            "администратора — напишите @gym_admin или позвоните на ресепшн.",
            reply_markup=ui.main_menu(_is_admin(message.from_user.id)),
        )
