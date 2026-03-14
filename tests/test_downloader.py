import asyncio
import threading
import time
from pathlib import Path

import pytest

import bot.services.downloader as downloader_module
from bot.services.downloader import (
    ResolveTimeoutError,
    YtDlpAudioService,
    _extract_youtube_video_candidates,
    _format_selector,
    _looks_like_url,
    _pick_best_entry,
    _preferred_quality,
    _resolve_targets,
    _source_from_info,
)
from bot.services.models import AudioSource, DownloadedAudio


def test_format_selector_prefers_mp4a_when_ffmpeg_missing() -> None:
    selector = _format_selector("best", "mp3", ffmpeg_available=False)
    assert "mp4a" in selector or "m4a" in selector


def test_format_selector_prefers_opus_when_requested() -> None:
    selector = _format_selector("balanced", "opus", ffmpeg_available=False)
    assert "opus" in selector


def test_preferred_quality_values() -> None:
    assert _preferred_quality("small") == "128"
    assert _preferred_quality("balanced") == "192"
    assert _preferred_quality("best") == "320"


def test_looks_like_url() -> None:
    assert _looks_like_url("https://youtube.com/watch?v=abc")
    assert _looks_like_url("www.youtube.com/watch?v=abc")
    assert not _looks_like_url("coldplay yellow")


def test_source_from_info_extracts_metadata() -> None:
    source = _source_from_info(
        {
            "id": "abc123",
            "title": "Yellow",
            "artist": "Coldplay",
            "album": "Parachutes",
            "duration": 269,
            "extractor_key": "Youtube",
            "webpage_url": "https://youtube.com/watch?v=abc123",
            "filesize_approx": 12_000_000,
        }
    )

    assert source.source_key == "Youtube:abc123"
    assert source.title == "Yellow"
    assert source.artist == "Coldplay"
    assert source.album == "Parachutes"
    assert source.duration_seconds == 269
    assert source.estimated_size_bytes == 12_000_000


def test_source_from_info_cleans_youtube_style_metadata() -> None:
    source = _source_from_info(
        {
            "id": "abc123",
            "title": "Coldplay - Yellow (Official Video)",
            "uploader": "Coldplay",
            "extractor_key": "Youtube",
        }
    )

    assert source.title == "Yellow"
    assert source.artist == "Coldplay"


def test_pick_best_entry_prefers_clean_match_over_remix() -> None:
    best = _pick_best_entry(
        {
            "entries": [
                {
                    "title": "Kesariya (Slowed + Reverb)",
                    "uploader": "Random Channel",
                    "duration": 305,
                },
                {
                    "title": "Kesariya",
                    "uploader": "Sony Music India",
                    "duration": 269,
                    "view_count": 1000000,
                },
            ]
        },
        query="Kesariya",
    )

    assert best is not None
    assert best["title"] == "Kesariya"


def test_resolve_targets_include_fallback_queries() -> None:
    targets = _resolve_targets("Coldplay Yellow")

    assert targets[0][0] == "ytsearch8:Coldplay Yellow"
    assert any(target == "ytsearch2:Coldplay Yellow official audio" for target, _ in targets)
    assert all(score_query == "Coldplay Yellow" for _, score_query in targets)


def test_extract_youtube_video_candidates_decodes_titles() -> None:
    payload = """
    "videoRenderer":{"videoId":"abc123","title":{"runs":[{"text":"Brown\\u0020Munde"}]},
    "lengthText":{"simpleText":"4:12"},
    "ownerText":{"runs":[{"text":"AP\\u0020Dhillon"}]}}
    """

    candidates = _extract_youtube_video_candidates(payload)

    assert len(candidates) == 1
    assert candidates[0]["id"] == "abc123"
    assert candidates[0]["title"] == "Brown Munde"
    assert candidates[0]["uploader"] == "AP Dhillon"
    assert candidates[0]["duration"] == 252


@pytest.mark.asyncio
async def test_resolve_query_is_not_blocked_by_active_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = YtDlpAudioService(
        tmp_path,
        max_concurrent_resolves=1,
        max_concurrent_downloads=1,
    )
    source = AudioSource(
        source_key="Youtube:abc123",
        title="Yellow",
        artist="Coldplay",
        album=None,
        duration_seconds=269,
        webpage_url="https://youtube.com/watch?v=abc123",
        thumbnail_url=None,
        extractor="Youtube",
    )
    download_started = threading.Event()
    release_download = threading.Event()

    def fake_download(
        resolved_source: AudioSource,
        quality_preset: str,
        audio_format: str,
        progress_callback,
        loop,
        cancel_event,
    ) -> DownloadedAudio:
        download_started.set()
        release_download.wait(timeout=2.0)
        file_path = tmp_path / "downloaded.mp3"
        file_path.write_bytes(b"ok")
        return DownloadedAudio(
            source=resolved_source,
            file_path=file_path,
            file_size_bytes=file_path.stat().st_size,
            cleanup_dir=tmp_path,
            audio_title=resolved_source.title,
            audio_performer=resolved_source.artist,
        )

    def fake_resolve(query: str) -> AudioSource:
        return AudioSource(
            source_key="Youtube:def456",
            title="Paradise",
            artist="Coldplay",
            album=None,
            duration_seconds=278,
            webpage_url="https://youtube.com/watch?v=def456",
            thumbnail_url=None,
            extractor="Youtube",
        )

    monkeypatch.setattr(service, "_download_from_source_sync", fake_download)
    monkeypatch.setattr(service, "_resolve_query_sync", fake_resolve)

    download_task = asyncio.create_task(service.download_from_source(source, "best"))

    try:
        started = await asyncio.to_thread(download_started.wait, 1.0)
        assert started is True

        resolved = await asyncio.wait_for(service.resolve_query("coldplay paradise"), timeout=0.5)

        assert resolved is not None
        assert resolved.title == "Paradise"
    finally:
        release_download.set()
        await asyncio.wait_for(download_task, timeout=1.0)
        await service.close()


