from __future__ import annotations

from aiogram.types import CallbackQuery, Chat, Message, User

from bot.config import Settings
from bot.database.repository import Database


def display_name(user: User) -> str:
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part).strip()
    return full_name or user.username or "Operator"


async def remember_user(db: Database, user: User) -> None:
    await db.upsert_user(
        user_id=user.id,
        username=user.username,
        full_name=display_name(user),
        language_code=user.language_code,
    )


def chat_title(chat: Chat) -> str | None:
    if chat.title:
        return chat.title
    if getattr(chat, "full_name", None):
        return chat.full_name
    return None


async def remember_chat(db: Database, chat: Chat, is_active: bool = True) -> None:
    await db.upsert_chat(
        chat_id=chat.id,
        chat_type=chat.type,
        title=chat_title(chat),
        username=chat.username,
        is_active=is_active,
    )


async def remember_message_context(db: Database, message: Message) -> None:
    if message.from_user:
        await remember_user(db, message.from_user)
    await remember_chat(db, message.chat)


async def remember_callback_context(db: Database, callback: CallbackQuery) -> None:
    if callback.from_user:
        await remember_user(db, callback.from_user)
    if isinstance(callback.message, Message):
        await remember_chat(db, callback.message.chat)


async def resolved_owner_user_id(db: Database, settings: Settings) -> int | None:
    return settings.owner_user_id or await db.get_owner_user_id()


async def is_owner(db: Database, settings: Settings, user_id: int) -> bool:
    owner_id = await resolved_owner_user_id(db, settings)
    return owner_id == user_id
