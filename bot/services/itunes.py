from __future__ import annotations

import logging

from aiohttp import ClientError, ClientSession, ClientTimeout

from bot.services.models import TrackResult


LOGGER = logging.getLogger(__name__)


class ItunesSearchService:
    BASE_URL = "https://itunes.apple.com/search"

    def __init__(
        self,
        session: ClientSession,
        timeout_seconds: float = 15.0,
        country_code: str | None = None,
    ) -> None:
        self._session = session
        self._timeout = ClientTimeout(total=timeout_seconds)
        self._country_code = country_code.strip().upper() if country_code else None

    async def search_tracks(self, query: str, limit: int = 5) -> list[TrackResult]:
        params = {
            "term": query,
            "entity": "song",
            "limit": max(1, min(limit, 10)),
        }
        if self._country_code:
            params["country"] = self._country_code

        try:
            async with self._session.get(self.BASE_URL, params=params, timeout=self._timeout) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as exc:
            LOGGER.warning("iTunes search failed for query=%r: %s", query, exc)
            return []

        results: list[TrackResult] = []
        for item in payload.get("results", []):
            track_name = item.get("trackName")
            artist_name = item.get("artistName")
            if not track_name or not artist_name:
                continue

            duration_ms = item.get("trackTimeMillis")
            results.append(
                TrackResult(
                    source="itunes",
                    provider_id=str(item.get("trackId") or item.get("collectionId") or track_name),
                    title=track_name,
                    artist=artist_name,
                    album=item.get("collectionName"),
                    duration_seconds=int(duration_ms / 1000) if duration_ms else None,
                    external_url=item.get("trackViewUrl") or item.get("collectionViewUrl"),
                    preview_url=item.get("previewUrl"),
                    artwork_url=item.get("artworkUrl100"),
                    genre=item.get("primaryGenreName"),
                )
            )
        return results
