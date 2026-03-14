from bot.handlers.search import _best_track_match, _has_variant_hint
from bot.services.models import TrackResult


def test_best_track_match_prefers_full_song_match() -> None:
    tracks = [
        TrackResult(
            source="itunes",
            provider_id="1",
            title="Kesariya (Dance Mix)",
            artist="Pritam",
            album="Single",
            duration_seconds=210,
            external_url=None,
            preview_url=None,
            artwork_url=None,
            genre=None,
        ),
        TrackResult(
            source="itunes",
            provider_id="2",
            title="Kesariya",
            artist="Pritam, Arijit Singh & Amitabh Bhattacharya",
            album="Brahmastra",
            duration_seconds=269,
            external_url=None,
            preview_url=None,
            artwork_url=None,
            genre=None,
        ),
    ]

    best = _best_track_match("Kesariya Arijit Singh", tracks)

    assert best.provider_id == "2"


def test_variant_hint_detects_user_wanted_remix() -> None:
    assert _has_variant_hint("Kesariya slowed reverb") is True
    assert _has_variant_hint("Kesariya Arijit Singh") is False
