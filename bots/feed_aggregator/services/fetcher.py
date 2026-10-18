"""Сбор и обработка лент.

Конвейер: RSS-лента -> записи -> очистка текста -> классификация по
пользовательским темам -> summary -> запись в БД с дедупликацией.

Сетевой слой:
  - ленты скачиваются через httpx с таймаутом (15 с), а байты отдаются
    в feedparser — сам feedparser.parse(url) таймаута не имеет и мог
    зависнуть на медленном источнике;
  - поддерживаются условные запросы (ETag / If-Modified-Since): если
    источник не менялся, сервер отвечает 304 и трафик не тратится.

Классификация: TF-IDF-векторизатор тем обучается ОДИН раз на цикл опроса
(TopicClassifier из botcore), а не заново на каждую запись ленты.

Сетевые ошибки и кривые ленты не валят процесс: проблемный источник
просто пропускается, остальные обрабатываются.
"""

from __future__ import annotations

import html as html_lib
import logging
import re

import feedparser
import httpx
from botcore import NLP, TopicClassifier

from .database import Database, make_uid

log = logging.getLogger("fetcher")

_TAG_RE = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

HTTP_TIMEOUT = 15.0
USER_AGENT = "feed-aggregator-bot/1.0 (+https://github.com/Kirill-Mik)"


def _strip_html(text: str) -> str:
    text = _TAG_RE.sub(" ", text or "")
    text = html_lib.unescape(text)
    return _WS.sub(" ", text).strip()


class FeedFetcher:
    def __init__(self, db: Database, nlp: NLP):
        self.db = db
        self.nlp = nlp

    # ---- Сетевой слой ----
    @staticmethod
    def _download(
        url: str,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> httpx.Response | None:
        """GET с таймаутом и условными заголовками. None при сетевой ошибке."""
        headers = {"User-Agent": USER_AGENT}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
                return client.get(url, headers=headers)
        except httpx.HTTPError as e:
            log.warning("Не удалось скачать %s: %s", url, e)
            return None

    def fetch_feed_meta(self, url: str) -> tuple[bool, str]:
        """Проверяет ленту и возвращает (валидна, заголовок)."""
        resp = self._download(url)
        if resp is None or resp.status_code >= 400:
            return False, ""
        d = feedparser.parse(resp.content)
        if d.bozo and not d.entries:
            return False, ""
        title = getattr(d.feed, "title", "") or url
        return True, title

    # ---- Конвейер ----
    def poll_source(
        self, user_id: int, source, classifier: TopicClassifier | None
    ) -> int:
        """Опрашивает один источник, классифицирует и сохраняет новые посты.

        classifier готовится вызывающим кодом один раз на цикл опроса.
        Возвращает число новых (недублирующихся) постов.
        """
        url = source["url"]
        resp = self._download(url, source["etag"], source["last_modified"])
        if resp is None:
            return 0
        if resp.status_code == 304:  # источник не менялся
            return 0
        if resp.status_code >= 400:
            log.warning("Источник %s ответил %s", url, resp.status_code)
            return 0

        self.db.update_source_cache(
            source["id"],
            resp.headers.get("ETag"),
            resp.headers.get("Last-Modified"),
        )

        parsed = feedparser.parse(resp.content)
        if not parsed.entries:
            return 0

        new_count = 0
        for entry in parsed.entries[:40]:
            title = _strip_html(getattr(entry, "title", "") or "")
            raw_desc = getattr(entry, "summary", "") or getattr(entry, "description", "")
            desc = _strip_html(raw_desc)
            link = getattr(entry, "link", "") or ""
            published = getattr(entry, "published", "") or getattr(entry, "updated", "")

            full_text = f"{title}. {desc}".strip()
            if len(full_text) < 5:
                continue

            uid = make_uid(url, link, title)

            # классификация по пользовательским темам (векторизатор уже обучен)
            topic, score = None, None
            if classifier is not None and not classifier.empty:
                best = classifier.best(full_text)
                if best:
                    topic, score = best[0], round(best[1], 4)

            summary = self.nlp.summarize(desc) if len(desc) > 280 else desc

            inserted = self.db.add_post(
                user_id=user_id,
                source_id=source["id"],
                uid=uid,
                title=title or "(без заголовка)",
                summary=summary or title,
                url=link,
                topic=topic,
                score=score,
                published=published,
            )
            if inserted:
                new_count += 1
        return new_count

    def poll_user(self, user_id: int) -> int:
        """Опрашивает все источники пользователя. Возвращает число новых постов.

        Классификатор тем строится один раз на весь цикл — TF-IDF не
        переобучается ни на источник, ни тем более на запись.
        """
        topics = self.db.get_topics(user_id)
        classifier = self.nlp.topic_classifier(topics) if topics else None
        total = 0
        for src in self.db.list_sources(user_id):
            total += self.poll_source(user_id, src, classifier)
        return total
