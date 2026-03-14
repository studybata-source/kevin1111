# Kevin 11 Music Bot

Kevin 11 Music Bot is a Telegram music bot focused on one clean job:

- type a song name or paste a supported link
- get back the audio file in Telegram
- keep max quality as the default mode

## Current Bot Features

- `/start`, `/help`, `/settings`, `/search`, `/song`, `/download`, `/lyrics`, `/history`, `/cancel`
- direct song-name downloads in private chat
- group-friendly flow with `/song`, mentions, and replies to the bot
- add-to-group shortcuts with default admin rights requests for smoother setup
- search result buttons
- `yt-dlp` download engine with Telegram `file_id` cache
- cached metadata lookups and shared in-flight source resolution for faster repeated requests
- shared search/callback session storage via the database for multi-worker deployments
- parallel metadata lookup with iTunes + Deezer
- per-user format selection: `MP3`, `M4A`, `Opus`, `Original`
- LRCLIB lyrics lookup
- PostgreSQL-ready storage for users, quality settings, formats, cache, history, and chat tracking
- optional webhook mode with Redis-backed FSM storage for production traffic
- optional Telegram ops-group alerts instead of noisy local runtime logs
- optional owner-only tools like `/stats`, `/broadcast`, and `/broadcast_groups`

## Removed Features

- inline mode
- scan audio / recognition
- Telegram business-mode handling

## Quick Start

```bash
pip install -r requirements.txt
copy .env.example .env
```

Set `BOT_TOKEN` and `BOT_USERNAME` in `.env`, then run:

```bat
run_bot.bat
```

You can also run:

```bash
python -m bot
```

On this Windows machine, `run_bot.bat` is the safer launcher because it prefers the working virtual environment automatically.

## Notes

- Polling mode works locally and only needs outbound HTTPS.
- For high-scale production, prefer `RUN_MODE=webhook` with `DATABASE_URL` on PostgreSQL and `REDIS_URL` for shared FSM state.
- Python 3.12 is the recommended Windows runtime.
- `ffmpeg` should be installed for MP3 conversion.
- Max quality is the default audio mode.
- If you set `DATABASE_URL`, the bot will use PostgreSQL instead of the local SQLite file.
- If `LOG_TO_FILE=false`, runtime logs stay off disk and only go to the console unless `OPS_CHAT_ID` is set.
- Throughput can be tuned with `RESOLVE_CONCURRENCY`, `DOWNLOAD_CONCURRENCY`, `METADATA_CACHE_TTL_SEC`, `RESOLVE_CACHE_TTL_SEC`, `DATABASE_POOL_SIZE`, and `DATABASE_MAX_OVERFLOW`.
