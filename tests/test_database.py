from pathlib import Path

import pytest

from bot.database.repository import Database


@pytest.mark.asyncio
async def test_database_round_trip(tmp_path: Path) -> None:
    database = Database(tmp_path / "kevin11.db", default_quality_preset="balanced", default_audio_format="m4a")
    await database.connect()
    await database.initialize()

    try:
        await database.upsert_user(
            user_id=101,
            username="kevin11",
            full_name="Kevin Levin",
            language_code="en",
        )
        await database.upsert_chat(
            chat_id=202,
            chat_type="private",
            title="Kevin Levin",
            username="kevin11",
            is_active=True,
        )

        assert await database.get_quality_preset(101) == "balanced"
        assert await database.get_audio_format(101) == "m4a"

        await database.set_quality_preset(101, "best")
        assert await database.get_quality_preset(101) == "best"
        await database.set_audio_format(101, "opus")
        assert await database.get_audio_format(101) == "opus"

        delivery_settings = await database.get_user_delivery_settings(101)
        assert delivery_settings == {"quality_preset": "best", "audio_format": "opus"}

        await database.log_search(101, "coldplay yellow", 1)
        history = await database.get_recent_searches(101)
        assert history
        assert history[0]["query"] == "coldplay yellow"

        await database.upsert_cached_audio(
            source_key="Youtube:abc123",
            telegram_file_id="file_123",
            title="Yellow",
            performer="Coldplay",
            duration_seconds=269,
            file_size_bytes=12_345_678,
        )
        cached = await database.get_cached_audio("Youtube:abc123")
        assert cached is not None
        assert cached["telegram_file_id"] == "file_123"
        assert cached["file_size_bytes"] == 12_345_678

        await database.upsert_query_source("coldplay yellow", "Youtube:abc123")
        assert await database.get_query_source_key("coldplay yellow") == "Youtube:abc123"

        await database.log_download(
            user_id=101,
            chat_id=202,
            query="coldplay yellow",
            source_key="Youtube:abc123",
            title="Yellow",
            performer="Coldplay",
            status="sent",
        )
        stats = await database.get_stats()
        assert stats["users"] == 1
        assert stats["downloads"] == 1
        assert stats["searches"] == 1
    finally:
        await database.close()