@pytest.mark.asyncio
async def test_resolve_query_coalesces_duplicate_requests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = YtDlpAudioService(tmp_path, max_concurrent_resolves=2, max_concurrent_downloads=1)
    calls = 0

    def fake_resolve(query: str) -> AudioSource:
        nonlocal calls
        calls += 1
        time.sleep(0.1)
        return AudioSource(
            source_key="Youtube:abc123",
            title="Yellow",
            artist="Coldplay",
            album=None,
            duration_seconds=269,
            webpage_url="https://youtube.com/watch?v=abc123",
            thumbnail_url=None,
            extractor="Youtube",
        )

    monkeypatch.setattr(service, "_resolve_query_sync", fake_resolve)

    try:
        first, second = await asyncio.gather(
            service.resolve_query("Coldplay Yellow"),
            service.resolve_query("   coldplay   yellow   "),
        )
    finally:
        await service.close()

    assert calls == 1
    assert first is not None
    assert second is not None
    assert first.source_key == second.source_key
    assert first is not second


@pytest.mark.asyncio
async def test_resolve_query_sync_uses_fallback_when_first_target_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = YtDlpAudioService(tmp_path, resolve_timeout_seconds=5, resolve_attempt_timeout_seconds=1)
    calls: list[str] = []

    def fake_resolve_target(target: str, score_query: str | None) -> AudioSource | None:
        calls.append(target)
        if "official audio" in target:
            return AudioSource(
                source_key="Youtube:abc123",
                title="Yellow",
                artist="Coldplay",
                album=None,
                duration_seconds=269,
                webpage_url="https://youtube.com/watch?v=abc123",
                thumbnail_url=None,
                extractor="Youtube",
            )
        return None

    monkeypatch.setattr(service, "_resolve_target_sync", fake_resolve_target)
    monkeypatch.setattr(service, "_resolve_from_youtube_html", lambda query: None)

    try:
        resolved = await service.resolve_query("Coldplay Yellow")
    finally:
        await service.close()

    assert resolved is not None
    assert resolved.title == "Yellow"
    assert calls[0] == "ytsearch8:Coldplay Yellow"
    assert any("official audio" in call for call in calls)


@pytest.mark.asyncio
async def test_resolve_query_uses_html_fallback_when_search_targets_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = YtDlpAudioService(tmp_path, resolve_timeout_seconds=5, resolve_attempt_timeout_seconds=1)

    class _FakeResponse:
        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'"videoRenderer":{"videoId":"abc123","title":{"runs":[{"text":"Yellow"}]},'
                b'"lengthText":{"simpleText":"4:29"},'
                b'"ownerText":{"runs":[{"text":"Coldplay"}]}}'
            )

    def fake_urlopen(request, timeout=0):
        return _FakeResponse()

    monkeypatch.setattr(service, "_resolve_target_sync", lambda *args, **kwargs: None)
    monkeypatch.setattr(downloader_module, "urlopen", fake_urlopen)

    try:
        resolved = await service.resolve_query("Coldplay Yellow")
    finally:
        await service.close()

    assert resolved is not None
    assert resolved.title == "Yellow"
    assert resolved.artist == "Coldplay"
    assert resolved.webpage_url == "https://www.youtube.com/watch?v=abc123"


@pytest.mark.asyncio
async def test_resolve_query_raises_timeout_when_worker_never_returns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = YtDlpAudioService(tmp_path, resolve_timeout_seconds=5, resolve_attempt_timeout_seconds=1)
    service._resolve_timeout_seconds = 0.1

    def fake_resolve_query_sync(query: str) -> AudioSource | None:
        time.sleep(0.4)
        return None

    monkeypatch.setattr(service, "_resolve_query_sync", fake_resolve_query_sync)

    try:
        with pytest.raises(ResolveTimeoutError):
            await service.resolve_query("Coldplay Yellow")
    finally:
        await service.close()
