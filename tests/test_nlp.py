"""Тесты NLP-ядра: стемминг, ранжирование, теги, классификация тем.

Всё офлайн, на маленьком корпусе.
"""

from botcore import NLP

DOCS = [
    "Рецепт борща: свёклу натереть, капусту нашинковать, варить час.",
    "Настройка веб-сервера nginx: конфигурация, прокси и кэширование.",
    "Как выбрать скальные туфли для боулдеринга новичку.",
]


def make_nlp() -> NLP:
    return NLP("ru")


class TestSemanticRank:
    def test_finds_doc_by_word_form(self):
        """Стемминг: запрос «свёкла» находит документ со «свёклу»."""
        nlp = make_nlp()
        ranked = nlp.semantic_rank("свёкла", DOCS)
        assert ranked, "ожидали хотя бы одно совпадение"
        top_idx, top_score = ranked[0]
        assert top_idx == 0
        assert top_score > 0

    def test_ranks_relevant_doc_first(self):
        nlp = make_nlp()
        ranked = nlp.semantic_rank("конфигурация сервера nginx", DOCS)
        assert ranked[0][0] == 1

    def test_empty_inputs(self):
        nlp = make_nlp()
        assert nlp.semantic_rank("", DOCS) == []
        assert nlp.semantic_rank("свёкла", []) == []

    def test_no_match_returns_empty(self):
        nlp = make_nlp()
        ranked = nlp.semantic_rank("квантовая хромодинамика", DOCS)
        assert ranked == []


class TestTfidfIndex:
    def test_index_matches_one_off_ranking(self):
        """Кэшированный индекс даёт тот же результат, что одноразовое ранжирование."""
        nlp = make_nlp()
        index = nlp.build_index(DOCS)
        assert index.rank("свёкла для борща") == nlp.semantic_rank("свёкла для борща", DOCS)

    def test_index_reusable_for_many_queries(self):
        nlp = make_nlp()
        index = nlp.build_index(DOCS)
        assert index.rank("нашинковать капусту")[0][0] == 0
        assert index.rank("прокси и кэширование")[0][0] == 1
        assert index.rank("туфли для лазания")[0][0] == 2

    def test_empty_corpus(self):
        nlp = make_nlp()
        index = nlp.build_index([])
        assert index.empty
        assert index.rank("что угодно") == []


class TestSummary:
    def test_summarize_short_text_as_is(self):
        nlp = make_nlp()
        text = "Короткий текст без изменений."
        assert nlp.summarize(text) == text


class TestTopicClassifier:
    TOPICS = {
        "Финансы": ["ставка", "кредит", "банк", "рубль", "инвестиции"],
        "Спорт": ["матч", "гол", "турнир", "чемпионат"],
    }

    def test_classifies_finance_text(self):
        nlp = make_nlp()
        clf = nlp.topic_classifier(self.TOPICS)
        best = clf.best("ЦБ поднял ключевую ставку, банки ждут роста кредитов")
        assert best is not None
        assert best[0] == "Финансы"
        assert best[1] > 0.05

    def test_classifies_sport_text(self):
        clf = make_nlp().topic_classifier(self.TOPICS)
        best = clf.best("Гол на последней минуте принёс победу в матче чемпионата")
        assert best is not None
        assert best[0] == "Спорт"

    def test_unrelated_text_below_threshold(self):
        clf = make_nlp().topic_classifier(self.TOPICS)
        assert clf.best("Сегодня солнечная погода и лёгкий ветер") is None

    def test_classifier_is_reusable(self):
        """Один классификатор обслуживает много текстов (fit — один раз)."""
        clf = make_nlp().topic_classifier(self.TOPICS)
        texts = [
            "банк снизил ставку по кредиту",
            "турнир завершился голом",
            "ставка на инвестиции в рублях",
        ]
        results = [clf.best(t) for t in texts]
        assert [r[0] for r in results] == ["Финансы", "Спорт", "Финансы"]

    def test_empty_topics(self):
        clf = make_nlp().topic_classifier({})
        assert clf.empty
        assert clf.best("любой текст") is None

    def test_one_off_helpers_match_classifier(self):
        nlp = make_nlp()
        text = "банк поднял ставку по кредитам"
        assert nlp.best_topic(text, self.TOPICS) == nlp.topic_classifier(self.TOPICS).best(text)
