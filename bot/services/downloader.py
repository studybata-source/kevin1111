from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from bot.services.models import AudioSource, DownloadProgress, DownloadedAudio
from bot.utils.system import ensure_executable_parent_on_path, find_executable


LOGGER = logging.getLogger(__name__)
NON_AUDIO_SUFFIXES = {".part", ".ytdl", ".jpg", ".jpeg", ".png", ".webp", ".json", ".description", ".vtt", ".srt"}
AUDIO_SUFFIXES = {".mp3", ".m4a", ".aac", ".opus", ".ogg", ".wav", ".flac", ".webm", ".mp4"}
SEARCH_POOL_SIZE = 8
PREFERRED_UPLOADER_HINTS = (
    "t-series",
    "zee music",
    "saregama",
    "sony music india",
    "tips official",
    "aditya music",
    "think music india",
    "lahari music",
    "speed records",
    "white hill music",
    "yrf music",
    "vevo",
    "topic",
)
NEGATIVE_RESULT_HINTS = {
    "karaoke": 12,
    "instrumental": 10,
    "reaction": 14,
    "teaser": 14,
    "trailer": 16,
    "whatsapp status": 16,
    "status": 12,
    "ringtone": 18,
    "shorts": 18,
    "slowed": 8,
    "reverb": 8,
    "lofi": 8,
    "8d": 8,
    "nightcore": 10,
    "sped up": 10,
    "bass boosted": 8,
    "cover": 8,
    "live": 12,
    "remix": 8,
    "dj": 7,
    "mashup": 10,
    "fanmade": 10,
    "jukebox": 20,
    "nonstop": 18,
    "full album": 18,
    "album songs": 18,
    "greatest hits": 20,
    "playlist": 16,
    "collection": 12,
    "medley": 12,
    "all songs": 18,
}
STOPWORDS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "from",
    "ft",
    "feat",
    "featuring",
    "in",
    "of",
    "official",
    "song",
    "the",
    "video",
    "with",
}
TITLE_NOISE_PATTERNS = (
    r"\s*[\(\[]\s*(official\s+audio|official\s+video|official\s+music\s+video|lyric(?:s)?\s+video|visualizer|audio|music\s+video|video\s+song|full\s+video(?:\s+song)?|hd|hq|4k|128kbps|320kbps)\s*[\)\]]",
    r"\s*-\s*(official\s+audio|official\s+video|official\s+music\s+video|lyric(?:s)?\s+video|visualizer|audio|music\s+video|video\s+song|full\s+video(?:\s+song)?|hd|hq|4k|128kbps|320kbps)\s*$",
)
FALLBACK_SEARCH_SUFFIXES = (
    "",
    " official audio",
    " audio",
    " song",
)
YOUTUBE_VIDEO_RENDERER_RE = re.compile(
    r'"videoRenderer":\{.*?"videoId":"(?P<video_id>[^"]+)".*?"title":\{"runs":\[\{"text":"(?P<title>(?:\\.|[^"\\])*)".*?"(?:ownerText|longBylineText|shortBylineText)":\{"runs":\[\{"text":"(?P<owner>(?:\\.|[^"\\])*)"',
    re.DOTALL,
)


@dataclass(slots=True)
class _CachedResolvedSource:
    expires_at: float
    source: AudioSource | None


class ResolveTimeoutError(RuntimeError):
    pass


