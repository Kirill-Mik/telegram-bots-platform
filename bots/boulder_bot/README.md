# boulder_bot

Booking bot for a climbing gym. A client picks a class, a date and a time
slot, leaves a name and a phone number, can cancel the booking and gets a
reminder a day before. Questions are answered from an FAQ by text similarity
(`botcore.nlp`). The same flow fits any slot-based booking: a gym, a pool,
a dance studio.

## Implementation notes

- Booking is atomic at the SQL level:
  `UPDATE slots SET booked = 1 WHERE id = ? AND booked = 0` plus a rowcount
  check. If two clients book the same slot at once, exactly one succeeds.
- A reminder is marked as sent only after Telegram confirms delivery.
- Admin panel for users listed in `ADMIN_IDS`: add classes, slots for a date
  and FAQ entries without editing the seed file.

## Run

```bash
cp bots/boulder_bot/.env.example bots/boulder_bot/.env   # set BOT_TOKEN and ADMIN_IDS
python -m bots.boulder_bot.seed                          # optional demo data
python -m bots.boulder_bot
```

Your Telegram ID for `ADMIN_IDS` can be found via @userinfobot.
