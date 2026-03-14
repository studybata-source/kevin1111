from __future__ import annotations

import asyncio
import logging

from aiohttp import ClientSession, web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonCommands

from bot.config import Settings
from bot.database.repository import Database
from bot.handlers import register_routers
from bot.logging_setup import configure_logging
from bot.middlewares import RateLimitMiddleware
from bot.services.downloader import YtDlpAudioService
from bot.services.metadata import MetadataSearchService
from bot.services.itunes import ItunesSearchService
from bot.services.lyrics import LrclibLyricsService
from bot.utils.bot_commands import (
    apply_channel_admin_rights,
    apply_group_admin_rights,
    apply_owner_command_scope,
    apply_public_command_scopes,
    public_bot_commands,
)
from bot.utils.cache import SearchSessionStore
from bot.utils.download_jobs import DownloadJobRegistry, SharedWorkRegistry
from bot.utils.users import resolved_owner_user_id


LOGGER = logging.getLogger(__name__)


async def run() -> None:
    settings = Settings()
    configure_logging(
        settings.log_level,
        log_to_file=settings.log_to_file,
        bot_token=settings.bot_token,
        ops_chat_id=settings.ops_chat_id,
        ops_alert_level=settings.ops_alert_level,
    )
    settings.ensure_directories()
    if not settings.bot_token:
        raise RuntimeError(
            "BOT_TOKEN is required for Telegram mode. "
            "Launch the terminal app with `python -m bot`, or set BOT_TOKEN and run `python -m bot telegram`."
        )

    database_target = settings.database_url or settings.database_path
    database = Database(
        database_target,
        default_quality_preset=settings.default_quality_preset,
        default_audio_format=settings.default_audio_format,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout_sec=settings.database_pool_timeout_sec,
    )
    await database.connect()
    await database.initialize()

    session = ClientSession()
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=_build_storage(settings))
    rate_limit = RateLimitMiddleware(
        limit=settings.message_rate_limit_count,
        window_seconds=settings.message_rate_limit_window_sec,
    )
    dispatcher.message.middleware(rate_limit)
    dispatcher.callback_query.middleware(rate_limit)
    dispatcher.channel_post.middleware(rate_limit)

    downloader = YtDlpAudioService(
        settings.download_dir,
        max_concurrent_resolves=settings.resolve_concurrency,
        max_concurrent_downloads=settings.download_concurrency,
        resolve_cache_ttl_seconds=settings.resolve_cache_ttl_sec,
        resolve_timeout_seconds=settings.resolve_timeout_sec,
        resolve_attempt_timeout_seconds=settings.resolve_attempt_timeout_sec,
    )
    await downloader.cleanup_stale_jobs(settings.cleanup_max_age_hours)

    dispatcher["settings"] = settings
    dispatcher["db"] = database
    dispatcher["metadata"] = MetadataSearchService(
        session,
        timeout_seconds=settings.search_timeout_sec,
        country_code=settings.search_country,
        cache_ttl_seconds=settings.metadata_cache_ttl_sec,
    )
    dispatcher["itunes"] = ItunesSearchService(
        session,
        timeout_seconds=settings.search_timeout_sec,
        country_code=settings.search_country,
    )
    dispatcher["lyrics"] = LrclibLyricsService(session, timeout_seconds=settings.search_timeout_sec)
    dispatcher["downloader"] = downloader
    dispatcher["search_cache"] = SearchSessionStore(db=database)
    dispatcher["download_jobs"] = DownloadJobRegistry()
    shared_downloads = SharedWorkRegistry(
        settings.redis_url,
        lease_seconds=int(settings.download_timeout_sec) + 60,
    )
    dispatcher["shared_downloads"] = shared_downloads

    register_routers(dispatcher)

    LOGGER.info("ffmpeg available: %s", "yes" if downloader.ffmpeg_available else "no")
    _log_production_warnings(settings)

    await configure_bot(bot, settings, database)

    try:
        if settings.ops_chat_id:
            await _send_ops_alert(bot, settings.ops_chat_id, "Kevin 11 Music Bot is live.")
        if settings.run_mode == "webhook":
            LOGGER.info("Kevin 11 Music Bot is starting in webhook mode.")
            await _run_webhook(bot, dispatcher, settings)
        else:
            LOGGER.info("Kevin 11 Music Bot is starting in polling mode.")
            await bot.delete_webhook(drop_pending_updates=True)
            await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        LOGGER.info("Shutting down Kevin 11 Music Bot.")
        if settings.ops_chat_id:
            await _send_ops_alert(bot, settings.ops_chat_id, "Kevin 11 Music Bot stopped.")
        await downloader.close()
        await shared_downloads.close()
        await dispatcher.storage.close()
        await session.close()
        await database.close()
        await bot.session.close()