class YtDlpAudioService:
    def __init__(
        self,
        download_dir: Path,
        *,
        max_concurrent_resolves: int = 16,
        max_concurrent_downloads: int = 4,
        resolve_cache_ttl_seconds: float = 600.0,
        resolve_timeout_seconds: float = 45.0,
        resolve_attempt_timeout_seconds: float = 12.0,
    ) -> None:
        self._download_dir = Path(download_dir)
        self._ffmpeg_path = find_executable("ffmpeg")
        ensure_executable_parent_on_path(self._ffmpeg_path)
        self._resolve_semaphore = asyncio.Semaphore(max(1, max_concurrent_resolves))
        self._download_semaphore = asyncio.Semaphore(max(1, max_concurrent_downloads))
        self._resolve_executor = ThreadPoolExecutor(
            max_workers=max(1, max_concurrent_resolves),
            thread_name_prefix="yt-resolve",
        )
        self._download_executor = ThreadPoolExecutor(
            max_workers=max(1, max_concurrent_downloads),
            thread_name_prefix="yt-download",
        )
        self._resolve_cache_ttl_seconds = max(0.0, resolve_cache_ttl_seconds)
        self._resolve_timeout_seconds = max(5.0, resolve_timeout_seconds)
        self._resolve_attempt_timeout_seconds = max(3.0, resolve_attempt_timeout_seconds)
        self._resolve_cache: dict[str, _CachedResolvedSource] = {}
        self._resolve_inflight: dict[str, asyncio.Future[AudioSource | None]] = {}
        self._resolve_lock = asyncio.Lock()

    @property
    def ffmpeg_available(self) -> bool:
        return self._ffmpeg_path is not None

    async def resolve_query(self, query_or_url: str) -> AudioSource | None:
        query_key = _normalized_query_cache_key(query_or_url)
        if not query_key:
            return None

        cached = await self._get_cached_resolve(query_key)
        if cached is not None or query_key in self._resolve_cache:
            return _clone_source(cached)

        loop = asyncio.get_running_loop()
        async with self._resolve_lock:
            cached = self._get_cached_resolve_unlocked(query_key)
            if cached is not None or query_key in self._resolve_cache:
                return _clone_source(cached)

            future = self._resolve_inflight.get(query_key)
            if future is None:
                future = loop.create_future()
                future.add_done_callback(_consume_future_exception)
                self._resolve_inflight[query_key] = future
                leader = True
            else:
                leader = False

        if not leader:
            return _clone_source(await asyncio.shield(future))

        try:
            async with self._resolve_semaphore:
                resolved = await asyncio.wait_for(
                    loop.run_in_executor(self._resolve_executor, self._resolve_query_sync, query_or_url),
                    timeout=self._resolve_timeout_seconds,
                )
            await self._store_cached_resolve(query_key, resolved)
            future.set_result(resolved)
            return _clone_source(resolved)
        except TimeoutError as exc:
            error = ResolveTimeoutError("Source lookup timed out.")
            future.set_exception(error)
            raise error from exc
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            async with self._resolve_lock:
                self._resolve_inflight.pop(query_key, None)

    async def download_from_source(
        self,
        source: AudioSource,
        quality_preset: str,
        audio_format: str = "mp3",
        *,
        progress_callback: Callable[[DownloadProgress], Awaitable[None]] | None = None,
        cancel_event: threading.Event | None = None,
        timeout_seconds: float | None = None,
    ) -> DownloadedAudio:
        async with self._download_semaphore:
            loop = asyncio.get_running_loop()
            task = loop.run_in_executor(
                self._download_executor,
                self._download_from_source_sync,
                source,
                quality_preset,
                audio_format,
                progress_callback,
                loop,
                cancel_event,
            )
            if timeout_seconds is None:
                return await task
            return await asyncio.wait_for(task, timeout=timeout_seconds)

    async def cleanup(self, downloaded_audio: DownloadedAudio) -> None:
        await asyncio.to_thread(shutil.rmtree, downloaded_audio.cleanup_dir, True)

    async def cleanup_stale_jobs(self, max_age_hours: int) -> None:
        await asyncio.to_thread(self._cleanup_stale_jobs_sync, max_age_hours)

    async def close(self) -> None:
        await asyncio.gather(
            asyncio.to_thread(self._resolve_executor.shutdown, wait=True, cancel_futures=True),
            asyncio.to_thread(self._download_executor.shutdown, wait=True, cancel_futures=True),
        )

    def _resolve_query_sync(self, query_or_url: str) -> AudioSource | None:
        query_or_url = query_or_url.strip()
        if not query_or_url:
            return None

        targets = _resolve_targets(query_or_url)
        if _looks_like_url(query_or_url):
            targets_to_try = targets
        else:
            targets_to_try = targets[:1]

        for target, score_query in targets_to_try:
            resolved = self._resolve_target_sync(target, score_query)
            if resolved is not None:
                return resolved

        if not _looks_like_url(query_or_url):
            resolved = self._resolve_from_youtube_html(query_or_url)
            if resolved is not None:
                return resolved

            for target, score_query in targets[1:]:
                resolved = self._resolve_target_sync(target, score_query)
                if resolved is not None:
                    return resolved
        return None

    def _resolve_target_sync(self, target: str, score_query: str | None) -> AudioSource | None:
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            target,
            "--dump-single-json",
            "--skip-download",
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            "--socket-timeout",
            str(int(max(5, math.ceil(self._resolve_attempt_timeout_seconds)))),
            "--extractor-retries",
            "1",
            "--retries",
            "1",
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._resolve_attempt_timeout_seconds,
                check=False,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired:
            LOGGER.warning("Resolve attempt timed out for target=%r", target)
            return None
        except OSError as exc:
            LOGGER.warning("Resolve attempt failed for target=%r: %s", target, exc)
            return None

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            if stderr:
                LOGGER.warning("Resolve attempt failed for target=%r: %s", target, stderr)
            return None

        payload = (completed.stdout or "").strip()
        if not payload:
            return None

        try:
            info = json.loads(payload)
        except ValueError:
            LOGGER.warning("Resolve attempt returned invalid JSON for target=%r", target)
            return None

        resolved = _pick_best_entry(info, score_query)
        if not resolved:
            return None
        return _source_from_info(resolved)

    def _resolve_from_youtube_html(self, query: str) -> AudioSource | None:
        request = Request(
            f"https://www.youtube.com/results?search_query={quote_plus(query)}&hl=en",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        try:
            with urlopen(request, timeout=self._resolve_attempt_timeout_seconds) as response:
                payload = response.read().decode("utf-8", errors="replace")
        except (OSError, URLError, ValueError) as exc:
            LOGGER.warning("HTML resolver failed for query=%r: %s", query, exc)
            return None

        candidates = _extract_youtube_video_candidates(payload)
        if not candidates:
            return None

        resolved = _pick_best_entry({"entries": candidates}, query)
        if not resolved:
            return None
        return _source_from_info(resolved)

    def _download_from_source_sync(
        self,
        source: AudioSource,
        quality_preset: str,
        audio_format: str,
        progress_callback: Callable[[DownloadProgress], Awaitable[None]] | None,
        loop: asyncio.AbstractEventLoop,
        cancel_event: threading.Event | None,
    ) -> DownloadedAudio:
        temp_dir = self._download_dir / f"job-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        options: dict[str, object] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "restrictfilenames": True,
            "outtmpl": str(temp_dir / "%(title).120B-%(id)s.%(ext)s"),
            "format": _format_selector(quality_preset, audio_format, ffmpeg_available=self.ffmpeg_available),
        }

        def progress_hook(payload: dict[str, object]) -> None:
            if cancel_event and cancel_event.is_set():
                raise DownloadError("Cancelled by user.")
            if progress_callback is None:
                return
            progress = DownloadProgress(
                status=str(payload.get("status") or "unknown"),
                percent_text=str(payload.get("_percent_str")).strip() if payload.get("_percent_str") else None,
                speed_text=str(payload.get("_speed_str")).strip() if payload.get("_speed_str") else None,
                eta_text=str(payload.get("_eta_str")).strip() if payload.get("_eta_str") else None,
                downloaded_bytes=int(payload.get("downloaded_bytes"))
                if isinstance(payload.get("downloaded_bytes"), (int, float))
                else None,
                total_bytes=int(payload.get("total_bytes"))
                if isinstance(payload.get("total_bytes"), (int, float))
                else None,
            )
            loop.call_soon_threadsafe(asyncio.create_task, progress_callback(progress))

        options["progress_hooks"] = [progress_hook]

        if self._ffmpeg_path:
            options["ffmpeg_location"] = self._ffmpeg_path
            postprocessors = _postprocessors(audio_format, quality_preset)
            if postprocessors:
                options["postprocessors"] = postprocessors

        target = source.webpage_url or source.source_key
        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(target, download=True)
        except DownloadError as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(f"Download failed: {exc}") from exc

        resolved = _pick_entry(info) or {}
        file_path = _find_downloaded_file(temp_dir)
        if file_path is None:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError("No audio file was produced by the downloader.")

        refreshed_source = _source_from_info(resolved or {
            "id": source.source_key,
            "title": source.title,
            "artist": source.artist,
            "track": source.title,
            "webpage_url": source.webpage_url,
        })

        return DownloadedAudio(
            source=refreshed_source,
            file_path=file_path,
            file_size_bytes=file_path.stat().st_size if file_path.exists() else None,
            cleanup_dir=temp_dir,
            audio_title=refreshed_source.title,
            audio_performer=refreshed_source.artist,
        )

    def _cleanup_stale_jobs_sync(self, max_age_hours: int) -> None:
        if max_age_hours <= 0:
            return
        cutoff_seconds = max_age_hours * 3600
        if not self._download_dir.exists():
            return
        for path in self._download_dir.glob("job-*"):
            if not path.is_dir():
                continue
            age_seconds = max(0.0, time.time() - path.stat().st_mtime)
            if age_seconds >= cutoff_seconds:
                shutil.rmtree(path, ignore_errors=True)

    async def _get_cached_resolve(self, query_key: str) -> AudioSource | None:
        async with self._resolve_lock:
            return self._get_cached_resolve_unlocked(query_key)

    def _get_cached_resolve_unlocked(self, query_key: str) -> AudioSource | None:
        cached = self._resolve_cache.get(query_key)
        if cached is None:
            return None
        if cached.expires_at <= time.monotonic():
            self._resolve_cache.pop(query_key, None)
            return None
        return cached.source

    async def _store_cached_resolve(self, query_key: str, source: AudioSource | None) -> None:
        async with self._resolve_lock:
            self._cleanup_expired_resolves_unlocked()
            self._resolve_cache[query_key] = _CachedResolvedSource(
                expires_at=time.monotonic() + self._resolve_cache_ttl_seconds,
                source=_clone_source(source),
            )

    def _cleanup_expired_resolves_unlocked(self) -> None:
        now = time.monotonic()
        expired_keys = [key for key, cached in self._resolve_cache.items() if cached.expires_at <= now]
        for key in expired_keys:
            self._resolve_cache.pop(key, None)


