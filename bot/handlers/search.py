from __future__ import annotations

import time
from html import escape

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.constants import BUTTON_DOWNLOAD, BUTTON_SEARCH, MENU_TEXTS, QUALITY_LABELS
from bot.database.repository import Database
from bot.keyboards.inline import download_actions_keyboard, search_results_keyboard
from bot.keyboards.reply import main_menu_keyboard
from bot.services.downloader import ResolveTimeoutError, YtDlpAudioService
from bot.services.metadata import MetadataSearchService
from bot.services.models import AudioSource, DownloadProgress, DownloadedAudio, TrackResult
from bot.states import SearchStates
from bot.utils.cache import SearchSessionStore, StoredSearchResults
from bot.utils.download_jobs import DownloadJobRegistry, SharedWorkRegistry
from bot.utils.formatting import format_download_status, format_search_page
from bot.utils.users import remember_callback_context, remember_message_context


router = Router(name="search")
SEARCH_PAGE_SIZE = 3


@router.message(Command(commands=["search"]))
async def handle_search_command(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    db: Database,
    metadata: MetadataSearchService,
    downloader: YtDlpAudioService,
    settings: Settings,
    search_cache: SearchSessionStore,
) -> None:
    await remember_message_context(db, message)
    query = (command.args or "").strip()
    if not query:
        await state.set_state(SearchStates.waiting_for_search_query)
        await message.answer(
            "Send the song name or artist and I'll line up the cleanest matches.",
            reply_markup=main_menu_keyboard(message.chat.type),
        )
        return

    await state.clear()
    await _handle_search_request(message, query, db, metadata, downloader, settings, search_cache)


@router.channel_post(Command(commands=["search"]))
async def handle_channel_search_command(
    message: Message,
    command: CommandObject,
    db: Database,
    metadata: MetadataSearchService,
    downloader: YtDlpAudioService,
    settings: Settings,
    search_cache: SearchSessionStore,
) -> None:
    await remember_message_context(db, message)
    query = (command.args or "").strip()
    if not query:
        await message.answer("Use /search followed by a song name inside the channel.")
        return
    await _handle_search_request(message, query, db, metadata, downloader, settings, search_cache)


@router.message(F.text == BUTTON_SEARCH)
async def prompt_search_input(message: Message, state: FSMContext, db: Database) -> None:
    await remember_message_context(db, message)
    await state.set_state(SearchStates.waiting_for_search_query)
    await message.answer(
        "Send the song name or artist and I'll line up the cleanest matches.",
        reply_markup=main_menu_keyboard(message.chat.type),
    )


@router.message(StateFilter(SearchStates.waiting_for_search_query), F.text)
async def handle_waiting_search_input(
    message: Message,
    state: FSMContext,
    db: Database,
    metadata: MetadataSearchService,
    downloader: YtDlpAudioService,
    settings: Settings,
    search_cache: SearchSessionStore,
) -> None:
    await remember_message_context(db, message)
    await state.clear()
    await _handle_search_request(message, message.text.strip(), db, metadata, downloader, settings, search_cache)


@router.message(Command(commands=["download", "song"]))
async def handle_download_command(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    db: Database,
    metadata: MetadataSearchService,
    downloader: YtDlpAudioService,
    settings: Settings,
    search_cache: SearchSessionStore,
    download_jobs: DownloadJobRegistry,
    shared_downloads: SharedWorkRegistry,
) -> None:
    await remember_message_context(db, message)
    query = (command.args or "").strip()
    if not query:
        await state.set_state(SearchStates.waiting_for_download_query)
        await message.answer(
            "Send the song name, artist, or a supported link.",
            reply_markup=main_menu_keyboard(message.chat.type),
        )
        return

    await state.clear()
    await _handle_download_request(
        message,
        query,
        db,
        metadata,
        downloader,
        settings,
        search_cache,
        download_jobs,
        shared_downloads,
    )


