from __future__ import annotations

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    ChatAdministratorRights,
)

from bot.constants import COMMANDS, OWNER_COMMANDS


def public_bot_commands() -> list[BotCommand]:
    return [BotCommand(command=name, description=description) for name, description in COMMANDS]


def private_bot_commands() -> list[BotCommand]:
    commands = [
        ("start", "Start the bot"),
        ("help", "Show help"),
        ("settings", "Personal audio settings"),
        ("search", "Show song matches"),
        ("song", "Fetch the track directly"),
        ("download", "Fetch from a song name or link"),
        ("lyrics", "Show lyrics for a song"),
        ("history", "Show recent searches"),
        ("cancel", "Cancel the current flow"),
    ]
    return [BotCommand(command=name, description=description) for name, description in commands]


def group_bot_commands() -> list[BotCommand]:
    commands = [
        ("help", "Show group usage"),
        ("song", "Fetch a track"),
        ("download", "Fetch from text or link"),
        ("search", "Show track choices"),
        ("lyrics", "Show lyrics"),
        ("cancel", "Cancel the current flow"),
    ]
    return [BotCommand(command=name, description=description) for name, description in commands]


def owner_bot_commands() -> list[BotCommand]:
    combined = COMMANDS + OWNER_COMMANDS
    return [BotCommand(command=name, description=description) for name, description in combined]


async def apply_public_command_scopes(bot: Bot) -> None:
    await bot.set_my_commands(private_bot_commands(), scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(group_bot_commands(), scope=BotCommandScopeAllGroupChats())


async def apply_owner_command_scope(bot: Bot, owner_user_id: int) -> None:
    await bot.set_my_commands(
        owner_bot_commands(),
        scope=BotCommandScopeChat(chat_id=owner_user_id),
    )


def group_admin_rights() -> ChatAdministratorRights:
    return ChatAdministratorRights(
        is_anonymous=False,
        can_manage_chat=True,
        can_delete_messages=True,
        can_manage_video_chats=True,
        can_restrict_members=False,
        can_promote_members=False,
        can_change_info=True,
        can_invite_users=True,
        can_post_stories=False,
        can_edit_stories=False,
        can_delete_stories=False,
        can_post_messages=False,
        can_edit_messages=False,
        can_pin_messages=True,
        can_manage_topics=True,
        can_manage_direct_messages=False,
        can_manage_tags=False,
    )


def channel_admin_rights() -> ChatAdministratorRights:
    return ChatAdministratorRights(
        is_anonymous=False,
        can_manage_chat=True,
        can_delete_messages=True,
        can_manage_video_chats=True,
        can_restrict_members=False,
        can_promote_members=False,
        can_change_info=True,
        can_invite_users=True,
        can_post_stories=False,
        can_edit_stories=False,
        can_delete_stories=False,
        can_post_messages=True,
        can_edit_messages=True,
        can_manage_direct_messages=False,
    )


async def apply_group_admin_rights(bot: Bot) -> None:
    await bot.set_my_default_administrator_rights(
        group_admin_rights(),
        for_channels=False,
    )


async def apply_channel_admin_rights(bot: Bot) -> None:
    await bot.set_my_default_administrator_rights(
        channel_admin_rights(),
        for_channels=True,
    )