def _resolve_targets(query_or_url: str) -> list[tuple[str, str | None]]:
    stripped = query_or_url.strip()
    if not stripped:
        return []
    if _looks_like_url(stripped):
        return [(stripped, None)]

    normalized = " ".join(stripped.split())
    targets: list[tuple[str, str | None]] = []
    seen: set[str] = set()

    for suffix in FALLBACK_SEARCH_SUFFIXES:
        search_query = f"{normalized}{suffix}".strip()
        pool_size = SEARCH_POOL_SIZE if not suffix else 2
        target = f"ytsearch{pool_size}:{search_query}"
        if target in seen:
            continue
        targets.append((target, normalized))
        seen.add(target)

    plain_query = normalized.replace(" - ", " ")
    if plain_query != normalized:
        target = f"ytsearch2:{plain_query}"
        if target not in seen:
            targets.append((target, plain_query))

    return targets


def _extract_youtube_video_candidates(payload: str) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    seen_video_ids: set[str] = set()

    matches = list(YOUTUBE_VIDEO_RENDERER_RE.finditer(payload))
    for index, match in enumerate(matches):
        video_id = match.group("video_id")
        if not video_id or video_id in seen_video_ids:
            continue

        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(payload)
        block = payload[match.start() : next_start]
        title = _decode_json_text_fragment(match.group("title"))
        owner = _decode_json_text_fragment(match.group("owner"))
        if not title:
            continue

        candidates.append(
            {
                "id": video_id,
                "title": title,
                "uploader": owner or None,
                "channel": owner or None,
                "duration": _extract_youtube_duration_seconds(block),
                "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
                "extractor_key": "Youtube",
            }
        )
        seen_video_ids.add(video_id)

    return candidates


