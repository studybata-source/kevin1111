# Kevin 11 Music Bot Roadmap

Last updated: 2026-03-13

## Product Scope

Kevin 11 Music Bot is now intentionally focused on a smaller, cleaner Telegram flow:

- user sends a song name or supported link
- bot finds the best usable match
- bot sends back the audio file in Telegram
- optional extras stay limited to lyrics, settings, history, and owner tools

Removed from scope:

- inline mode
- scan audio / music recognition
- business mode handling

## What The Bot Supports

- private chat direct download from plain text
- group usage with `/song`, `/download`, mentions, and replies to the bot
- add-to-group button with suggested admin rights
- lyrics lookup
- quality settings
- search history
- owner-only stats and broadcast tools

## What The Bot Does Not Use

- BotFather inline mode
- Telegram business mode
- forum-thread specific features
- music recognition / voice-note scanning

## Current Technical Direction

- `aiogram` 3 polling bot
- `yt-dlp` for source resolution and download
- `ffmpeg` for MP3 extraction when available
- iTunes Search API for cleaner metadata matching
- LRCLIB for lyrics
- SQLite + Telegram `file_id` cache

## Next Priorities

1. Keep the download path stable and simple.
2. Improve source matching for edge-case tracks.
3. Tighten owner-only tools without adding spammy features.
4. Keep the Telegram UX minimal and obvious.