@router.channel_post(Command(commands=["download", "song"]))
async def handle_channel_download_command(
    message: Message,
    command: CommandObject,
    db: Database,
    metadata: MetadataSearchService,
    downloader: YtDlpAudioService,
    settings: Settings,
    search_cache: SearchSessionStore,
    download_jobs: DownloadJobRegistry,
    shared_downloads: SharedWorkRegistry,
) -> None:
    await remember_message_context(db, message)
    query = (command.args or "").strip()
    if not query:
        await message.answer("Use /download followed by a song name or supported link.")
        return
    await _handle_download_request(
        message,
        query,
        db,
        metadata,
        downloader,
        settings,
        search_cache,
        download_jobs,
        shared_downloads,
    )


@router.message(F.text == BUTTON_DOWNLOAD)
async def prompt_download_input(message: Message, state: FSMContext, db: Database) -> None:
    await remember_message_context(db, message)
    await state.set_state(SearchStates.waiting_for_download_query)
    await message.answer(
        "Send the song name, artist, or a supported link.",
        reply_markup=main_menu_keyboard(message.chat.type),
    )


@router.message(StateFilter(SearchStates.waiting_for_download_query), F.text)
async def handle_waiting_download_input(
    message: Message,
    state: FSMContext,
    db: Database,
    metadata: MetadataSearchService,
    downloader: YtDlpAudioService,
    settings: Settings,
    search_cache: SearchSessionStore,
    download_jobs: DownloadJobRegistry,
    shared_downloads: SharedWorkRegistry,
) -> None:
    await remember_message_context(db, message)
    await state.clear()
    await _handle_download_request(
        message,
        message.text.strip(),
        db,
        metadata,
        downloader,
        settings,
        search_cache,
        download_jobs,
        shared_downloads,
    )


@router.message(StateFilter(None), F.chat.type == ChatType.PRIVATE, F.text)
async def handle_private_free_text_download(
    message: Message,
    db: Database,
    metadata: MetadataSearchService,
    downloader: YtDlpAudioService,
    settings: Settings,
    search_cache: SearchSessionStore,
    download_jobs: DownloadJobRegistry,
    shared_downloads: SharedWorkRegistry,
) -> None:
    if not message.text or message.chat.type != ChatType.PRIVATE:
        return

    text = message.text.strip()
    if not text or text in MENU_TEXTS or text.startswith("/"):
        return

    await remember_message_context(db, message)
    await _handle_download_request(
        message,
        text,
        db,
        metadata,
        downloader,
        settings,
        search_cache,
        download_jobs,
        shared_downloads,
    )


@router.message(StateFilter(None), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.text)
async def handle_group_text_download(
    message: Message,
    db: Database,
    metadata: MetadataSearchService,
    downloader: YtDlpAudioService,
    settings: Settings,
    search_cache: SearchSessionStore,
    download_jobs: DownloadJobRegistry,
    shared_downloads: SharedWorkRegistry,
) -> None:
    if not message.text or message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return

    text = message.text.strip()
    if not text or text in MENU_TEXTS or text.startswith("/"):
        return

    query = _extract_group_query(message, text, settings.bot_username)
    if not query:
        return

    await remember_message_context(db, message)
    await _handle_download_request(
        message,
        query,
        db,
        metadata,
        downloader,
        settings,
        search_cache,
        download_jobs,
        shared_downloads,
    )


@router.callback_query(F.data.startswith("search:page:"))
async def paginate_search_results(
    callback: CallbackQuery,
    db: Database,
    settings: Settings,
    search_cache: SearchSessionStore,
) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return

    await remember_callback_context(db, callback)
    _, _, token, page_text = callback.data.split(":", 3)
    search_results = await search_cache.get_results(token)
    if search_results is None:
        await callback.message.answer("That search session expired. Run /search again.")
        return

    try:
        page = max(0, int(page_text))
    except ValueError:
        return
    text, markup = _render_search_page(search_results, token, page, settings.bot_username)
    await _safe_edit_text(callback.message, text, reply_markup=markup, fallback_to_answer=True)


