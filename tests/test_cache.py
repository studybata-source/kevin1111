from pathlib import Path

import pytest

from bot.database.repository import Database
from bot.services.models import TrackResult
from bot.utils.cache import SearchSessionStore


@pytest.mark.asyncio
async def test_search_session_store_round_trip() -> None:
    store = SearchSessionStore(ttl_seconds=60)
    tracks = [
        TrackResult(
            source="itunes",
            provider_id="1",
            title="Yellow",
            artist="Coldplay",
            album="Parachutes",
            duration_seconds=269,
            external_url=None,
            preview_url=None,
            artwork_url=None,
            genre="Alternative",
        )
    ]

    results_token = await store.put_results("yellow", tracks)
    query_token = await store.put_query("Coldplay - Yellow")

    stored_results = await store.get_results(results_token)
    assert stored_results is not None
    assert stored_results.query == "yellow"
    assert stored_results.tracks[0].title == "Yellow"
    assert await store.get_query(query_token) == "Coldplay - Yellow"


@pytest.mark.asyncio
async def test_search_session_store_rejects_wrong_kind() -> None:
    store = SearchSessionStore(ttl_seconds=60)
    query_token = await store.put_query("Adele - Hello")

    assert await store.get_results(query_token) is None


@pytest.mark.asyncio
async def test_search_session_store_can_use_database_backend(tmp_path: Path) -> None:
    database = Database(tmp_path / "kevin11.db")
    await database.connect()
    await database.initialize()

    try:
        writer = SearchSessionStore(ttl_seconds=60, db=database)
        reader = SearchSessionStore(ttl_seconds=60, db=database)
        token = await writer.put_query("Adele - Hello")

        assert await reader.get_query(token) == "Adele - Hello"
    finally:
        await database.close()
