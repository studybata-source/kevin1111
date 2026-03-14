from __future__ import annotations

import asyncio

from aiogram import F, Bot, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.config import Settings
from bot.database.repository import Database
from bot.keyboards.reply import main_menu_keyboard
from bot.states import AdminStates
from bot.utils.bot_commands import apply_owner_command_scope
from bot.utils.users import is_owner, remember_message_context, resolved_owner_user_id


router = Router(name="admin")


@router.message(Command("claim_owner"))
async def claim_owner(
    message: Message,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not message.from_user:
        return

    await remember_message_context(db, message)
    if not settings.enable_admin_tools:
        return

    if message.chat.type != "private":
        await message.answer("Claim ownership from a private chat with the bot.")
        return

    existing_owner = await resolved_owner_user_id(db, settings)
    if existing_owner and existing_owner != message.from_user.id:
        await message.answer("This bot already has an owner configured.")
        return

    await db.set_owner_user_id(message.from_user.id)
    await apply_owner_command_scope(bot, message.from_user.id)
    await message.answer(
        "Ownership claimed. You can now use /stats, /groups, /thischat, /broadcast, and /broadcast_groups.",
        reply_markup=main_menu_keyboard(message.chat.type),
    )


@router.message(Command("stats"))
async def show_stats(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return

    await remember_message_context(db, message)
    if not settings.enable_admin_tools:
        return
    if not await is_owner(db, settings, message.from_user.id):
        return

    stats = await db.get_stats()
    await message.answer(
        (
            "<b>Kevin 11 admin stats</b>\n"
            f"Known users: <b>{stats['users']}</b>\n"
            f"Active chats: <b>{stats['active_chats']}</b>\n"
            f"Groups tracked: <b>{stats['groups']}</b>\n"
            f"Searches logged: <b>{stats['searches']}</b>\n"
            f"Downloads logged: <b>{stats['downloads']}</b>"
        ),
        reply_markup=main_menu_keyboard(message.chat.type),
    )


@router.message(Command("groups"))
async def show_groups(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return

    await remember_message_context(db, message)
    if not settings.enable_admin_tools:
        return
    if not await is_owner(db, settings, message.from_user.id):
        return

    groups = await db.get_broadcast_targets(groups_only=True)
    if not groups:
        await message.answer("No groups tracked yet.", reply_markup=main_menu_keyboard(message.chat.type))
        return

    lines = ["<b>Tracked groups</b>"]
    for item in groups[:20]:
        title = item["title"] or item["username"] or str(item["chat_id"])
        lines.append(f"- {title} | <code>{item['chat_id']}</code>")
    await message.answer("\n".join(lines), reply_markup=main_menu_keyboard(message.chat.type))


@router.message(Command("thischat"))
async def show_current_chat(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return

    await remember_message_context(db, message)
    if not settings.enable_admin_tools:
        return
    if not await is_owner(db, settings, message.from_user.id):
        return

    title = message.chat.title or getattr(message.chat, "full_name", None) or "Untitled"
    username = f"@{message.chat.username}" if message.chat.username else "none"
    await message.answer(
        (
            "<b>Current chat</b>\n"
            f"Type: <b>{message.chat.type}</b>\n"
            f"Title: <b>{title}</b>\n"
            f"Chat ID: <code>{message.chat.id}</code>\n"
            f"Username: <b>{username}</b>"
        ),
        reply_markup=main_menu_keyboard(message.chat.type),
    )


@router.message(Command("broadcast"))
async def broadcast_all(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    await _start_or_run_broadcast(
        message=message,
        command=command,
        state=state,
        db=db,
        settings=settings,
        bot=bot,
        groups_only=False,
    )


@router.message(Command("broadcast_groups"))
async def broadcast_groups(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    await _start_or_run_broadcast(
        message=message,
        command=command,
        state=state,
        db=db,
        settings=settings,
        bot=bot,
        groups_only=True,
    )


@router.message(AdminStates.waiting_for_broadcast_all, F.text)
async def handle_waiting_broadcast_all(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    await _finish_waiting_broadcast(message, state, db, settings, bot, groups_only=False)


@router.message(AdminStates.waiting_for_broadcast_groups, F.text)
async def handle_waiting_broadcast_groups(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    await _finish_waiting_broadcast(message, state, db, settings, bot, groups_only=True)


async def _start_or_run_broadcast(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
    groups_only: bool,
) -> None:
    if not message.from_user:
        return

    await remember_message_context(db, message)
    if not settings.enable_admin_tools:
        return
    if not await is_owner(db, settings, message.from_user.id):
        return

    text = (command.args or "").strip()
    if not text:
        await state.set_state(
            AdminStates.waiting_for_broadcast_groups if groups_only else AdminStates.waiting_for_broadcast_all
        )
        scope = "all tracked groups" if groups_only else "all tracked chats"
        await message.answer(
            f"Send the broadcast text now. It will go to {scope}. /cancel will abort.",
            reply_markup=main_menu_keyboard(message.chat.type),
        )
        return

    await state.clear()
    await _run_broadcast(message, db, bot, text, groups_only=groups_only)


async def _finish_waiting_broadcast(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
    groups_only: bool,
) -> None:
    if not message.from_user:
        return

    await remember_message_context(db, message)
    if not settings.enable_admin_tools:
        await state.clear()
        return
    if not await is_owner(db, settings, message.from_user.id):
        await state.clear()
        return

    await state.clear()
    await _run_broadcast(message, db, bot, message.text.strip(), groups_only=groups_only)


async def _run_broadcast(
    message: Message,
    db: Database,
    bot: Bot,
    text: str,
    groups_only: bool,
) -> None:
    targets = await db.get_broadcast_targets(groups_only=groups_only)
    if not targets:
        await message.answer("No tracked broadcast targets yet.", reply_markup=main_menu_keyboard(message.chat.type))
        return

    sent = 0
    failed = 0
    deactivated = 0

    for target in targets:
        chat_id = int(target["chat_id"])
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=None)
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode=None)
                sent += 1
            except (TelegramForbiddenError, TelegramBadRequest):
                failed += 1
                await db.set_chat_active(chat_id, False)
                deactivated += 1
            except Exception:
                failed += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
            await db.set_chat_active(chat_id, False)
            deactivated += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.05)

    scope = "groups" if groups_only else "chats"
    await message.answer(
        (
            f"<b>Broadcast complete</b>\n"
            f"Scope: <b>{scope}</b>\n"
            f"Delivered: <b>{sent}</b>\n"
            f"Failed: <b>{failed}</b>\n"
            f"Deactivated unreachable chats: <b>{deactivated}</b>"
        ),
        reply_markup=main_menu_keyboard(message.chat.type),
    )
