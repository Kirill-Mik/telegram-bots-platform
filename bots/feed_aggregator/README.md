# feed_aggregator

Reads RSS/Atom feeds, sorts entries into topics defined by the user and sends
digests. A topic is a set of keywords, so nothing has to be trained. Entries
are matched to topics with stemmed TF-IDF and cosine similarity from
`botcore.nlp`.

## Implementation notes

- Polling starts a few seconds after launch, then repeats every
  `POLL_INTERVAL_MIN` minutes.
- Feeds are downloaded with httpx (15 s timeout, conditional requests with
  ETag / If-Modified-Since); the bytes are then parsed by feedparser.
- The topic vectorizer is fitted once per polling cycle, not for every entry.
- Only numeric ids go into callback_data (Telegram's limit is 64 bytes).

## Run

```bash
cp bots/feed_aggregator/.env.example bots/feed_aggregator/.env   # set BOT_TOKEN
python -m bots.feed_aggregator
```

In Telegram: /start, add sources, define topics, press "Обновить" (refresh).
