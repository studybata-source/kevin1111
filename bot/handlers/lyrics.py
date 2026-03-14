from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.constants import BUTTON_LYRICS
from bot.database.repository import Database
from bot.keyboards.inline import lyrics_actions_keyboard
from bot.keyboards.reply import main_menu_keyboard
from bot.services.downloader import ResolveTimeoutError, YtDlpAudioService
from bot.services.lyrics import LrclibLyricsService
from bot.services.metadata import MetadataSearchService
from bot.services.models import TrackResult
from bot.states import LyricsStates
from bot.utils.cache import SearchSessionStore
from bot.utils.formatting import format_lyrics
from bot.utils.users import remember_callback_context, remember_message_context


router = Router(name="lyrics")


@router.message(Command("lyrics"))
@router.message(F.text == BUTTON_LYRICS)
async def handle_lyrics_command(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    db: Database,
    settings: Settings,
    metadata: MetadataSearchService,
    lyrics: LrclibLyricsService,
    downloader: YtDlpAudioService,
    search_cache: SearchSessionStore,
) -> None:
    await remember_message_context(db, message)
    query = (command.args or "").strip() if command.args else ""
    if not query and message.text == BUTTON_LYRICS:
        query = ""
    if not query:
        await state.set_state(LyricsStates.waiting_for_query)
        await message.answer(
            "Send the song name or artist to fetch lyrics.",
            reply_markup=main_menu_keyboard(message.chat.type),
        )
        return

    await state.clear()
    await _handle_lyrics_request(message, query, settings, metadata, lyrics, downloader, search_cache)


@router.message(StateFilter(LyricsStates.waiting_for_query), F.text)
async def handle_waiting_lyrics_query(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
    metadata: MetadataSearchService,
    lyrics: LrclibLyricsService,
    downloader: YtDlpAudioService,
    search_cache: SearchSessionStore,
) -> None:
    await remember_message_context(db, message)
    await state.clear()
    await _handle_lyrics_request(message, message.text.strip(), settings, metadata, lyrics, downloader, search_cache)


@router.callback_query(F.data.startswith("search:lyrics:"))
async def handle_search_lyrics_callback(
    callback: CallbackQuery,
    db: Database,
    settings: Settings,
    metadata: MetadataSearchService,
    lyrics: LrclibLyricsService,
    downloader: YtDlpAudioService,
    search_cache: SearchSessionStore,
) -> None:
    if not callback.data:
        return
    await remember_callback_context(db, callback)
    await callback.answer()

    parts = callback.data.split(":")
    if len(parts) != 4:
        return
    token = parts[2]
    try:
        index = int(parts[3])
    except ValueError:
        return

    search_results = await search_cache.get_results(token)
    if search_results is None or index < 0 or index >= len(search_results.tracks):
        if isinstance(callback.message, Message):
            await callback.message.answer("That search result expired. Run /search again.")
        return

    track = search_results.tracks[index]
    callback_message = callback.message if isinstance(callback.message, Message) else None
    if callback_message is not None:
        await _send_lyrics_for_track(callback_message, track, settings, lyrics, search_cache, downloader)


@router.callback_query(F.data.startswith("query:lyrics:"))
async def handle_query_lyrics_callback(
    callback: CallbackQuery,
    db: Database,
    settings: Settings,
    metadata: MetadataSearchService,
    lyrics: LrclibLyricsService,
    downloader: YtDlpAudioService,
    search_cache: SearchSessionStore,
) -> None:
    if not callback.data:
        return
    await remember_callback_context(db, callback)
    await callback.answer()

    token = callback.data.rsplit(":", 1)[-1]
    query = await search_cache.get_query(token)
    if not query:
        if isinstance(callback.message, Message):
            await callback.message.answer("That saved query expired. Send the song name again.")
        return

    callback_message = callback.message if isinstance(callback.message, Message) else None
    if callback_message is not None:
        await _handle_lyrics_request(callback_message, query, settings, metadata, lyrics, downloader, search_cache)


async def _handle_lyrics_request(
    message: Message,
    query: str,
    settings: Settings,
    metadata: MetadataSearchService,
    lyrics: LrclibLyricsService,
    downloader: YtDlpAudioService,
    search_cache: SearchSessionStore,
) -> None:
    query = query.strip()
    if not query:
        await message.answer("Send a real song name or artist.", reply_markup=main_menu_keyboard(message.chat.type))
        return

    status_message = await message.answer("Reading the lines...", reply_markup=main_menu_keyboard(message.chat.type))
    track = await _resolve_track(query, metadata, downloader)
    if track is not None:
        result = await lyrics.find_lyrics(track.title, track.artist, query_text=query)
        if result is None:
            result = await lyrics.find_lyrics(track.title, query_text=query)
    else:
        result = await lyrics.find_lyrics(query, query_text=query)

    if result is None:
        await _safe_edit_or_answer(
            status_message,
            "Couldn't lock the right lyrics for that one.",
            reply_markup=main_menu_keyboard(message.chat.type),
        )
        return

    followup_query = query
    if track is not None:
        followup_query = f"{track.artist} - {track.title}"

    query_token = await search_cache.put_query(followup_query)
    await _safe_edit_or_answer(
        status_message,
        format_lyrics(result),
        reply_markup=lyrics_actions_keyboard(query_token, settings.bot_username),
    )


async def _send_lyrics_for_track(
    message: Message,
    track: TrackResult,
    settings: Settings,
    lyrics: LrclibLyricsService,
    search_cache: SearchSessionStore,
    downloader: YtDlpAudioService,
) -> None:
    result = await lyrics.find_lyrics(track.title, track.artist, query_text=f"{track.artist} {track.title}")
    if result is None:
        fallback_query = f"{track.artist} - {track.title}"
        try:
            source = await downloader.resolve_query(fallback_query)
        except ResolveTimeoutError:
            source = None
        if source is not None:
            result = await lyrics.find_lyrics(source.title, source.artist, query_text=fallback_query)
    if result is None:
        await message.answer("Couldn't lock the right lyrics for that result.", reply_markup=main_menu_keyboard(message.chat.type))
        return

    query_token = await search_cache.put_query(f"{track.artist} - {track.title}")
    await message.answer(
        format_lyrics(result),
        reply_markup=lyrics_actions_keyboard(query_token, settings.bot_username),
    )


async def _resolve_track(
    query: str,
    metadata: MetadataSearchService,
    downloader: YtDlpAudioService,
) -> TrackResult | None:
    tracks = await metadata.search_tracks(query, limit=1)
    if tracks:
        return tracks[0]

    try:
        source = await downloader.resolve_query(query)
    except ResolveTimeoutError:
        source = None
    if source is None:
        return None

    return TrackResult(
        source="yt_dlp",
        provider_id=source.source_key,
        title=source.title,
        artist=source.artist or "Unknown artist",
        album=source.album,
        duration_seconds=source.duration_seconds,
        external_url=source.webpage_url,
        preview_url=None,
        artwork_url=source.thumbnail_url,
        genre=None,
    )


async def _safe_edit_or_answer(message: Message, text: str, reply_markup: object | None = None) -> None:
    edit_markup = reply_markup if isinstance(reply_markup, InlineKeyboardMarkup) else None
    answer_markup = reply_markup if reply_markup is not None else main_menu_keyboard(message.chat.type)
    try:
        await message.edit_text(text, reply_markup=edit_markup)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=answer_markup)
