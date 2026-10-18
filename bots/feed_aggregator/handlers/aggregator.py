"""Хендлеры бота-агрегатора.

Сценарии:
  - /start, помощь
  - добавление источника: «📡 Источники» -> ввод URL ленты
  - добавление темы: «🏷 Темы» -> ввод «Название: слово1, слово2, ...»
  - дайджест непрочитанного, обновление вручную, статистика
  - просмотр постов по теме, удаление источников/тем (по числовым id)

FSM-состояния разделяют ввод URL и ввод темы от обычных нажатий кнопок.
"""

from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..services.database import Database
from ..services.fetcher import FeedFetcher
from . import ui

router = Router()

# внедряются из main.py
db: Database | None = None
fetcher: FeedFetcher | None = None
scheduler = None  # PollScheduler


class Flow(StatesGroup):
    add_source = State()
    add_topic = State()


WELCOME = (
    "👋 <b>ИИ-агрегатор новостей</b>\n\n"
    "Я собираю записи из RSS-лент, раскладываю их по вашим темам с помощью "
    "ИИ-классификации и присылаю дайджесты.\n\n"
    "С чего начать:\n"
    "1️⃣ «📡 Источники» — добавьте RSS-ленты\n"
    "2️⃣ «🏷 Темы» — задайте темы ключевыми словами\n"
    "3️⃣ «🔄 Обновить» — собрать записи прямо сейчас\n"
    "4️⃣ «📰 Дайджест» — свежее, разложенное по темам\n\n"
    "Темы — это «настраиваемые признаки»: вы описываете тему словами, "
    "обучать ничего не нужно."
)

HELP = (
    "<b>Команды и кнопки</b>\n\n"
    "📡 <b>Источники</b> — список лент; чтобы добавить, пришлите URL RSS.\n"
    "🏷 <b>Темы</b> — список тем; чтобы добавить, пришлите строку вида:\n"
    "<code>Финансы: ставка, кредит, инвестиции, рубль</code>\n"
    "🔄 <b>Обновить</b> — опросить ленты сейчас.\n"
    "📰 <b>Дайджест</b> — новые записи по темам.\n"
    "📊 <b>Статистика</b> — сколько собрано и по каким темам.\n\n"
    "Записи без подходящей темы помечаются как «Без темы»."
)


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(WELCOME, reply_markup=ui.main_menu())


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    await message.answer(HELP, reply_markup=ui.main_menu())


# ---------- Источники ----------
@router.message(F.text == "📡 Источники")
async def btn_sources(message: Message, state: FSMContext):
    sources = db.list_sources(message.from_user.id)
    if sources:
        text = "<b>Ваши источники:</b>\n\n" + "\n".join(
            f"• {ui._esc(s['title'] or s['url'])}" for s in sources
        )
        await message.answer(text, reply_markup=ui.sources_keyboard(sources))
    await message.answer(
        "Пришлите URL RSS-ленты, чтобы добавить источник.\n"
        "<i>Пример: https://habr.com/ru/rss/all/all/</i>"
    )
    await state.set_state(Flow.add_source)


@router.message(Flow.add_source, F.text)
async def on_add_source(message: Message, state: FSMContext):
    await state.clear()
    url = message.text.strip()
    if not url.startswith(("http://", "https://")):
        await message.answer("Это не похоже на URL. Нужна ссылка на RSS-ленту.")
        return
    await message.answer("⏳ Проверяю ленту…")
    ok, title = await asyncio.to_thread(fetcher.fetch_feed_meta, url)
    if not ok:
        await message.answer("Не удалось прочитать ленту по этому адресу.")
        return
    sid = db.add_source(message.from_user.id, url, title)
    if sid is None:
        await message.answer("Этот источник уже добавлен.")
        return
    await message.answer(
        f"✅ Добавлено: <b>{ui._esc(title)}</b>\n"
        f"Нажмите «🔄 Обновить», чтобы собрать записи."
    )


# ---------- Темы ----------
@router.message(F.text == "🏷 Темы")
async def btn_topics(message: Message, state: FSMContext):
    topic_rows = db.list_topics(message.from_user.id)
    if topic_rows:
        import json

        lines = [
            f"• <b>{ui._esc(t['name'])}</b>: "
            f"{ui._esc(', '.join(json.loads(t['keywords'])))}"
            for t in topic_rows
        ]
        await message.answer(
            "<b>Ваши темы:</b>\n\n" + "\n".join(lines),
            reply_markup=ui.topics_keyboard(topic_rows),
        )
    await message.answer(
        "Пришлите тему в формате <code>Название: слово1, слово2, ...</code>\n"
        "<i>Пример: Технологии: нейросеть, ИИ, гаджеты, стартап</i>"
    )
    await state.set_state(Flow.add_topic)


