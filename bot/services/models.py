from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class TrackResult:
    source: str
    provider_id: str
    title: str
    artist: str
    album: str | None
    duration_seconds: int | None
    external_url: str | None
    preview_url: str | None
    artwork_url: str | None
    genre: str | None


@dataclass(slots=True)
class LyricsResult:
    title: str
    artist: str
    plain_lyrics: str
    synced_lyrics: str | None = None


@dataclass(slots=True)
class AudioSource:
    source_key: str
    title: str
    artist: str | None
    album: str | None
    duration_seconds: int | None
    webpage_url: str | None
    thumbnail_url: str | None
    extractor: str | None
    estimated_size_bytes: int | None = None
    is_live: bool = False


@dataclass(slots=True)
class DownloadedAudio:
    source: AudioSource
    file_path: Path
    file_size_bytes: int | None
    cleanup_dir: Path
    audio_title: str
    audio_performer: str | None


@dataclass(slots=True)
class DownloadProgress:
    status: str
    percent_text: str | None
    speed_text: str | None
    eta_text: str | None
    downloaded_bytes: int | None
    total_bytes: int | None
