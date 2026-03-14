import asyncio

from bot.middlewares.rate_limit import RateLimitMiddleware


async def _handler(_: object, __: dict[str, object]) -> str:
    return "ok"


class DummyUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


def test_rate_limit_blocks_after_limit() -> None:
    middleware = RateLimitMiddleware(limit=2, window_seconds=30)
    data = {"event_from_user": DummyUser(101)}

    assert asyncio.run(middleware(_handler, object(), data)) == "ok"
    assert asyncio.run(middleware(_handler, object(), data)) == "ok"
    assert asyncio.run(middleware(_handler, object(), data)) is None