@router.callback_query(F.data.startswith("search:download:"))
async def download_search_result(
    callback: CallbackQuery,
    db: Database,
    downloader: YtDlpAudioService,
    settings: Settings,
    search_cache: SearchSessionStore,
    download_jobs: DownloadJobRegistry,
    shared_downloads: SharedWorkRegistry,
) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return

    await remember_callback_context(db, callback)
    _, _, token, index_text = callback.data.split(":", 3)
    track = await _get_track_from_token(search_cache, token, index_text)
    if track is None:
        await callback.message.answer("That search result expired. Run /search again.")
        return

    await _handle_download_request(
        callback.message,
        _music_query_from_track(track),
        db,
        None,
        downloader,
        settings,
        search_cache,
        download_jobs,
        shared_downloads,
        preferred_track=track,
        requesting_user_id=callback.from_user.id if callback.from_user else None,
    )


@router.callback_query(F.data.startswith("query:download:"))
async def download_from_query_token(
    callback: CallbackQuery,
    db: Database,
    downloader: YtDlpAudioService,
    settings: Settings,
    search_cache: SearchSessionStore,
    download_jobs: DownloadJobRegistry,
    shared_downloads: SharedWorkRegistry,
) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return

    await remember_callback_context(db, callback)
    token = callback.data.rsplit(":", 1)[-1]
    query = await search_cache.get_query(token)
    if not query:
        await callback.message.answer("That saved query expired. Send the song name again.")
        return

    await _handle_download_request(
        callback.message,
        query,
        db,
        None,
        downloader,
        settings,
        search_cache,
        download_jobs,
        shared_downloads,
        requesting_user_id=callback.from_user.id if callback.from_user else None,
    )


async def _handle_search_request(
    message: Message,
    query: str,
    db: Database,
    metadata: MetadataSearchService,
    downloader: YtDlpAudioService,
    settings: Settings,
    search_cache: SearchSessionStore,
) -> None:
    query = query.strip()
    if not query:
        await message.answer("Send a real song name or artist.", reply_markup=main_menu_keyboard(message.chat.type))
        return

    status_message = await message.answer("Lining up the best picks...", reply_markup=main_menu_keyboard(message.chat.type))
    tracks = await _search_tracks(query, metadata, downloader, limit=max(settings.search_limit * 2, 6))
    if message.from_user:
        await db.log_search(message.from_user.id, query, len(tracks))

    if not tracks:
        await _safe_edit_text(
            status_message,
            "Couldn't lock a solid match. Try song name + artist.",
            fallback_to_answer=True,
        )
        return

    token = await search_cache.put_results(query, tracks)
    text, markup = _render_search_page(
        StoredSearchResults(query=query, tracks=tracks),
        token,
        page=0,
        bot_username=settings.bot_username,
    )
    await _safe_edit_text(status_message, text, reply_markup=markup, fallback_to_answer=True)