def _decode_json_text_fragment(value: str | None) -> str:
    if not value:
        return ""
    try:
        decoded = json.loads(f'"{value}"')
    except ValueError:
        decoded = value.replace('\\"', '"').replace("\\/", "/")
    return _normalize_spaces(unescape(decoded))


def _extract_youtube_duration_seconds(block: str) -> int | None:
    match = re.search(r'"lengthText":\{"simpleText":"(?P<duration>[^"]+)"', block)
    if not match:
        return None
    return _parse_duration_text(match.group("duration"))


def _parse_duration_text(value: str | None) -> int | None:
    if not value:
        return None

    parts = [part for part in value.split(":") if part.isdigit()]
    if len(parts) == 2:
        minutes, seconds = (int(part) for part in parts)
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = (int(part) for part in parts)
        return hours * 3600 + minutes * 60 + seconds
    return None


def _pick_entry(info: dict[str, object] | None) -> dict[str, object] | None:
    if not info:
        return None
    entries = info.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                return entry
        return None
    return info


def _pick_best_entry(info: dict[str, object] | None, query: str | None = None) -> dict[str, object] | None:
    if not info:
        return None

    entries = info.get("entries")
    if not isinstance(entries, list):
        return info

    candidates = [entry for entry in entries if isinstance(entry, dict)]
    if not candidates:
        return None
    if not query:
        return candidates[0]
    return max(candidates, key=lambda entry: _score_search_result(entry, query))


