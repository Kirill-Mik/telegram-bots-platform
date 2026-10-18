"""Тесты feed_aggregator: классификация записей по темам, условные
запросы (304), лимит callback_data. Сеть подменена, БД — во временной папке."""

import pytest
from botcore import NLP

from bots.feed_aggregator.handlers import ui
from bots.feed_aggregator.services.database import Database
from bots.feed_aggregator.services.fetcher import FeedFetcher

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <title>Тестовая лента</title>
  <item>
    <title>ЦБ поднял ключевую ставку</title>
    <description>Банки ожидают роста ставок по кредитам и вкладам в рублях.</description>
    <link>https://example.ru/finance/1</link>
  </item>
  <item>
    <title>Гол на последней минуте</title>
    <description>Команда выиграла матч чемпионата, гол забит в добавленное время.</description>
    <link>https://example.ru/sport/2</link>
  </item>
</channel></rss>
"""


class FakeResponse:
    def __init__(self, status_code=200, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


@pytest.fixture(scope="module")
def nlp():
    return NLP("ru")


@pytest.fixture()
def db(tmp_path):
    database = Database(str(tmp_path / "feeds.db"))
    yield database
    database.close()


@pytest.fixture()
def fetcher(db, nlp, monkeypatch):
    f = FeedFetcher(db, nlp)
    calls = []

    def fake_download(url, etag=None, last_modified=None):
        calls.append({"url": url, "etag": etag, "last_modified": last_modified})
        return FakeResponse(
            200, RSS.encode("utf-8"), {"ETag": 'W/"abc"', "Last-Modified": "yesterday"}
        )

    monkeypatch.setattr(f, "_download", fake_download)
    f._calls = calls
    return f


class TestClassification:
    def test_posts_classified_into_user_topics(self, db, fetcher):
        db.add_source(1, "https://example.ru/rss", "Лента")
        db.add_topic(1, "Финансы", ["ставка", "кредит", "банк", "рубль"])
        db.add_topic(1, "Спорт", ["матч", "гол", "чемпионат"])

        new_count = fetcher.poll_user(1)
        assert new_count == 2

        posts = {p["title"]: p for p in db.recent_posts(1)}
        assert posts["ЦБ поднял ключевую ставку"]["topic"] == "Финансы"
        assert posts["Гол на последней минуте"]["topic"] == "Спорт"
        for p in posts.values():
            assert p["score"] and p["score"] > 0

    def test_no_topics_means_untagged_posts(self, db, fetcher):
        db.add_source(1, "https://example.ru/rss", "Лента")
        assert fetcher.poll_user(1) == 2
        assert all(p["topic"] is None for p in db.recent_posts(1))

    def test_repeat_poll_no_duplicates(self, db, fetcher):
        db.add_source(1, "https://example.ru/rss", "Лента")
        assert fetcher.poll_user(1) == 2
        assert fetcher.poll_user(1) == 0
        assert db.stats(1)["total"] == 2


class TestConditionalRequests:
    def test_etag_saved_and_sent_back(self, db, fetcher):
        db.add_source(1, "https://example.ru/rss", "Лента")
        fetcher.poll_user(1)
        src = db.list_sources(1)[0]
        assert src["etag"] == 'W/"abc"'
        assert src["last_modified"] == "yesterday"

        fetcher.poll_user(1)  # второй опрос шлёт условные заголовки
        assert fetcher._calls[-1]["etag"] == 'W/"abc"'
        assert fetcher._calls[-1]["last_modified"] == "yesterday"

    def test_304_means_no_new_posts(self, db, nlp, monkeypatch):
        f = FeedFetcher(db, nlp)
        monkeypatch.setattr(f, "_download", lambda *a, **kw: FakeResponse(304))
        db.add_source(1, "https://example.ru/rss", "Лента")
        assert f.poll_user(1) == 0
        assert db.stats(1)["total"] == 0

    def test_network_error_skipped(self, db, nlp, monkeypatch):
        f = FeedFetcher(db, nlp)
        monkeypatch.setattr(f, "_download", lambda *a, **kw: None)
        db.add_source(1, "https://example.ru/rss", "Лента")
        assert f.poll_user(1) == 0


class TestCallbackDataLimit:
    def test_topic_callbacks_use_numeric_ids(self, db):
        """Кириллическое имя темы не попадает в callback_data (лимит 64 байта)."""
        long_name = "Очень длинное название темы про международную макроэкономику"
        db.add_topic(1, long_name, ["слово"] * 10)
        rows = db.list_topics(1)
        kb = ui.topics_keyboard(rows)
        for row in kb.inline_keyboard:
            for btn in row:
                assert len(btn.callback_data.encode("utf-8")) <= 64
                prefix, id_part = btn.callback_data.rsplit(":", 1)
                assert id_part.isdigit(), "в callback_data должен быть числовой id"
