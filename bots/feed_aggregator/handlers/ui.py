"""Клавиатуры и форматирование сообщений агрегатора.

В callback_data кладём только числовые id (лимит Telegram — 64 байта,
кириллическое название темы легко его превышает).
"""

from __future__ import annotations

import html

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📰 Дайджест"), KeyboardButton(text="🔄 Обновить")],
            [KeyboardButton(text="🏷 Темы"), KeyboardButton(text="📡 Источники")],
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
    )


def _esc(s: str) -> str:
    return html.escape(s or "")


def sources_keyboard(sources) -> InlineKeyboardMarkup | None:
    if not sources:
        return None
    rows = [
        [
            InlineKeyboardButton(
                text=f"🗑 {(_esc(s['title'] or s['url']))[:30]}",
                callback_data=f"src_del:{s['id']}",
            )
        ]
        for s in sources
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def topics_keyboard(topic_rows) -> InlineKeyboardMarkup | None:
    """topic_rows — строки таблицы topics (id, name). callback — по id."""
    if not topic_rows:
        return None
    rows = []
    for t in topic_rows:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📂 {t['name']}", callback_data=f"topic_show:{t['id']}"
                ),
                InlineKeyboardButton(text="🗑", callback_data=f"topic_del:{t['id']}"),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_post(p, index: int | None = None) -> str:
    prefix = f"{index}. " if index else ""
    topic = f"  📂 <b>{_esc(p['topic'])}</b>" if p["topic"] else ""
    score = ""
    if p["score"] is not None and p["topic"]:
        score = f" ({round(p['score'] * 100)}%)"
    link = f"\n🔗 {_esc(p['url'])}" if p["url"] else ""
    summary = _esc((p["summary"] or "")[:220])
    return f"📰 <b>{prefix}{_esc(p['title'])}</b>{topic}{score}\n<i>{summary}</i>{link}"


def format_digest(posts) -> str:
    if not posts:
        return "Новых записей нет."
    # группируем по темам
    by_topic: dict[str, list] = {}
    for p in posts:
        key = p["topic"] or "Без темы"
        by_topic.setdefault(key, []).append(p)
    blocks = [f"📬 <b>Новый дайджест</b> — {len(posts)} записей\n"]
    for topic, items in by_topic.items():
        blocks.append(f"\n━━ <b>{_esc(topic)}</b> ({len(items)}) ━━")
        for p in items[:8]:
            link = f"\n   🔗 {_esc(p['url'])}" if p["url"] else ""
            blocks.append(f"• {_esc(p['title'])}{link}")
    return "\n".join(blocks)
