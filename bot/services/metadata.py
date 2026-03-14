from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass

from aiohttp import ClientError, ClientSession, ClientTimeout

from bot.services.itunes import ItunesSearchService
from bot.services.models import TrackResult


class DeezerSearchService:
    BASE_URL = "https://api.deezer.com/search"

    def __init__(self, session: ClientSession, timeout_seconds: float = 15.0) -> None:
        self._session = session
        self._timeout = ClientTimeout(total=timeout_seconds)

    async def search_tracks(self, query: str, limit: int = 5) -> list[TrackResult]:
        params = {
            "q": query,
            "limit": max(1, min(limit, 10)),
        }
        try:
            async with self._session.get(self.BASE_URL, params=params, timeout=self._timeout) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError):
            return []

        results: list[TrackResult] = []
        for item in payload.get("data", []):
            title = item.get("title")
            artist = (item.get("artist") or {}).get("name")
            if not title or not artist:
                continue
            album = (item.get("album") or {}).get("title")
            artwork = (item.get("album") or {}).get("cover_medium")
            results.append(
                TrackResult(
                    source="deezer",
                    provider_id=str(item.get("id") or title),
                    title=str(title),
                    artist=str(artist),
                    album=str(album) if album else None,
                    duration_seconds=int(item["duration"]) if item.get("duration") else None,
                    external_url=str(item.get("link")) if item.get("link") else None,
                    preview_url=str(item.get("preview")) if item.get("preview") else None,
                    artwork_url=str(artwork) if artwork else None,
                    genre=None,
                )
            )
        return results


@dataclass(slots=True)
class _CachedTrackSearch:
    expires_at: float
    tracks: list[TrackResult]


class MetadataSearchService:
    def __init__(
        self,
        session: ClientSession,
        *,
        timeout_seconds: float = 15.0,
        country_code: str | None = None,
        cache_ttl_seconds: float = 180.0,
    ) -> None:
        self._itunes = ItunesSearchService(session, timeout_seconds=timeout_seconds, country_code=country_code)
        self._deezer = DeezerSearchService(session, timeout_seconds=timeout_seconds)
        self._cache_ttl_seconds = max(0.0, cache_ttl_seconds)
        self._cache: dict[str, _CachedTrackSearch] = {}
        self._inflight: dict[str, asyncio.Future[list[TrackResult]]] = {}
        self._lock = asyncio.Lock()

    async def search_tracks(self, query: str, limit: int = 5) -> list[TrackResult]:
        normalized_query = self._normalize(query)
        bounded_limit = max(1, min(limit, 10))
        if not normalized_query:
            return []
        cache_key = f"{normalized_query}|{bounded_limit}"

        cached = await self._get_cached_tracks(cache_key)
        if cached is not None:
            return list(cached)

        loop = asyncio.get_running_loop()
        async with self._lock:
            cached = self._get_cached_tracks_unlocked(cache_key)
            if cached is not None:
                return list(cached)

            future = self._inflight.get(cache_key)
            if future is None:
                future = loop.create_future()
                future.add_done_callback(_consume_future_exception)
                self._inflight[cache_key] = future
                leader = True
            else:
                leader = False

        if not leader:
            return list(await asyncio.shield(future))

        try:
            tracks = await self._search_tracks_uncached(query, bounded_limit)
            await self._store_cached_tracks(cache_key, tracks)
            future.set_result(list(tracks))
            return list(tracks)
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            async with self._lock:
                self._inflight.pop(cache_key, None)

    async def _search_tracks_uncached(self, query: str, limit: int) -> list[TrackResult]:
        itunes_tracks, deezer_tracks = await asyncio.gather(
            self._itunes.search_tracks(query, limit=limit),
            self._deezer.search_tracks(query, limit=limit),
            return_exceptions=False,
        )

        deduped: OrderedDict[str, TrackResult] = OrderedDict()
        for track in [*itunes_tracks, *deezer_tracks]:
            key = self._track_key(track)
            if key not in deduped:
                deduped[key] = track
            if len(deduped) >= limit:
                break
        return list(deduped.values())

    async def _get_cached_tracks(self, cache_key: str) -> list[TrackResult] | None:
        async with self._lock:
            return self._get_cached_tracks_unlocked(cache_key)

    def _get_cached_tracks_unlocked(self, cache_key: str) -> list[TrackResult] | None:
        cached = self._cache.get(cache_key)
        if cached is None:
            return None
        if cached.expires_at <= time.monotonic():
            self._cache.pop(cache_key, None)
            return None
        return cached.tracks

    async def _store_cached_tracks(self, cache_key: str, tracks: list[TrackResult]) -> None:
        async with self._lock:
            self._cleanup_expired_cache_unlocked()
            self._cache[cache_key] = _CachedTrackSearch(
                expires_at=time.monotonic() + self._cache_ttl_seconds,
                tracks=list(tracks),
            )

    def _cleanup_expired_cache_unlocked(self) -> None:
        now = time.monotonic()
        expired_keys = [key for key, cached in self._cache.items() if cached.expires_at <= now]
        for key in expired_keys:
            self._cache.pop(key, None)

    def _track_key(self, track: TrackResult) -> str:
        return f"{self._normalize(track.title)}|{self._normalize(track.artist)}"

    def _normalize(self, text: str) -> str:
        return " ".join(text.casefold().split())


def _consume_future_exception(future: asyncio.Future[object]) -> None:
    if future.cancelled():
        return
    try:
        future.exception()
    except asyncio.CancelledError:
        return
