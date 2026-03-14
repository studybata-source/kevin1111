from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass

from bot.database.repository import Database
from bot.services.models import TrackResult


@dataclass(slots=True)
class CachedPayload:
    expires_at: float
    kind: str
    value: object


@dataclass(slots=True)
class StoredSearchResults:
    query: str
    tracks: list[TrackResult]


class SearchSessionStore:
    def __init__(self, ttl_seconds: int = 1800, *, db: Database | None = None) -> None:
        self._ttl_seconds = ttl_seconds
        self._db = db
        self._payloads: dict[str, CachedPayload] = {}
        self._last_cleanup_at = 0.0
        self._cleanup_interval_seconds = min(max(60, ttl_seconds // 2), 300)

    async def put_results(self, query: str, tracks: list[TrackResult]) -> str:
        return await self._put("results", StoredSearchResults(query=query, tracks=tracks))

    async def get_results(self, token: str) -> StoredSearchResults | None:
        payload = await self._get(token, expected_kind="results")
        return payload if isinstance(payload, StoredSearchResults) else None

    async def put_query(self, query: str) -> str:
        return await self._put("query", query)

    async def get_query(self, token: str) -> str | None:
        payload = await self._get(token, expected_kind="query")
        return str(payload) if isinstance(payload, str) else None

    async def _put(self, kind: str, value: object) -> str:
        if self._db is None:
            self._cleanup()
        else:
            await self._cleanup_shared_store()

        token = secrets.token_urlsafe(6).replace("-", "").replace("_", "")
        if self._db is None:
            self._payloads[token] = CachedPayload(
                expires_at=time.monotonic() + self._ttl_seconds,
                kind=kind,
                value=value,
            )
            return token

        expires_at = int(time.time()) + self._ttl_seconds
        payload_json = self._serialize_payload(kind, value)
        await self._db.upsert_search_session(token, kind, payload_json, expires_at)
        return token

    async def _get(self, token: str, expected_kind: str) -> object | None:
        if self._db is None:
            self._cleanup()
            cached = self._payloads.get(token)
            if not cached or cached.kind != expected_kind:
                return None
            return cached.value

        await self._cleanup_shared_store()
        payload_json = await self._db.get_search_session(token, expected_kind, now_epoch=int(time.time()))
        if payload_json is None:
            return None
        return self._deserialize_payload(expected_kind, payload_json)

    def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [token for token, cached in self._payloads.items() if cached.expires_at <= now]
        for token in expired:
            self._payloads.pop(token, None)

    async def _cleanup_shared_store(self) -> None:
        if self._db is None:
            return
        now = time.monotonic()
        if now - self._last_cleanup_at < self._cleanup_interval_seconds:
            return
        self._last_cleanup_at = now
        await self._db.delete_expired_search_sessions(int(time.time()))

    def _serialize_payload(self, kind: str, value: object) -> str:
        if kind == "query":
            return json.dumps({"query": str(value)})
        if kind == "results" and isinstance(value, StoredSearchResults):
            return json.dumps(
                {
                    "query": value.query,
                    "tracks": [asdict(track) for track in value.tracks],
                }
            )
        raise ValueError(f"Unsupported search-session payload kind: {kind}")

    def _deserialize_payload(self, kind: str, payload_json: str) -> object | None:
        payload = json.loads(payload_json)
        if kind == "query":
            return str(payload.get("query") or "")
        if kind == "results":
            tracks = [TrackResult(**track_payload) for track_payload in payload.get("tracks", [])]
            return StoredSearchResults(query=str(payload.get("query") or ""), tracks=tracks)
        return None