async def configure_bot(bot: Bot, settings: Settings, db: Database) -> None:
    await bot.set_my_commands(public_bot_commands())
    await apply_public_command_scopes(bot)
    await apply_group_admin_rights(bot)
    await apply_channel_admin_rights(bot)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    await bot.set_my_description(
        "No fluff. Type a song name or paste a link. Kevin 11 sends back the file with Max quality on by default."
    )
    await bot.set_my_short_description("Type a song. Get the file.")

    if settings.enable_admin_tools:
        owner_user_id = await resolved_owner_user_id(db, settings)
        if owner_user_id:
            await apply_owner_command_scope(bot, owner_user_id)


async def _send_ops_alert(bot: Bot, ops_chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=ops_chat_id, text=text)
    except Exception:
        LOGGER.warning("Failed to send Telegram ops alert.", exc_info=True)


def _build_storage(settings: Settings):
    if not settings.redis_url:
        return MemoryStorage()

    try:
        from aiogram.fsm.storage.redis import RedisStorage
    except ImportError as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError("REDIS_URL is set, but the 'redis' package is not installed.") from exc

    return RedisStorage.from_url(settings.redis_url)


def _log_production_warnings(settings: Settings) -> None:
    if settings.run_mode == "webhook" and not settings.database_url:
        LOGGER.warning("Webhook mode is running without DATABASE_URL. SQLite is not suitable for large-scale traffic.")
    if settings.run_mode == "webhook" and not settings.redis_url:
        LOGGER.warning("Webhook mode is running without REDIS_URL. FSM state will stay local to each worker.")


async def _run_webhook(bot: Bot, dispatcher: Dispatcher, settings: Settings) -> None:
    from aiogram.webhook.aiohttp_server import setup_application

    if not settings.webhook_base_url:
        raise RuntimeError("WEBHOOK_BASE_URL is required when RUN_MODE=webhook.")

    webhook_url = f"{settings.webhook_base_url.rstrip('/')}{settings.webhook_path}"
    app = web.Application()
    handler = _ManagedBotRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        secret_token=settings.webhook_secret_token,
    )
    handler.register(app, path=settings.webhook_path)
    setup_application(app, dispatcher, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.webhook_host, port=settings.webhook_port)
    await bot.set_webhook(
        webhook_url,
        secret_token=settings.webhook_secret_token,
        allowed_updates=dispatcher.resolve_used_update_types(),
        drop_pending_updates=True,
    )
    await site.start()
    LOGGER.info("Webhook listener is live on %s:%s%s", settings.webhook_host, settings.webhook_port, settings.webhook_path)

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


class _ManagedBotRequestHandler:
    def __init__(self, dispatcher: Dispatcher, bot: Bot, secret_token: str | None) -> None:
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler

        class _Handler(SimpleRequestHandler):
            async def close(self_inner) -> None:
                return None

        self._handler = _Handler(
            dispatcher=dispatcher,
            bot=bot,
            secret_token=secret_token,
            handle_in_background=True,
        )

    def register(self, app: web.Application, *, path: str) -> None:
        self._handler.register(app, path=path)
