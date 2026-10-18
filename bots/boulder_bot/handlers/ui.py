"""Клавиатуры и форматирование сообщений бота записи в скалодром."""

from __future__ import annotations

import html

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from botcore import dates


def _esc(s) -> str:
    return html.escape(str(s) if s is not None else "")


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="📅 Записаться"), KeyboardButton(text="🗂 Мои записи")],
        [KeyboardButton(text="❓ Задать вопрос"), KeyboardButton(text="ℹ️ Помощь")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="🛠 Админ")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Предстоящие записи", callback_data="adm:appts")],
            [InlineKeyboardButton(text="➕ Добавить услугу", callback_data="adm:service")],
            [InlineKeyboardButton(text="➕ Добавить слоты", callback_data="adm:slots")],
            [InlineKeyboardButton(text="➕ Добавить FAQ", callback_data="adm:faq")],
        ]
    )


def services_keyboard(services, prefix: str = "svc") -> InlineKeyboardMarkup:
    rows = []
    for s in services:
        price = f" — {s['price']} ₽" if s["price"] else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{s['name']}{price}", callback_data=f"{prefix}:{s['id']}"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dates_keyboard(service_id: int, date_list: list[str]) -> InlineKeyboardMarkup:
    rows, row = [], []
    for d in date_list[:12]:
        # d = YYYY-MM-DD -> отображаем DD.MM
        label = f"{d[8:10]}.{d[5:7]}"
        row.append(InlineKeyboardButton(text=label, callback_data=f"date:{service_id}:{d}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="‹ К занятиям", callback_data="back:svc")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def slots_keyboard(service_id: int, date_prefix: str, slots) -> InlineKeyboardMarkup:
    rows, row = [], []
    for s in slots:
        label = dates.fmt_local(s["starts_at"])[-5:]  # HH:MM
        row.append(InlineKeyboardButton(text=label, callback_data=f"slot:{s['id']}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [InlineKeyboardButton(text="‹ К датам", callback_data=f"back:date:{service_id}")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def appt_actions(appt_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✖️ Отменить запись", callback_data=f"cancel:{appt_id}")]
        ]
    )


def format_appt(appt) -> str:
    price = f"\n💳 {appt['price']} ₽" if appt["price"] else ""
    return (
        f"🧗 <b>{_esc(appt['service_name'])}</b>\n"
        f"📅 {dates.fmt_local(appt['starts_at'])}"
        f"{price}\n"
        f"👤 {_esc(appt['client'])}"
        + (f"\n📞 {_esc(appt['phone'])}" if appt["phone"] else "")
    )


def format_admin_appt(appt) -> str:
    phone = f" · 📞 {_esc(appt['phone'])}" if appt["phone"] else ""
    return (
        f"📅 {dates.fmt_local(appt['starts_at'])} — "
        f"<b>{_esc(appt['service_name'])}</b>\n"
        f"   👤 {_esc(appt['client'])}{phone}"
    )
