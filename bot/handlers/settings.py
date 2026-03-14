from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from bot.config import Settings
from bot.constants import QUALITY_LABELS
from bot.database.repository import Database
from bot.keyboards.inline import settings_keyboard
from bot.utils.formatting import format_settings
from bot.utils.users import remember_callback_context


router = Router(name="settings")
VALID_PRESETS = {"best", "balanced", "small"}


@router.callback_query(F.data.startswith("settings:quality:"))
async def set_quality(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.from_user:
        return

    preset = callback.data.rsplit(":", 1)[-1]
    if preset not in VALID_PRESETS:
        await callback.answer("Unknown quality preset.", show_alert=True)
        return
    await remember_callback_context(db, callback)
    await db.set_quality_preset(callback.from_user.id, preset)
    await callback.answer(f"Settings updated: {QUALITY_LABELS[preset]}.")

    if callback.message:
        delivery_settings = await db.get_user_delivery_settings(callback.from_user.id)
        try:
            await callback.message.edit_text(
                format_settings(delivery_settings["quality_preset"], delivery_settings["audio_format"]),
                reply_markup=settings_keyboard(
                    delivery_settings["quality_preset"],
                    delivery_settings["audio_format"],
                    settings.bot_username,
                ),
            )
        except TelegramBadRequest:
            await callback.message.answer(
                format_settings(delivery_settings["quality_preset"], delivery_settings["audio_format"]),
                reply_markup=settings_keyboard(
                    delivery_settings["quality_preset"],
                    delivery_settings["audio_format"],
                    settings.bot_username,
                ),
            )


@router.callback_query(F.data.startswith("settings:format:"))
async def set_audio_format(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.from_user:
        return

    await remember_callback_context(db, callback)
    await db.set_audio_format(callback.from_user.id, settings.default_audio_format)
    await callback.answer("Formats are off right now. Kevin 11 stays on MP3.")

    if callback.message:
        delivery_settings = await db.get_user_delivery_settings(callback.from_user.id)
        try:
            await callback.message.edit_text(
                format_settings(delivery_settings["quality_preset"], delivery_settings["audio_format"]),
                reply_markup=settings_keyboard(
                    delivery_settings["quality_preset"],
                    delivery_settings["audio_format"],
                    settings.bot_username,
                ),
            )
        except TelegramBadRequest:
            await callback.message.answer(
                format_settings(delivery_settings["quality_preset"], delivery_settings["audio_format"]),
                reply_markup=settings_keyboard(
                    delivery_settings["quality_preset"],
                    delivery_settings["audio_format"],
                    settings.bot_username,
                ),
            )