async def _handle_download_request(
    message: Message,
    query: str,
    db: Database,
    metadata: MetadataSearchService | None,
    downloader: YtDlpAudioService,
    settings: Settings,
    search_cache: SearchSessionStore,
    download_jobs: DownloadJobRegistry,
    shared_downloads: SharedWorkRegistry,
    preferred_track: TrackResult | None = None,
    requesting_user_id: int | None = None,
) -> None:
    query = query.strip()
    if not query:
        await message.answer("Send a real song name or link.", reply_markup=main_menu_keyboard(message.chat.type))
        return

    effective_user_id = requesting_user_id
    if effective_user_id is None and message.from_user and not message.from_user.is_bot:
        effective_user_id = message.from_user.id

    job_key = _job_key(message, effective_user_id)
    job = await download_jobs.start(job_key, query)
    if job is None:
        await message.answer(
            "A download is already running for you. Wait for it to finish or send /cancel.",
            reply_markup=main_menu_keyboard(message.chat.type),
        )
        return

    status_message = await message.answer("Hunting your track...", reply_markup=main_menu_keyboard(message.chat.type))
    downloaded_audio: DownloadedAudio | None = None
    source: AudioSource | None = None
    cache_key: str | None = None
    owns_shared_download = False
    shared_download_failure: BaseException | None = None
    shared_download_succeeded = False
    resolved_query = query
    query_token = await search_cache.put_query(query)
    try:
        quality_preset = settings.default_quality_preset
        audio_format = "mp3"
        if effective_user_id is not None:
            delivery_settings = await db.get_user_delivery_settings(effective_user_id)
            quality_preset = delivery_settings["quality_preset"]

        query_cache_key = _normalized_query_key(query)
        cached_source_key = await db.get_query_source_key(query_cache_key)
        if cached_source_key:
            cached_audio = await db.get_cached_audio(_audio_cache_key(cached_source_key, quality_preset, audio_format))
            if cached_audio:
                delivered = await _deliver_cached_audio(
                    message,
                    status_message,
                    db,
                    settings,
                    query_token=query_token,
                    query=query,
                    source_key=cached_source_key,
                    cached_audio=cached_audio,
                    quality_preset=quality_preset,
                    audio_format=audio_format,
                    source=None,
                    user_id=effective_user_id,
                )
                if delivered:
                    return

        resolved_query = _music_query_from_track(preferred_track) if preferred_track else query
        inferred_track = preferred_track
        if inferred_track is None:
            resolved_query, inferred_track = await _refine_download_query(query, metadata)
        source = await downloader.resolve_query(resolved_query)
        if effective_user_id is not None:
            await db.log_search(effective_user_id, resolved_query, 1 if source else 0)

        if source is None:
            await _safe_edit_text(
                status_message,
                "Couldn't lock a solid match. Try song name + artist.",
                fallback_to_answer=True,
            )
            return

        if inferred_track is not None:
            source.title = inferred_track.title
            source.artist = inferred_track.artist
            if not source.album:
                source.album = inferred_track.album

        validation_error = _validate_source(source, settings)
        if validation_error:
            await _safe_edit_text(status_message, validation_error, fallback_to_answer=True)
            await db.log_download(
                chat_id=message.chat.id,
                query=resolved_query,
                source_key=source.source_key,
                title=source.title,
                performer=source.artist,
                status="blocked",
                user_id=effective_user_id,
            )
            return

        query_token = await search_cache.put_query(
            _music_query_from_track(inferred_track) if inferred_track is not None else _music_query_from_source(source)
        )
        cache_key = _audio_cache_key(source.source_key, quality_preset, audio_format)
        while True:
            cached_audio = await db.get_cached_audio(cache_key)
            if cached_audio:
                delivered = await _deliver_cached_audio(
                    message,
                    status_message,
                    db,
                    settings,
                    query_token=query_token,
                    query=resolved_query,
                    source_key=source.source_key,
                    cached_audio=cached_audio,
                    quality_preset=quality_preset,
                    audio_format=audio_format,
                    source=source,
                    user_id=effective_user_id,
                )
                if delivered:
                    await _remember_query_cache_entries(
                        db,
                        source.source_key,
                        query,
                        resolved_query,
                        inferred_track,
                    )
                    return

            owns_shared_download, shared_download = await shared_downloads.claim(cache_key)
            if owns_shared_download:
                break

            await _safe_edit_text(
                status_message,
                "That track is already being pulled for someone else. Reusing it as soon as it lands...",
                fallback_to_answer=True,
            )
            try:
                await asyncio.wait_for(asyncio.shield(shared_download), timeout=settings.download_timeout_sec)
            except TimeoutError:
                await _safe_edit_text(
                    status_message,
                    "Another request for that track is taking too long. Try again in a moment.",
                    fallback_to_answer=True,
                )
                return
            except Exception:
                continue

        await _safe_edit_text(
            status_message,
            format_download_status(
                title=source.title,
                performer=source.artist,
                phase="Match locked. Pulling the file...",
            ),
            fallback_to_answer=True,
        )

        last_progress_update = 0.0

        async def on_progress(progress: DownloadProgress) -> None:
            nonlocal last_progress_update
            now = time.monotonic()
            if progress.status == "downloading" and now - last_progress_update < 0.8:
                return
            last_progress_update = now

            phase = "Final touch..." if progress.status == "finished" else "Pulling the file..."
            await _safe_edit_text(
                status_message,
                format_download_status(
                    title=source.title,
                    performer=source.artist,
                    percent_text=progress.percent_text if progress.status == "downloading" else None,
                    speed_text=progress.speed_text if progress.status == "downloading" else None,
                    eta_text=progress.eta_text if progress.status == "downloading" else None,
                    phase=phase,
                ),
            )

        downloaded_audio = await downloader.download_from_source(
            source,
            quality_preset,
            audio_format,
            progress_callback=on_progress,
            cancel_event=job.cancel_event,
            timeout_seconds=settings.download_timeout_sec,
        )
        if inferred_track is not None:
            downloaded_audio.audio_title = inferred_track.title
            downloaded_audio.audio_performer = inferred_track.artist
            downloaded_audio.source.title = inferred_track.title
            downloaded_audio.source.artist = inferred_track.artist
            if not downloaded_audio.source.album:
                downloaded_audio.source.album = inferred_track.album
        input_file = FSInputFile(downloaded_audio.file_path)

        await _safe_edit_text(
            status_message,
            format_download_status(
                title=downloaded_audio.audio_title,
                performer=downloaded_audio.audio_performer,
                phase="Dropping it in chat...",
            ),
        )

        try:
            sent = await message.answer_audio(
                audio=input_file,
                title=downloaded_audio.audio_title,
                performer=downloaded_audio.audio_performer,
                duration=downloaded_audio.source.duration_seconds,
                caption=_audio_delivery_caption(
                    downloaded_audio.source,
                    quality_preset,
                    audio_format=audio_format,
                    file_size_bytes=downloaded_audio.file_size_bytes,
                ),
                reply_markup=download_actions_keyboard(query_token, settings.bot_username),
            )
            if sent.audio:
                await db.upsert_cached_audio(
                    source_key=_audio_cache_key(downloaded_audio.source.source_key, quality_preset, audio_format),
                    telegram_file_id=sent.audio.file_id,
                    title=downloaded_audio.audio_title,
                    performer=downloaded_audio.audio_performer,
                    duration_seconds=downloaded_audio.source.duration_seconds,
                    file_size_bytes=downloaded_audio.file_size_bytes,
                )
            await _remember_query_cache_entries(
                db,
                downloaded_audio.source.source_key,
                query,
                resolved_query,
                inferred_track,
            )
            await db.log_download(
                chat_id=message.chat.id,
                query=resolved_query,
                source_key=downloaded_audio.source.source_key,
                title=downloaded_audio.audio_title,
                performer=downloaded_audio.audio_performer,
                status="sent",
                user_id=effective_user_id,
            )
            final_text = f"Dropped in chat. {QUALITY_LABELS[quality_preset]} is on."
            if not downloader.ffmpeg_available:
                final_text += " ffmpeg is missing, so Telegram got the cleanest raw format available."
            await _safe_edit_text(status_message, final_text, fallback_to_answer=True)
            shared_download_succeeded = True
        except TelegramBadRequest:
            await message.answer_document(
                document=input_file,
                caption=(
                    f"Track file ready.\nQuality: {QUALITY_LABELS[quality_preset]}\n"
                    "Format: MP3\n"
                    f"Size: {_format_file_size(downloaded_audio.file_size_bytes)}\n"
                    "Telegram wouldn't take it as audio, so it landed as a file instead."
                ),
                reply_markup=download_actions_keyboard(query_token, settings.bot_username),
            )
            await _remember_query_cache_entries(
                db,
                downloaded_audio.source.source_key,
                query,
                resolved_query,
                inferred_track,
            )
            await db.log_download(
                chat_id=message.chat.id,
                query=resolved_query,
                source_key=downloaded_audio.source.source_key,
                title=downloaded_audio.audio_title,
                performer=downloaded_audio.audio_performer,
                status="document",
                user_id=effective_user_id,
            )
            await _safe_edit_text(
                status_message,
                "Done. Telegram forced a file send on that one.",
                fallback_to_answer=True,
            )
            shared_download_succeeded = True
    except ResolveTimeoutError:
        shared_download_failure = ResolveTimeoutError("Source lookup timed out.")
        await _safe_edit_text(
            status_message,
            "Source lookup timed out before the file pull started. Try again in a moment.",
            fallback_to_answer=True,
        )
        if effective_user_id is not None:
            await db.log_download(
                chat_id=message.chat.id,
                query=resolved_query,
                source_key="resolve-timeout",
                title=query,
                performer=None,
                status="resolve_timeout",
                user_id=effective_user_id,
            )
    except TimeoutError:
        shared_download_failure = TimeoutError("Download timed out.")
        await _safe_edit_text(
            status_message,
            "Download timed out. Try again later or choose a shorter track.",
            fallback_to_answer=True,
        )
        if source is not None:
            await db.log_download(
                chat_id=message.chat.id,
                query=resolved_query,
                source_key=source.source_key,
                title=source.title,
                performer=source.artist,
                status="timeout",
                user_id=effective_user_id,
            )
    except RuntimeError as exc:
        shared_download_failure = exc
        lowered = str(exc).lower()
        if "cancelled by user" in lowered:
            message_text = "Download cancelled."
            status = "cancelled"
        else:
            message_text = f"That drop failed: <code>{escape(str(exc))}</code>"
            status = "failed"
        await _safe_edit_text(status_message, message_text, fallback_to_answer=True)
        if source is not None:
            await db.log_download(
                chat_id=message.chat.id,
                query=resolved_query,
                source_key=source.source_key,
                title=source.title,
                performer=source.artist,
                status=status,
                user_id=effective_user_id,
            )
    finally:
        if cache_key is not None and owns_shared_download:
            await shared_downloads.finish(
                cache_key,
                None if shared_download_succeeded else shared_download_failure or RuntimeError("Download did not finish."),
            )
        await download_jobs.finish(job_key)
        if downloaded_audio is not None:
            await downloader.cleanup(downloaded_audio)


