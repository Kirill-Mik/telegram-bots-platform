# storage_bot

Personal file storage in Telegram: folders, upload, download. The bot does not
process file contents; it returns files exactly as they were received.

## Features

- Folder tree with breadcrumb navigation ("Хранилище / Клиенты / Договоры").
- Upload: send a file to the chat and it goes to the folder that is open.
  Documents, photos, video, audio and voice messages are supported.
- Download a single file, or a whole folder as a ZIP that keeps subfolders.
- Rename, move and delete. Deleting a folder shows how many files it
  contains before confirming.
- `/find <part of name>` — search by file name.
- `/tree` — the whole tree as text.

## How it works

Metadata (tree, names, sizes) is stored in SQLite. File bytes are stored on
disk in the same folder structure the user sees:

```
data/storage/<user_id>/Клиенты/Договоры/contract.pdf
```

The storage can be browsed, copied or backed up without running the bot.

Names are unique within a folder: on a clash the bot adds a suffix
(`report.pdf` becomes `report (2).pdf`) instead of overwriting. Characters that
are invalid in Windows or Linux paths are removed.

Downloads use Telegram's `file_id`, so a file is sent without reading it from
disk. The disk copy is kept as the source of truth in case Telegram loses the
file.

## Telegram limits

- Bots can download files up to 20 MB (Bot API limit); larger files are
  rejected with a message.
- Bots can send files up to 50 MB, so the bot refuses to build a ZIP larger
  than that and says so.

## Run

```bash
cp bots/storage_bot/.env.example bots/storage_bot/.env   # set BOT_TOKEN
python -m bots.storage_bot
```
