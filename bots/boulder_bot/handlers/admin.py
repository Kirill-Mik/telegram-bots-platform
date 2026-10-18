"""Минимальная админ-панель бота скалодрома.

Доступна пользователям из ADMIN_IDS (задаются в .env). Позволяет наполнять
бота без правки seed-файла:
  - добавить услугу (название; длительность; цена);
  - добавить слоты на дату (дата + список времён);
  - добавить запись в FAQ (вопрос, затем ответ);
  - посмотреть предстоящие записи.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from botcore import dates

from ..services.database import Database
from . import ui

router = Router()

db: Database | None = None
ADMIN_IDS: set[int] = set()


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return event.from_user is not None and event.from_user.id in ADMIN_IDS


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class AdminForm(StatesGroup):
    service = State()        # ввод «Название; минуты; цена»
    slots_service = State()  # выбор услуги для слотов
    slots_input = State()    # ввод «ДД.ММ ЧЧ:ММ ЧЧ:ММ …»
    faq_question = State()
    faq_answer = State()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------- Меню ----------
@router.message(F.text == "🛠 Админ")
async def admin_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=ui.admin_menu())


@router.callback_query(F.data == "adm:appts")
async def adm_appts(cb: CallbackQuery):
    appts = db.all_upcoming(_now_iso(), limit=50)
    if not appts:
        await cb.message.answer("Предстоящих записей нет.")
        await cb.answer()
        return
    blocks = [ui.format_admin_appt(a) for a in appts]
    await cb.message.answer(
        f"🛠 <b>Предстоящие записи</b> ({len(appts)}):\n\n" + "\n\n".join(blocks)
    )
    await cb.answer()


# ---------- Добавить услугу ----------
@router.callback_query(F.data == "adm:service")
async def adm_service_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminForm.service)
    await cb.message.answer(
        "Пришлите услугу в формате:\n"
        "<code>Название; длительность_минут; цена_₽</code>\n"
        "<i>Пример: Свободное лазание (день); 120; 700</i>\n"
        "Цену можно опустить."
    )
    await cb.answer()


@router.message(AdminForm.service, F.text)
async def adm_service_save(message: Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split(";")]
    if not parts or len(parts[0]) < 3:
        await message.answer("Нужно хотя бы название (от 3 символов). Попробуйте ещё раз.")
        return
    name = parts[0]
    try:
        duration = int(parts[1]) if len(parts) > 1 and parts[1] else 60
        price = int(parts[2]) if len(parts) > 2 and parts[2] else None
    except ValueError:
        await message.answer("Длительность и цена должны быть числами. Попробуйте ещё раз.")
        return
    await state.clear()
    db.add_service(name, duration, price)
    price_str = f", {price} ₽" if price else ""
    await message.answer(
        f"✅ Услуга добавлена: <b>{ui._esc(name)}</b> ({duration} мин{price_str}).\n"
        f"Теперь добавьте слоты («➕ Добавить слоты»)."
    )


# ---------- Добавить слоты ----------
@router.callback_query(F.data == "adm:slots")
async def adm_slots_start(cb: CallbackQuery, state: FSMContext):
    services = db.list_services()
    if not services:
        await cb.answer("Сначала добавьте услугу", show_alert=True)
        return
    await state.set_state(AdminForm.slots_service)
    await cb.message.answer(
        "Для какой услуги добавить слоты?",
        reply_markup=ui.services_keyboard(services, prefix="admsvc"),
    )
    await cb.answer()


@router.callback_query(AdminForm.slots_service, F.data.startswith("admsvc:"))
async def adm_slots_service(cb: CallbackQuery, state: FSMContext):
    service_id = int(cb.data.split(":", 1)[1])
    svc = db.get_service(service_id)
    if not svc:
        await cb.answer("Услуга не найдена", show_alert=True)
        return
    await state.update_data(service_id=service_id)
    await state.set_state(AdminForm.slots_input)
    await cb.message.answer(
        f"Слоты для «<b>{ui._esc(svc['name'])}</b>».\n"
        "Пришлите дату и времена одной строкой:\n"
        "<code>ДД.ММ ЧЧ:ММ ЧЧ:ММ …</code>\n"
        "<i>Пример: 25.12 12:00 14:00 18:00</i>"
    )
    await cb.answer()


def _parse_slots_line(text: str) -> list[str] | None:
    """«ДД.ММ[.ГГГГ] ЧЧ:ММ ЧЧ:ММ …» -> список ISO-времён (UTC) или None."""
    tokens = text.split()
    if len(tokens) < 2:
        return None
    tz = dates.local_tz()
    today = datetime.now(tz).date()
    date_token = tokens[0]
    day = None
    for fmt in ("%d.%m.%Y", "%d.%m"):
        try:
            day = datetime.strptime(date_token, fmt).date()
            if fmt == "%d.%m":
                day = day.replace(year=today.year)
                if day < today:  # прошло в этом году — берём следующий
                    day = day.replace(year=today.year + 1)
            break
        except ValueError:
            continue
    if day is None:
        return None
    result = []
    for t in tokens[1:]:
        try:
            hh, mm = t.split(":")
            local_dt = datetime(day.year, day.month, day.day, int(hh), int(mm), tzinfo=tz)
        except ValueError:
            return None
        result.append(local_dt.astimezone(UTC).isoformat())
    return result


@router.message(AdminForm.slots_input, F.text)
async def adm_slots_save(message: Message, state: FSMContext):
    times = _parse_slots_line(message.text.strip())
    if not times:
        await message.answer(
            "Не понял формат. Пример: <code>25.12 12:00 14:00 18:00</code>. "
            "Попробуйте ещё раз."
        )
        return
    data = await state.get_data()
    await state.clear()
    added = skipped = 0
    for iso in times:
        if db.add_slot(data["service_id"], iso):
            added += 1
        else:
            skipped += 1
    note = f" (пропущено дублей: {skipped})" if skipped else ""
    await message.answer(f"✅ Добавлено слотов: {added}{note}.")


# ---------- Добавить FAQ ----------
@router.callback_query(F.data == "adm:faq")
async def adm_faq_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminForm.faq_question)
    await cb.message.answer("Пришлите текст вопроса:")
    await cb.answer()


@router.message(AdminForm.faq_question, F.text)
async def adm_faq_question(message: Message, state: FSMContext):
    question = message.text.strip()
    if len(question) < 5:
        await message.answer("Вопрос слишком короткий, попробуйте ещё раз.")
        return
    await state.update_data(question=question)
    await state.set_state(AdminForm.faq_answer)
    await message.answer("Теперь пришлите ответ на этот вопрос:")


@router.message(AdminForm.faq_answer, F.text)
async def adm_faq_answer(message: Message, state: FSMContext):
    answer = message.text.strip()
    if len(answer) < 5:
        await message.answer("Ответ слишком короткий, попробуйте ещё раз.")
        return
    data = await state.get_data()
    await state.clear()
    db.add_faq(data["question"], answer)
    await message.answer(
        "✅ FAQ-запись добавлена. ИИ-помощник сразу начнёт использовать её "
        "при ответах на вопросы."
    )
