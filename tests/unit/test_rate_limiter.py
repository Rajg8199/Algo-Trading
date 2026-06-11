import time

from tp_upstox.rest import RateLimiter


async def test_rate_limiter_enforces_budget() -> None:
    limiter = RateLimiter(rate=10)
    start = time.monotonic()
    for _ in range(15):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    # 10 burst tokens free, remaining 5 at 10/s -> >= ~0.4s
    assert elapsed >= 0.35


async def test_rate_limiter_allows_burst() -> None:
    limiter = RateLimiter(rate=50)
    start = time.monotonic()
    for _ in range(20):
        await limiter.acquire()
    assert time.monotonic() - start < 0.2