def _source_from_info(info: dict[str, object]) -> AudioSource:
    raw_title = str(info.get("track") or info.get("title") or "Unknown title")
    raw_artist = info.get("artist") or info.get("uploader") or info.get("channel") or info.get("creator")
    title, artist = _clean_source_metadata(raw_title, str(raw_artist) if raw_artist else None)
    album = info.get("album")
    duration = info.get("duration")
    extractor = info.get("extractor_key") or info.get("extractor")
    media_id = info.get("id")
    webpage_url = info.get("webpage_url") or info.get("original_url") or info.get("url")
    estimated_size = info.get("filesize") or info.get("filesize_approx")
    source_key = str(f"{extractor}:{media_id}" if extractor and media_id else webpage_url or media_id or title)

    return AudioSource(
        source_key=source_key,
        title=title,
        artist=str(artist) if artist else None,
        album=str(album) if album else None,
        duration_seconds=int(duration) if isinstance(duration, (int, float)) else None,
        webpage_url=str(webpage_url) if webpage_url else None,
        thumbnail_url=str(info.get("thumbnail")) if info.get("thumbnail") else None,
        extractor=str(extractor) if extractor else None,
        estimated_size_bytes=int(estimated_size) if isinstance(estimated_size, (int, float)) else None,
        is_live=bool(info.get("is_live")),
    )


def _score_search_result(info: dict[str, object], query: str) -> float:
    title = str(info.get("track") or info.get("title") or "")
    artist = str(info.get("artist") or info.get("uploader") or info.get("channel") or info.get("creator") or "")
    album = str(info.get("album") or "")
    query_text = _normalize_text(query)
    title_text = _normalize_text(title)
    artist_text = _normalize_text(artist)
    album_text = _normalize_text(album)

    query_terms = _significant_tokens(query)
    title_terms = _significant_tokens(title)
    artist_terms = _significant_tokens(artist)
    album_terms = _significant_tokens(album)
    combined_terms = title_terms | artist_terms | album_terms

    score = 0.0
    if query_text and title_text == query_text:
        score += 90
    elif query_text and query_text in title_text:
        score += 45

    combined_text = _normalize_text(f"{artist} {title}")
    if query_text and combined_text == query_text:
        score += 75
    elif query_text and query_text in combined_text:
        score += 28

    title_matches = len(query_terms & title_terms)
    artist_matches = len(query_terms & artist_terms)
    album_matches = len(query_terms & album_terms)
    score += title_matches * 7
    score += artist_matches * 5
    score += album_matches * 3

    if query_terms and query_terms.issubset(combined_terms):
        score += 18

    if "official audio" in title_text or "provided to youtube by" in artist_text:
        score += 14
    elif "official video" in title_text or "official music video" in title_text:
        score += 12
    elif "official lyric" in title_text or "official lyrics" in title_text:
        score += 8
    elif "lyric video" in title_text or "lyrics video" in title_text:
        score += 3

    preferred_uploader = False
    for hint in PREFERRED_UPLOADER_HINTS:
        if hint in artist_text:
            preferred_uploader = True
            score += 12 if hint != "topic" else 8

    if len(query_terms) >= 2 and title_matches >= max(2, len(query_terms) - 1) and artist_matches == 0 and not preferred_uploader:
        score -= 40
    elif len(query_terms) >= 2 and title_matches >= 1 and artist_matches == 0 and not preferred_uploader:
        score -= 12

    haystack = f"{title_text} {artist_text} {album_text}".strip()
    for hint, penalty in NEGATIVE_RESULT_HINTS.items():
        wanted = hint in query_text
        present = hint in haystack
        if wanted and present:
            score += 8
        elif present:
            score -= penalty

    duration = info.get("duration")
    if isinstance(duration, (int, float)):
        if 120 <= duration <= 420:
            score += 6
        elif duration < 60:
            score -= 25
        elif duration > 900:
            score -= 18

    view_count = info.get("view_count")
    if isinstance(view_count, (int, float)) and view_count > 0:
        score += min(8.0, math.log10(float(view_count) + 1))

    return score


