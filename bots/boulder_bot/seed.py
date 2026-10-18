"""Демо-наполнение для бота записи в скалодром.

Создаёт типовые занятия, слоты на ближайшие дни и базу FAQ.
Запуск из корня монорепо:  python -m bots.boulder_bot.seed

Наполнять бота можно и без seed — через встроенную админ-панель
(кнопка «🛠 Админ» для пользователей из ADMIN_IDS).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from .services.database import Database


def main():
    db_path = os.getenv("DB_PATH", "data/boulder.db")
    db = Database(db_path)

    if db.list_services():
        print("В базе уже есть занятия — пропускаю seed.")
        return

    s_trial = db.add_service("Пробное занятие с инструктором", 60, 1200)
    s_open = db.add_service("Свободное лазание (день)", 120, 700)
    s_kids = db.add_service("Детская секция (6–12 лет)", 60, 900)

    # слоты на ближайшие 5 дней, рабочие часы 12-22
    now = datetime.now(UTC)
    added = 0
    for day in range(1, 6):
        date = (now + timedelta(days=day)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        for hour in (12, 14, 16, 18, 19, 20):
            for svc in (s_trial, s_open, s_kids):
                slot = date.replace(hour=hour)
                if db.add_slot(svc, slot.isoformat()):
                    added += 1

    faqs = [
        ("Сколько стоит свободное лазание?",
         "Дневной абонемент на свободное лазание — 700 рублей, без ограничения "
         "по времени в течение дня."),
        ("Нужна ли своя обувь?",
         "Скальники можно взять в прокат за 250 рублей. Магнезия выдаётся "
         "бесплатно. Нужна только удобная спортивная одежда."),
        ("Вы работаете по выходным?",
         "Да, в выходные зал открыт с 10:00 до 22:00. В будни — с 12:00 до 23:00."),
        ("Можно ли новичку без опыта?",
         "Конечно! Начните с пробного занятия с инструктором — научим базовой "
         "технике лазания и безопасному спрыгиванию на боулдеринге."),
        ("Можно ли оплатить картой?",
         "Да, мы принимаем наличные, банковские карты и оплату по QR-коду. "
         "Абонементы — тоже."),
        ("Как отменить или перенести запись?",
         "Отменить запись можно в боте в разделе «Мои записи». Для переноса "
         "отмените текущую и выберите новое время."),
    ]
    for q, a in faqs:
        db.add_faq(q, a)

    print(
        f"Готово: занятий — {len(db.list_services())}, слотов — {added}, "
        f"FAQ — {len(db.all_faq())}."
    )
    db.close()


if __name__ == "__main__":
    main()
