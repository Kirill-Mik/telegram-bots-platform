"""NLP-слой платформы (лёгкий, без PyTorch).

Переиспользуемое ядро для всех ботов:
  - экстрактивное summary              (sumy TextRank)
  - семантический поиск                (TF-IDF + косинусная близость)
  - классификация по темам             (темы задаются ключевыми словами)

Выбор стека продиктован ограничением сервера (1-4 ГБ RAM): ни одна
зависимость не тянет тяжёлые ML-фреймворки. Для повторяющихся операций
есть кэшируемые объекты:
  - TfidfIndex      — матрица корпуса считается один раз, запросы дёшевы;
  - TopicClassifier — векторизатор тем обучается один раз на цикл опроса.
"""

from __future__ import annotations

import re
import threading

import numpy as np
from nltk.stem.snowball import SnowballStemmer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

_WS = re.compile(r"\s+")

_punkt_ready = False


def _ensure_punkt() -> None:
    """Токенизаторы nltk нужны только sumy — качаем лениво и не при импорте."""
    global _punkt_ready
    if _punkt_ready:
        return
    import nltk

    for pkg in ("punkt", "punkt_tab"):
        try:
            nltk.data.find(f"tokenizers/{pkg}")
        except LookupError:
            try:
                nltk.download(pkg, quiet=True)
            except Exception:  # noqa: BLE001
                pass
    _punkt_ready = True


