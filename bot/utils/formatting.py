from __future__ import annotations

from html import escape

from bot.constants import QUALITY_DESCRIPTIONS, QUALITY_LABELS
from bot.services.models import LyricsResult, TrackResult


def format_duration(duration_seconds: int | None) -> str:
    if not duration_seconds:
        return "Unknown"
    minutes, seconds = divmod(duration_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def format_search_intro(query: str, count: int) -> str:
    safe_query = escape(query)
    return (
        f"<b>Search results</b>\n"
        f"Query: <code>{safe_query}</code>\n"
        f"Matches found: <b>{count}</b>"
    )


def format_track_card(track: TrackResult, index: int) -> str:
    parts = [
        f"<b>{index}. {escape(track.title)}</b>",
        f"Artist: <b>{escape(track.artist)}</b>",
        f"Album: {escape(track.album or 'Single / Unknown')}",
        f"Length: {format_duration(track.duration_seconds)}",
    ]
    if track.genre:
        parts.append(f"Genre: {escape(track.genre)}")
    return "\n".join(parts)


def format_history(rows: list[dict[str, str | int]]) -> str:
    if not rows:
        return (
            "<b>No recents yet.</b>\n"
            "Drop a song name, paste a link, or tap the menu to start."
        )

    lines = ["<b>Recent searches</b>"]
    for row in rows:
        query = escape(str(row["query"]))
        result_count = row["result_count"]
        created_at = escape(str(row["created_at"]))
        lines.append(f"- <code>{query}</code> | {result_count} hits | {created_at}")
    return "\n".join(lines)


def format_settings(preset: str, audio_format: str) -> str:
    quality_label = QUALITY_LABELS.get(preset, preset.title())
    quality_description = QUALITY_DESCRIPTIONS.get(preset, "No description available.")
    return (
        "<b>Settings</b>\n"
        f"Current quality preset: <b>{escape(quality_label)}</b>\n"
        f"{escape(quality_description)}\n\n"
        "Current audio format: <b>MP3</b>\n"
        "Format switching is off right now so downloads stay stable.\n\n"
        "These settings apply only to your future downloads."
    )


def format_lyrics(result: LyricsResult) -> str:
    body = result.plain_lyrics.strip()
    if len(body) > 3200:
        body = body[:3200].rstrip() + "\n\n[truncated for Telegram]"

    header = f"<b>{escape(result.title)}</b>\nArtist: <b>{escape(result.artist)}</b>"
    if result.synced_lyrics:
        header += "\nTimed lyrics: <b>available</b>"
    return f"{header}\n\n{escape(body)}"


def format_search_page(query: str, tracks: list[TrackResult], page: int, total_pages: int) -> str:
    start = page * 3
    page_tracks = tracks[start : start + 3]
    lines = [
        "<b>Track picks</b>",
        f"Query: <code>{escape(query)}</code>",
        f"Page <b>{page + 1}</b> of <b>{total_pages}</b>",
        "",
    ]
    for index, track in enumerate(page_tracks, start=start + 1):
        lines.append(format_track_card(track, index))
        lines.append("")
    return "\n".join(lines).strip()


def format_download_status(
    title: str,
    performer: str | None,
    percent_text: str | None = None,
    speed_text: str | None = None,
    eta_text: str | None = None,
    phase: str = "Pulling audio",
) -> str:
    lines = [f"<b>{escape(title)}</b>"]
    if performer:
        lines.append(f"Artist: <b>{escape(performer)}</b>")
    lines.append(escape(phase))
    if percent_text:
        lines.append(f"Progress: <b>{escape(percent_text)}</b>")
    if speed_text:
        lines.append(f"Speed: <code>{escape(speed_text)}</code>")
    if eta_text:
        lines.append(f"ETA: <code>{escape(eta_text)}</code>")
    return "\n".join(lines)
