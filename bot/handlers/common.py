from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from bot.config import Settings
from bot.constants import BUTTON_HELP, BUTTON_HISTORY, BUTTON_SETTINGS
from bot.database.repository import Database
from bot.keyboards.inline import settings_keyboard, welcome_shortcuts_keyboard
from bot.keyboards.reply import main_menu_keyboard
from bot.utils.download_jobs import DownloadJobRegistry
from bot.utils.formatting import format_history, format_settings
from bot.utils.users import display_name, remember_callback_context, remember_message_context


router = Router(name="common")


WELCOME_TEMPLATE = (
    "<b>Kevin 11 Music Bot</b>\n"
    "No fluff. Drop a song name. Get the file.\n"
    "Default setting: <b>Max quality</b>.\n\n"
    "<b>Quick use</b>\n"
    "- DM: just type the song name\n"
    "- Group: use /song track name\n"
    "- Group alt: make the bot admin, then plain text works too\n"
    "- Link mode: paste a supported link\n\n"
    "Want choices first? Use /search."
)

HELP_TEXT = (
    "<b>How to use Kevin 11</b>\n"
    "- DM: send a song name for direct audio\n"
    "- /song [query] - fastest direct fetch\n"
    "- /download [query or link] - direct fetch from text or link\n"
    "- /search [query] - show multiple track picks first\n"
    "- /lyrics [query] - get lyrics\n"
    "- /settings - open settings\n"
    "- /history - see recents\n"
    "- /cancel - stop the current flow\n\n"
    "<b>Group setup</b>\n"
    "- Add the bot to the group from its Telegram profile\n"
    "- Best setup: make the bot admin in the group\n"
    "- If the bot is admin, normal group text works much better\n"
    "- If the bot is not admin and privacy mode is ON, use /song, /download, mention the bot, or reply to the bot\n"
    "- If you want the bot to catch more plain group messages even without admin, disable privacy mode in BotFather with /setprivacy"
)

SEARCH_TIPS_TEXT = (
    "<b>Best flow</b>\n"
    "- Private chat: send the song name directly\n"
    "- Group: use /song track name for the cleanest flow\n"
    "- Group alt: make the bot admin, then normal text can work too\n"
    "- Mention the bot or reply to it if you do not want to use commands\n"
    "- Add the bot to the group from its Telegram profile, then promote it to admin if you want easier plain-text use\n"
    "- Use /search when you want button-based picks first\n"
    "- Default setting is Max quality"
)


@router.message(Command("start"))
async def handle_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not message.from_user:
        return

    await remember_message_context(db, message)
    await state.clear()

    if command.args == "kevin11":
        await message.answer(
            (
                "<b>Group setup ready.</b>\n"
                "Use /song track name for the fastest fetch.\n"
                "You can also mention the bot with the track name or reply to the bot with the track name."
            ),
            reply_markup=main_menu_keyboard(message.chat.type),
        )
    elif message.chat.type in {"group", "supergroup"}:
        await message.answer(
            (
                "<b>Group setup ready.</b>\n"
                "Best setup: make the bot admin for easier plain-text fetches.\n"
                "Fallback: use /song track name, mention the bot, or reply to it with the track name."
            ),
            reply_markup=main_menu_keyboard(message.chat.type),
        )

    await message.answer(
        WELCOME_TEMPLATE,
        reply_markup=main_menu_keyboard(message.chat.type),
    )
    await message.answer(
        f"Ready, <b>{display_name(message.from_user)}</b>. Drop the track name.",
        reply_markup=welcome_shortcuts_keyboard(settings.bot_username),
    )


@router.message(Command("help"))
@router.message(F.text == BUTTON_HELP)
async def handle_help(message: Message, db: Database) -> None:
    await remember_message_context(db, message)
    await message.answer(HELP_TEXT, reply_markup=main_menu_keyboard(message.chat.type))


@router.message(Command("history"))
@router.message(F.text == BUTTON_HISTORY)
async def handle_history(message: Message, db: Database) -> None:
    if not message.from_user:
        return
    await remember_message_context(db, message)
    rows = await db.get_recent_searches(message.from_user.id)
    await message.answer(format_history(rows), reply_markup=main_menu_keyboard(message.chat.type))


@router.message(Command("cancel"))
async def handle_cancel(
    message: Message,
    state: FSMContext,
    db: Database,
    download_jobs: DownloadJobRegistry,
) -> None:
    await remember_message_context(db, message)
    await state.clear()
    if message.from_user:
        cancelled = await download_jobs.cancel(f"user:{message.from_user.id}")
    else:
        cancelled = await download_jobs.cancel(f"chat:{message.chat.id}")

    text = "Current flow cleared. Send a fresh query whenever you are ready."
    if cancelled:
        text = "Active download cancellation requested. Send a fresh query when you are ready."
    await message.answer(text, reply_markup=main_menu_keyboard(message.chat.type))


@router.callback_query(F.data == "show:search_tips")
async def show_search_tips(callback: CallbackQuery, db: Database) -> None:
    await remember_callback_context(db, callback)
    await callback.answer()
    callback_message = callback.message if isinstance(callback.message, Message) else None
    if callback_message:
        await callback_message.answer(SEARCH_TIPS_TEXT, reply_markup=main_menu_keyboard(callback_message.chat.type))


@router.message(Command("settings"))
@router.message(F.text == BUTTON_SETTINGS)
async def show_settings_message(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    await remember_message_context(db, message)
    delivery_settings = await db.get_user_delivery_settings(message.from_user.id)
    await message.answer(
        format_settings(delivery_settings["quality_preset"], delivery_settings["audio_format"]),
        reply_markup=settings_keyboard(
            delivery_settings["quality_preset"],
            delivery_settings["audio_format"],
            settings.bot_username,
        ),
    )


@router.callback_query(F.data == "show:settings")
async def show_settings_callback(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.from_user:
        return
    await remember_callback_context(db, callback)
    delivery_settings = await db.get_user_delivery_settings(callback.from_user.id)
    await callback.answer()
    callback_message = callback.message if isinstance(callback.message, Message) else None
    if callback_message:
        await callback_message.answer(
            format_settings(delivery_settings["quality_preset"], delivery_settings["audio_format"]),
            reply_markup=settings_keyboard(
                delivery_settings["quality_preset"],
                delivery_settings["audio_format"],
                settings.bot_username,
            ),
        )


@router.my_chat_member()
async def track_membership(update: ChatMemberUpdated, db: Database) -> None:
    is_active = update.new_chat_member.status not in {"left", "kicked"}
    await db.upsert_chat(
        chat_id=update.chat.id,
        chat_type=update.chat.type,
        title=update.chat.title or getattr(update.chat, "full_name", None),
        username=update.chat.username,
        is_active=is_active,
    )