def _clean(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


class TfidfIndex:
    """Предпосчитанный TF-IDF-индекс корпуса.

    Матрица документов считается один раз (fit), дальше каждый запрос —
    только transform + косинус. Владелец индекса отвечает за инвалидацию
    при изменении корпуса.
    """

    def __init__(self, vectorizer: TfidfVectorizer | None, matrix) -> None:
        self._vectorizer = vectorizer
        self._matrix = matrix

    @property
    def empty(self) -> bool:
        return self._vectorizer is None

    def rank(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """(индекс_документа, score) по убыванию близости к query."""
        query = _clean(query)
        if not query or self.empty:
            return []
        q_vec = self._vectorizer.transform([query])
        sims = cosine_similarity(q_vec, self._matrix).ravel()
        order = np.argsort(-sims)
        return [(int(i), float(sims[i])) for i in order[:top_k] if sims[i] > 0.0]


class TopicClassifier:
    """Классификатор по пользовательским темам ({название: [ключевые слова]}).

    Векторизатор обучается на «эталонных документах» тем ОДИН раз;
    классификация каждого текста — только transform. Это убирает
    переобучение TF-IDF на каждую запись ленты.
    """

    def __init__(self, vectorizer: TfidfVectorizer | None, topic_matrix, names: list[str]):
        self._vectorizer = vectorizer
        self._matrix = topic_matrix
        self._names = names

    @property
    def empty(self) -> bool:
        return self._vectorizer is None

    def classify(self, text: str, threshold: float = 0.0) -> list[tuple[str, float]]:
        text = _clean(text)
        if not text or self.empty:
            return []
        vec = self._vectorizer.transform([text])
        sims = cosine_similarity(vec, self._matrix).ravel()
        scored = [
            (self._names[i], float(sims[i]))
            for i in range(len(self._names))
            if sims[i] > threshold
        ]
        scored.sort(key=lambda x: -x[1])
        return scored

    def best(self, text: str, threshold: float = 0.05) -> tuple[str, float] | None:
        ranked = self.classify(text, threshold)
        return ranked[0] if ranked else None


class NLP:
    """Лёгкий NLP-движок. Потокобезопасен; ленивая инициализация экстракторов."""

    def __init__(self, lang: str = "ru"):
        self.lang = lang if lang in ("ru", "en") else "ru"
        self._lock = threading.Lock()
        stem_lang = "russian" if self.lang == "ru" else "english"
        self._stemmer = SnowballStemmer(stem_lang)
        self._token_re = re.compile(r"[\w-]+", re.UNICODE)

    def _stem_analyzer(self, text: str) -> list[str]:
        """Токенизация + стемминг для TF-IDF.

        Нормализует словоформы (свёклы/свёклу -> свекл), чтобы
        семантический поиск находил совпадения по смыслу, а не по
        точному написанию. Это критично для русского языка.
        """
        tokens = self._token_re.findall(text.lower())
        return [self._stemmer.stem(t) for t in tokens if len(t) > 2]

    # ---- Summary --------------------------------------------------------
    def summarize(self, text: str, sentences: int = 3) -> str:
        text = _clean(text)
        if not text:
            return ""
        # Короткий текст не нуждается в summary
        if len(text) < 280:
            return text
        try:
            _ensure_punkt()
            from sumy.nlp.tokenizers import Tokenizer
            from sumy.parsers.plaintext import PlaintextParser
            from sumy.summarizers.text_rank import TextRankSummarizer

            tok_lang = "russian" if self.lang == "ru" else "english"
            parser = PlaintextParser.from_string(text, Tokenizer(tok_lang))
            summarizer = TextRankSummarizer()
            picked = summarizer(parser.document, sentences)
            result = " ".join(str(s) for s in picked).strip()
            return result or text[:280] + "…"
        except Exception:  # noqa: BLE001
            # Фолбэк: первые N символов
            return text[:280] + "…"

    # ---- Семантический поиск -------------------------------------------
    def build_index(self, docs: list[str]) -> TfidfIndex:
        """Строит переиспользуемый TF-IDF-индекс по корпусу документов."""
        corpus = [_clean(d) for d in docs]
        if not corpus:
            return TfidfIndex(None, None)
        try:
            vectorizer = TfidfVectorizer(analyzer=self._stem_analyzer)
            matrix = vectorizer.fit_transform(corpus)
            return TfidfIndex(vectorizer, matrix)
        except ValueError:
            # пустой словарь (например, только стоп-слова)
            return TfidfIndex(None, None)

    def semantic_rank(
        self, query: str, docs: list[str], top_k: int = 10
    ) -> list[tuple[int, float]]:
        """Одноразовое ранжирование docs по близости к query.

        Для повторяющихся запросов по одному и тому же корпусу используйте
        build_index() и TfidfIndex.rank() — матрица посчитается один раз.
        """
        query = _clean(query)
        if not query:
            return []
        return self.build_index(docs).rank(query, top_k)

    # ---- Классификация по темам ----------------------------------------
    def topic_classifier(self, topics: dict[str, list[str]]) -> TopicClassifier:
        """Готовит классификатор по темам (векторизатор обучается один раз).

        topics: {название_темы: [ключевые слова/фразы]}. Каждая тема
        превращается в «эталонный документ» из своих ключевых слов;
        близость текста к теме считается стеммированным TF-IDF + косинусом.
        Пользователь задаёт темы словами, обучать модель не нужно.
        """
        if not topics:
            return TopicClassifier(None, None, [])
        names = list(topics.keys())
        topic_docs = [" ".join(kw) for kw in topics.values()]
        try:
            vectorizer = TfidfVectorizer(analyzer=self._stem_analyzer)
            matrix = vectorizer.fit_transform(topic_docs)
            return TopicClassifier(vectorizer, matrix, names)
        except ValueError:
            return TopicClassifier(None, None, [])

    def classify(
        self, text: str, topics: dict[str, list[str]], threshold: float = 0.0
    ) -> list[tuple[str, float]]:
        """Одноразовая классификация (для пакетной работы см. topic_classifier)."""
        return self.topic_classifier(topics).classify(text, threshold)

    def best_topic(
        self, text: str, topics: dict[str, list[str]], threshold: float = 0.05
    ) -> tuple[str, float] | None:
        return self.topic_classifier(topics).best(text, threshold)