def _render_search_page(
    search_results: StoredSearchResults,
    token: str,
    page: int,
    bot_username: str | None = None,
) -> tuple[str, object]:
    total_pages = max(1, (len(search_results.tracks) + SEARCH_PAGE_SIZE - 1) // SEARCH_PAGE_SIZE)
    safe_page = max(0, min(page, total_pages - 1))
    start_index = safe_page * SEARCH_PAGE_SIZE
    page_tracks = search_results.tracks[start_index : start_index + SEARCH_PAGE_SIZE]
    text = format_search_page(search_results.query, search_results.tracks, safe_page, total_pages)
    markup = search_results_keyboard(
        token=token,
        page=safe_page,
        total_pages=total_pages,
        page_count=len(page_tracks),
        start_index=start_index,
        bot_username=bot_username,
    )
    return text, markup


async def _search_tracks(
    query: str,
    metadata: MetadataSearchService,
    downloader: YtDlpAudioService,
    limit: int,
) -> list[TrackResult]:
    tracks = await metadata.search_tracks(query, limit=limit)
    if tracks:
        return tracks

    try:
        fallback = await downloader.resolve_query(query)
    except ResolveTimeoutError:
        return []
    if fallback is None:
        return []

    return [
        TrackResult(
            source="yt_dlp",
            provider_id=fallback.source_key,
            title=fallback.title,
            artist=fallback.artist or "Unknown artist",
            album=fallback.album,
            duration_seconds=fallback.duration_seconds,
            external_url=fallback.webpage_url,
            preview_url=None,
            artwork_url=fallback.thumbnail_url,
            genre=None,
        )
    ]


async def _refine_download_query(query: str, metadata: MetadataSearchService | None) -> tuple[str, TrackResult | None]:
    if metadata is None or _query_looks_like_url(query) or _has_variant_hint(query):
        return query, None

    tracks = await metadata.search_tracks(query, limit=4)
    if not tracks:
        return query, None

    best_track = _best_track_match(query, tracks)
    return _music_query_from_track(best_track), best_track


def _best_track_match(query: str, tracks: list[TrackResult]) -> TrackResult:
    query_tokens = _query_tokens(query)
    if not query_tokens:
        return tracks[0]

    def score(track: TrackResult) -> int:
        title_tokens = _query_tokens(track.title)
        artist_tokens = _query_tokens(track.artist)
        album_tokens = _query_tokens(track.album or "")
        track_tokens = title_tokens | artist_tokens | album_tokens
        points = len(query_tokens & title_tokens) * 4
        points += len(query_tokens & artist_tokens) * 3
        points += len(query_tokens & album_tokens)
        if query_tokens.issubset(track_tokens):
            points += 10
        return points

    return max(tracks, key=score)


def _has_variant_hint(query: str) -> bool:
    lowered = query.casefold()
    return any(
        hint in lowered
        for hint in (
            "acoustic",
            "cover",
            "dj",
            "edit",
            "instrumental",
            "karaoke",
            "live",
            "lofi",
            "mashup",
            "nightcore",
            "reverb",
            "remix",
            "slowed",
            "sped up",
            "unplugged",
            "version",
        )
    )


def _query_looks_like_url(text: str) -> bool:
    lowered = text.casefold()
    return lowered.startswith("http://") or lowered.startswith("https://") or "www." in lowered


def _query_tokens(text: str) -> set[str]:
    return {token for token in "".join(ch if ch.isalnum() else " " for ch in text.casefold()).split() if len(token) > 1}


async def _get_track_from_token(
    search_cache: SearchSessionStore,
    token: str,
    index_text: str,
) -> TrackResult | None:
    search_results = await search_cache.get_results(token)
    if search_results is None:
        return None
    try:
        index = int(index_text)
    except ValueError:
        return None
    if index < 0 or index >= len(search_results.tracks):
        return None
    return search_results.tracks[index]


def _music_query_from_track(track: TrackResult) -> str:
    return f"{track.artist} - {track.title}"


def _music_query_from_source(source: AudioSource) -> str:
    if source.artist:
        return f"{source.artist} - {source.title}"
    return source.title


def _validate_source(source: AudioSource, settings: Settings) -> str | None:
    if source.is_live:
        return "Live streams are not supported for download."
    if (
        settings.max_audio_duration_sec > 0
        and source.duration_seconds
        and source.duration_seconds > settings.max_audio_duration_sec
    ):
        return (
            f"This track is too long for the current bot limits. "
            f"Maximum duration is {settings.max_audio_duration_sec // 60} minutes."
        )
    if settings.max_audio_size_mb > 0:
        max_size_bytes = settings.max_audio_size_mb * 1024 * 1024
    else:
        max_size_bytes = 0
    if max_size_bytes and source.estimated_size_bytes and source.estimated_size_bytes > max_size_bytes:
        return (
            f"This source looks too large before download starts. "
            f"Current limit is about {settings.max_audio_size_mb} MB."
        )
    return None


def _audio_cache_key(source_key: str, quality_preset: str, audio_format: str) -> str:
    return f"{source_key}|{quality_preset}|{audio_format}"


async def _deliver_cached_audio(
    message: Message,
    status_message: Message,
    db: Database,
    settings: Settings,
    *,
    query_token: str,
    query: str,
    source_key: str,
    cached_audio: dict[str, str | int],
    quality_preset: str,
    audio_format: str,
    source: AudioSource | None,
    user_id: int | None,
) -> bool:
    try:
        await message.answer_audio(
            audio=str(cached_audio["telegram_file_id"]),
            title=str(cached_audio["title"]),
            performer=str(cached_audio["performer"]) if cached_audio["performer"] else None,
            duration=int(cached_audio["duration_seconds"]) if cached_audio["duration_seconds"] else None,
            caption=_audio_delivery_caption(
                source,
                quality_preset,
                audio_format=audio_format,
                file_size_bytes=int(cached_audio["file_size_bytes"]) if cached_audio["file_size_bytes"] else None,
            ),
            reply_markup=download_actions_keyboard(query_token, settings.bot_username),
        )
        await db.log_download(
            chat_id=message.chat.id,
            query=query,
            source_key=source_key,
            title=str(cached_audio["title"]),
            performer=str(cached_audio["performer"]) if cached_audio["performer"] else None,
            status="cache",
            user_id=user_id,
        )
        await _safe_edit_text(
            status_message,
            f"Dropped fast from cache. <b>{escape(str(cached_audio['title']))}</b> is ready.",
            fallback_to_answer=True,
        )
        return True
    except TelegramBadRequest:
        return False


def _audio_delivery_caption(
    source: AudioSource | None,
    quality_preset: str,
    *,
    audio_format: str,
    file_size_bytes: int | None = None,
) -> str:
    quality_name = QUALITY_LABELS.get(quality_preset, quality_preset.title())
    size_value = file_size_bytes
    if size_value is None and source is not None:
        size_value = source.estimated_size_bytes
    size_text = _format_file_size(size_value)
    return (
        f"Quality: <b>{escape(quality_name)}</b> | "
        f"Format: <b>{escape(audio_format.upper())}</b> | "
        f"Size: <b>{escape(size_text)}</b>"
    )


def _display_source_name(extractor: str | None) -> str:
    if not extractor:
        return "Direct"
    lowered = extractor.casefold()
    if lowered == "youtube":
        return "YouTube"
    return extractor.replace("_", " ").title()


def _format_file_size(size_bytes: int | None) -> str:
    if not size_bytes or size_bytes <= 0:
        return "Unknown"
    units = ("B", "KB", "MB", "GB")
    value = float(size_bytes)
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.1f} {units[unit_index]}"