def _clean_source_metadata(title: str, artist: str | None) -> tuple[str, str | None]:
    clean_title = _normalize_spaces(title)
    clean_artist = _strip_artist_noise(_normalize_spaces(artist)) if artist else None

    if clean_artist:
        artist_prefix = f"{clean_artist} - "
        if clean_title.casefold().startswith(artist_prefix.casefold()):
            clean_title = clean_title[len(artist_prefix) :]

    if not clean_artist and " - " in clean_title:
        left, right = clean_title.split(" - ", 1)
        if 1 < len(left) <= 60 and 1 < len(right) <= 150:
            clean_artist = _strip_artist_noise(left)
            clean_title = right

    clean_title = _strip_title_noise(clean_title)
    clean_title = _normalize_spaces(clean_title) or "Unknown title"
    clean_artist = _normalize_spaces(clean_artist) if clean_artist else None
    return clean_title, clean_artist


def _strip_title_noise(title: str) -> str:
    cleaned = title
    previous = None
    while cleaned != previous:
        previous = cleaned
        for pattern in TITLE_NOISE_PATTERNS:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip(" -|_")
    return cleaned


def _strip_artist_noise(artist: str | None) -> str | None:
    if not artist:
        return None
    cleaned = re.sub(r"\s*-\s*topic$", "", artist, flags=re.IGNORECASE)
    return cleaned.strip(" -|_") or None


def _significant_tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {token for token in re.findall(r"\w+", text.casefold()) if len(token) > 1 and token not in STOPWORDS}


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(re.findall(r"\w+", text.casefold()))


def _normalize_spaces(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _find_downloaded_file(temp_dir: Path) -> Path | None:
    files = [path for path in temp_dir.rglob("*") if path.is_file() and path.suffix.lower() not in NON_AUDIO_SUFFIXES]
    if not files:
        return None

    audio_files = [path for path in files if path.suffix.lower() in AUDIO_SUFFIXES]
    candidates = audio_files or files
    candidates.sort(key=lambda path: (path.stat().st_size, path.stat().st_mtime), reverse=True)
    return candidates[0]


def _format_selector(quality_preset: str, audio_format: str, ffmpeg_available: bool) -> str:
    if ffmpeg_available:
        if quality_preset == "small":
            return "bestaudio[abr<=128]/bestaudio/worstaudio"
        if quality_preset == "balanced":
            return "bestaudio[abr<=192]/bestaudio"
        return "bestaudio/best"

    if audio_format == "opus":
        if quality_preset == "small":
            return "bestaudio[acodec*=opus][abr<=128]/bestaudio[abr<=128]/worstaudio"
        if quality_preset == "balanced":
            return "bestaudio[acodec*=opus][abr<=192]/bestaudio[abr<=192]/bestaudio"
        return "bestaudio[acodec*=opus]/bestaudio"
    if audio_format == "original":
        return "bestaudio/best"
    if quality_preset == "small":
        return "bestaudio[abr<=128][ext=m4a]/bestaudio[abr<=128]/worstaudio"
    if quality_preset == "balanced":
        return "bestaudio[abr<=192][ext=m4a]/bestaudio[abr<=192]/bestaudio"
    return "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio/best"


def _preferred_quality(quality_preset: str) -> str:
    if quality_preset == "small":
        return "128"
    if quality_preset == "balanced":
        return "192"
    return "320"


def _postprocessors(audio_format: str, quality_preset: str) -> list[dict[str, str]]:
    if audio_format == "original":
        return [{"key": "FFmpegMetadata"}]

    preferred_codec = "mp3"
    if audio_format == "m4a":
        preferred_codec = "m4a"
    elif audio_format == "opus":
        preferred_codec = "opus"

    return [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": preferred_codec,
            "preferredquality": _preferred_quality(quality_preset),
        },
        {"key": "FFmpegMetadata"},
    ]


def _looks_like_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://") or "www." in text


def _normalized_query_cache_key(query_or_url: str) -> str:
    stripped = query_or_url.strip()
    if not stripped:
        return ""
    if _looks_like_url(stripped):
        return stripped
    return " ".join(stripped.casefold().split())


def _clone_source(source: AudioSource | None) -> AudioSource | None:
    if source is None:
        return None
    return AudioSource(
        source_key=source.source_key,
        title=source.title,
        artist=source.artist,
        album=source.album,
        duration_seconds=source.duration_seconds,
        webpage_url=source.webpage_url,
        thumbnail_url=source.thumbnail_url,
        extractor=source.extractor,
        estimated_size_bytes=source.estimated_size_bytes,
        is_live=source.is_live,
    )


def _consume_future_exception(future: asyncio.Future[object]) -> None:
    if future.cancelled():
        return
    try:
        future.exception()
    except asyncio.CancelledError:
        return