@router.message(Flow.add_topic, F.text)
async def on_add_topic(message: Message, state: FSMContext):
    await state.clear()
    raw = message.text.strip()
    if ":" not in raw:
        await message.answer("Нужен формат «Название: слово1, слово2».")
        return
    name, kw_str = raw.split(":", 1)
    name = name.strip()
    keywords = [k.strip() for k in kw_str.split(",") if k.strip()]
    if not name or not keywords:
        await message.answer("Укажите название темы и хотя бы одно ключевое слово.")
        return
    db.add_topic(message.from_user.id, name, keywords)
    await message.answer(
        f"✅ Тема <b>{ui._esc(name)}</b> сохранена ({len(keywords)} ключевых слов).\n"
        f"Новые записи будут классифицироваться по ней."
    )


# ---------- Обновление и дайджест ----------
@router.message(F.text == "🔄 Обновить")
async def btn_refresh(message: Message):
    sources = db.list_sources(message.from_user.id)
    if not sources:
        await message.answer("Сначала добавьте хотя бы один источник («📡 Источники»).")
        return
    await message.answer("⏳ Опрашиваю источники…")
    new_count = await scheduler.poll_now(message.from_user.id)
    if new_count:
        await message.answer(
            f"Готово: собрано новых записей — {new_count}. "
            f"Нажмите «📰 Дайджест»."
        )
    else:
        await message.answer("Новых записей нет.")


@router.message(F.text == "📰 Дайджест")
async def btn_digest(message: Message):
    posts = db.unseen_posts(message.from_user.id, limit=50)
    if not posts:
        await message.answer(
            "Непрочитанных записей нет. Нажмите «🔄 Обновить», чтобы собрать свежие."
        )
        return
    await message.answer(ui.format_digest(posts))
    db.mark_seen(message.from_user.id, [p["id"] for p in posts])


@router.message(F.text == "📊 Статистика")
async def btn_stats(message: Message):
    s = db.stats(message.from_user.id)
    lines = [
        f"📡 Источников: <b>{s['sources']}</b>",
        f"📰 Всего записей: <b>{s['total']}</b>",
        "",
        "<b>По темам:</b>",
    ]
    if s["by_topic"]:
        for topic, count in s["by_topic"].items():
            lines.append(f"• {ui._esc(topic)}: {count}")
    else:
        lines.append("— пока пусто")
    await message.answer("\n".join(lines))


# ---------- Callback ----------
@router.callback_query(F.data.startswith("src_del:"))
async def cb_src_del(cb: CallbackQuery):
    sid = int(cb.data.split(":", 1)[1])
    ok = db.remove_source(cb.from_user.id, sid)
    await cb.answer("Удалено" if ok else "Не найдено")
    if ok and cb.message:
        await cb.message.edit_text("🗑 Источник удалён.")


@router.callback_query(F.data.startswith("topic_del:"))
async def cb_topic_del(cb: CallbackQuery):
    topic_id = int(cb.data.split(":", 1)[1])
    topic = db.get_topic(cb.from_user.id, topic_id)
    ok = topic is not None and db.remove_topic(cb.from_user.id, topic_id)
    await cb.answer("Удалено" if ok else "Не найдено")
    if ok and cb.message:
        await cb.message.edit_text(f"🗑 Тема «{ui._esc(topic['name'])}» удалена.")


@router.callback_query(F.data.startswith("topic_show:"))
async def cb_topic_show(cb: CallbackQuery):
    topic_id = int(cb.data.split(":", 1)[1])
    topic = db.get_topic(cb.from_user.id, topic_id)
    if not topic:
        await cb.answer("Тема не найдена", show_alert=True)
        return
    posts = db.posts_by_topic(cb.from_user.id, topic["name"], limit=10)
    if not posts:
        await cb.answer("По этой теме пока нет записей", show_alert=True)
        return
    blocks = [ui.format_post(p, i) for i, p in enumerate(posts, 1)]
    await cb.message.answer(
        f"📂 <b>{ui._esc(topic['name'])}</b> — последние записи:\n\n"
        + "\n\n".join(blocks)
    )
    await cb.answer()
