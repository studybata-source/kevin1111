from __future__ import annotations

import logging
import re

from aiohttp import ClientError, ClientSession, ClientTimeout

from bot.services.models import LyricsResult


LOGGER = logging.getLogger(__name__)


class LrclibLyricsService:
    BASE_URL = "https://lrclib.net/api/search"

    def __init__(self, session: ClientSession, timeout_seconds: float = 15.0) -> None:
        self._session = session
        self._timeout = ClientTimeout(total=timeout_seconds)

    async def find_lyrics(
        self,
        title: str,
        artist: str | None = None,
        *,
        query_text: str | None = None,
    ) -> LyricsResult | None:
        params = {"track_name": title}
        if artist:
            params["artist_name"] = artist

        try:
            async with self._session.get(self.BASE_URL, params=params, timeout=self._timeout) as response:
                response.raise_for_status()
                payload = await response.json()
        except (ClientError, TimeoutError, ValueError) as exc:
            LOGGER.warning("LRCLIB lookup failed for title=%r artist=%r: %s", title, artist, exc)
            return None

        if not payload:
            return None

        candidates = [item for item in payload if item.get("plainLyrics")]
        if not candidates:
            return None

        best = max(candidates, key=lambda item: _score_candidate(item, title, artist, query_text))
        lyrics = best.get("plainLyrics")
        if not lyrics:
            return None

        return LyricsResult(
            title=best.get("trackName") or title,
            artist=best.get("artistName") or artist or "Unknown",
            plain_lyrics=lyrics,
            synced_lyrics=best.get("syncedLyrics"),
        )


TOKEN_RE = re.compile(r"[a-z0-9']+")


def _score_candidate(
    item: dict[str, object],
    title: str,
    artist: str | None,
    query_text: str | None,
) -> float:
    track_name = str(item.get("trackName") or "")
    artist_name = str(item.get("artistName") or "")
    lyrics_text = str(item.get("plainLyrics") or "")

    score = 0.0
    wanted_title = _normalized_text(title)
    candidate_title = _normalized_text(track_name)
    wanted_artist = _normalized_text(artist or "")
    candidate_artist = _normalized_text(artist_name)
    query_norm = _normalized_text(query_text or "")

    if wanted_title and candidate_title == wanted_title:
        score += 40
    elif wanted_title and wanted_title in candidate_title:
        score += 20

    if wanted_artist and candidate_artist == wanted_artist:
        score += 28
    elif wanted_artist and wanted_artist in candidate_artist:
        score += 14

    query_tokens = _tokens(query_text or f"{title} {artist or ''}")
    title_tokens = _tokens(track_name)
    artist_tokens = _tokens(artist_name)
    score += len(query_tokens & title_tokens) * 5
    score += len(query_tokens & artist_tokens) * 4

    preferred_script = _dominant_script(query_text or f"{title} {artist or ''}")
    lyrics_script = _dominant_script(lyrics_text[:700])
    score += _script_bonus(preferred_script, lyrics_script)

    if query_norm and query_norm in _normalized_text(f"{artist_name} {track_name}"):
        score += 12

    return score


def _normalized_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(_normalized_text(text)))


def _dominant_script(text: str) -> str:
    counts = {
        "latin": 0,
        "devanagari": 0,
        "gurmukhi": 0,
        "telugu": 0,
        "other": 0,
    }
    for char in text:
        codepoint = ord(char)
        if "a" <= char.casefold() <= "z":
            counts["latin"] += 1
        elif 0x0900 <= codepoint <= 0x097F:
            counts["devanagari"] += 1
        elif 0x0A00 <= codepoint <= 0x0A7F:
            counts["gurmukhi"] += 1
        elif 0x0C00 <= codepoint <= 0x0C7F:
            counts["telugu"] += 1
        elif char.isalpha():
            counts["other"] += 1

    dominant = max(counts, key=counts.get)
    return dominant if counts[dominant] > 0 else "latin"


def _script_bonus(preferred_script: str, lyrics_script: str) -> float:
    if preferred_script == lyrics_script:
        return 18.0
    if preferred_script == "latin":
        if lyrics_script in {"devanagari", "gurmukhi"}:
            return -4.0
        if lyrics_script == "telugu":
            return -18.0
        if lyrics_script == "other":
            return -10.0
    if lyrics_script == "latin":
        return 4.0
    return -6.0
