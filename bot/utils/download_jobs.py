from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class ActiveDownloadJob:
    key: str
    query: str
    started_at: float = field(default_factory=time.monotonic)
    cancel_event: threading.Event = field(default_factory=threading.Event)


class DownloadJobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, ActiveDownloadJob] = {}
        self._lock = asyncio.Lock()

    async def start(self, key: str, query: str) -> ActiveDownloadJob | None:
        async with self._lock:
            if key in self._jobs:
                return None
            job = ActiveDownloadJob(key=key, query=query)
            self._jobs[key] = job
            return job

    async def get(self, key: str) -> ActiveDownloadJob | None:
        async with self._lock:
            return self._jobs.get(key)

    async def cancel(self, key: str) -> bool:
        async with self._lock:
            job = self._jobs.get(key)
            if not job:
                return False
            job.cancel_event.set()
            return True

    async def finish(self, key: str) -> None:
        async with self._lock:
            self._jobs.pop(key, None)


class SharedWorkRegistry:
    def __init__(
        self,
        redis_url: str | None = None,
        *,
        lease_seconds: int = 900,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self._work: dict[str, asyncio.Future[None]] = {}
        self._lock = asyncio.Lock()
        self._lease_seconds = max(30, lease_seconds)
        self._poll_interval_seconds = max(0.1, poll_interval_seconds)
        self._redis = None
        if redis_url:
            try:
                from redis.asyncio import from_url
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError("REDIS_URL is set, but the 'redis' package is not installed.") from exc
            self._redis = from_url(redis_url, decode_responses=True)

    async def claim(self, key: str) -> tuple[bool, asyncio.Future[None]]:
        if self._redis is not None:
            return await self._claim_distributed(key)

        loop = asyncio.get_running_loop()
        async with self._lock:
            future = self._work.get(key)
            if future is None:
                future = loop.create_future()
                future.add_done_callback(_consume_future_exception)
                self._work[key] = future
                return True, future
            return False, future

    async def finish(self, key: str, error: BaseException | None = None) -> None:
        if self._redis is not None:
            await self._finish_distributed(key, error)
            return

        async with self._lock:
            future = self._work.pop(key, None)
        if future is None or future.done():
            return
        if error is None:
            future.set_result(None)
            return
        future.set_exception(error)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()

    async def _claim_distributed(self, key: str) -> tuple[bool, asyncio.Future[None]]:
        lease_key = self._lease_key(key)
        error_key = self._error_key(key)
        acquired = await self._redis.set(lease_key, "1", ex=self._lease_seconds, nx=True)
        if acquired:
            await self._redis.delete(error_key)
            future = asyncio.get_running_loop().create_future()
            future.set_result(None)
            return True, future

        future = asyncio.create_task(self._wait_for_distributed_release(key))
        future.add_done_callback(_consume_future_exception)
        return False, future

    async def _finish_distributed(self, key: str, error: BaseException | None = None) -> None:
        lease_key = self._lease_key(key)
        error_key = self._error_key(key)
        if error is None:
            await self._redis.delete(error_key)
        else:
            await self._redis.set(error_key, str(error), ex=min(self._lease_seconds, 300))
        await self._redis.delete(lease_key)

    async def _wait_for_distributed_release(self, key: str) -> None:
        lease_key = self._lease_key(key)
        error_key = self._error_key(key)
        while True:
            error_message = await self._redis.get(error_key)
            if error_message:
                raise RuntimeError(str(error_message))

            if not await self._redis.exists(lease_key):
                return

            await asyncio.sleep(self._poll_interval_seconds)

    def _lease_key(self, key: str) -> str:
        return f"kevin11:shared-work:lease:{key}"

    def _error_key(self, key: str) -> str:
        return f"kevin11:shared-work:error:{key}"


def _consume_future_exception(future: asyncio.Future[object]) -> None:
    if future.cancelled():
        return
    try:
        future.exception()
    except asyncio.CancelledError:
        return
