import asyncio

import pytest

from bot.services.metadata import MetadataSearchService
from bot.services.models import TrackResult


def _track(provider_id: str, title: str, artist: str) -> TrackResult:
    return TrackResult(
        source="itunes",
        provider_id=provider_id,
        title=title,
        artist=artist,
        album=None,
        duration_seconds=200,
        external_url=None,
        preview_url=None,
        artwork_url=None,
        genre=None,
    )


@pytest.mark.asyncio
async def test_metadata_search_coalesces_and_caches_duplicate_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    service = MetadataSearchService(session=None, cache_ttl_seconds=60)  # type: ignore[arg-type]
    calls = {"itunes": 0, "deezer": 0}

    async def fake_itunes(query: str, limit: int = 5) -> list[TrackResult]:
        calls["itunes"] += 1
        await asyncio.sleep(0.05)
        return [_track("1", "Yellow", "Coldplay")]

    async def fake_deezer(query: str, limit: int = 5) -> list[TrackResult]:
        calls["deezer"] += 1
        await asyncio.sleep(0.05)
        return [_track("2", "Yellow", "Coldplay")]

    monkeypatch.setattr(service._itunes, "search_tracks", fake_itunes)
    monkeypatch.setattr(service._deezer, "search_tracks", fake_deezer)

    first, second = await asyncio.gather(
        service.search_tracks("Yellow", limit=3),
        service.search_tracks("   yellow   ", limit=3),
    )
    third = await service.search_tracks("yellow", limit=3)

    assert calls == {"itunes": 1, "deezer": 1}
    assert len(first) == 1
    assert len(second) == 1
    assert len(third) == 1
    assert first[0].title == "Yellow"
