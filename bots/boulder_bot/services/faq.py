"""ИИ-помощник по частым вопросам.

Сопоставляет вопрос клиента с базой FAQ через семантическую близость
(стеммированный TF-IDF из botcore). Если близость выше порога — отдаёт
готовый ответ; иначе предлагает связаться с администратором.
Никаких облачных LLM, работает локально.
"""

from __future__ import annotations

from botcore import NLP

from .database import Database


class FAQMatcher:
    def __init__(self, db: Database, nlp: NLP, threshold: float = 0.15):
        self.db = db
        self.nlp = nlp
        self.threshold = threshold

    def answer(self, query: str) -> tuple[str, float] | None:
        """Возвращает (ответ, score) или None, если ничего близкого нет."""
        rows = self.db.all_faq()
        if not rows:
            return None
        # сопоставляем по вопросам (заодно учитываем текст ответа для контекста)
        corpus = [f"{r['question']} {r['answer']}" for r in rows]
        ranked = self.nlp.semantic_rank(query, corpus, top_k=1)
        if not ranked:
            return None
        idx, score = ranked[0]
        if score < self.threshold:
            return None
        return rows[idx]["answer"], round(score, 3)
