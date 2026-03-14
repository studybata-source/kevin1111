from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, limit: int, window_seconds: float) -> None:
        self._limit = max(1, limit)
        self._window_seconds = max(1.0, window_seconds)
        self._buckets: dict[int, deque[float]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, object]], Awaitable[object]],
        event: TelegramObject,
        data: dict[str, object],
    ) -> object:
        user = data.get("event_from_user")
        if user is None or not hasattr(user, "id"):
            return await handler(event, data)

        user_id = int(getattr(user, "id"))
        now = time.monotonic()
        bucket = self._buckets.setdefault(user_id, deque())
        while bucket and now - bucket[0] > self._window_seconds:
            bucket.popleft()

        if len(bucket) >= self._limit:
            if isinstance(event, Message):
                await event.answer("Too many requests. Slow down for a few seconds and try again.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Too many requests. Try again in a few seconds.", show_alert=True)
            return None

        bucket.append(now)
        return await handler(event, data)