def _normalized_query_key(query: str) -> str:
    return " ".join(query.casefold().split())


async def _remember_query_cache_entries(
    db: Database,
    source_key: str,
    original_query: str,
    resolved_query: str,
    inferred_track: TrackResult | None,
) -> None:
    keys = {
        _normalized_query_key(original_query),
        _normalized_query_key(resolved_query),
    }
    if inferred_track is not None:
        keys.add(_normalized_query_key(_music_query_from_track(inferred_track)))
    for key in keys:
        if key:
            await db.upsert_query_source(key, source_key)


def _job_key(message: Message, user_id: int | None = None) -> str:
    if user_id is not None:
        return f"user:{user_id}"
    if message.from_user and not message.from_user.is_bot:
        return f"user:{message.from_user.id}"
    return f"chat:{message.chat.id}"


async def _safe_edit_text(
    message: Message,
    text: str,
    *,
    reply_markup: object | None = None,
    fallback_to_answer: bool = False,
) -> None:
    edit_markup = reply_markup if isinstance(reply_markup, InlineKeyboardMarkup) else None
    answer_markup = reply_markup if reply_markup is not None else main_menu_keyboard(message.chat.type)
    try:
        await message.edit_text(text, reply_markup=edit_markup)
    except TelegramBadRequest as exc:
        lowered = str(exc).lower()
        if "message is not modified" in lowered:
            return
        if fallback_to_answer:
            try:
                await message.answer(text, reply_markup=answer_markup)
            except TelegramBadRequest:
                return
        return


def _extract_group_query(message: Message, text: str, bot_username: str | None) -> str | None:
    if _is_reply_to_bot(message):
        return text.strip()

    if not bot_username:
        return None

    mention = f"@{bot_username.lower()}"
    filtered: list[str] = []
    found_mention = False
    for piece in text.split():
        if piece.strip(" ,:-").lower() == mention:
            found_mention = True
            continue
        filtered.append(piece)

    if not found_mention:
        return None

    cleaned = " ".join(filtered).strip(" ,:-")
    return cleaned or None


def _is_reply_to_bot(message: Message) -> bool:
    reply = message.reply_to_message
    if not reply or not reply.from_user:
        return False
    return bool(reply.from_user.is_bot and reply.from_user.id == message.bot.id)
