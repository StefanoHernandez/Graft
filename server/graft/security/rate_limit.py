"""Redis limits for the public chat endpoint.

Both primitives are Lua, so the check and the write are one step. A read followed
by a write loses exactly when it matters: two visitors arriving in the same
millisecond is the normal case for a public endpoint.

Callers must treat a Redis outage as a refusal (fail closed). A chat request that
proceeds without a limit is a request that can spend a bot's provider budget
without a ceiling.
"""
from __future__ import annotations

from redis.asyncio import Redis

# INCR creates the key at 1; the expiry is attached on that first hit, so a
# window starts when its first request arrives.
_RATE = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
if count > tonumber(ARGV[1]) then
  return 0
end
return 1
"""

# A sorted set of live tokens scored by their expiry. Expired entries are dropped
# on every call, so a caller that died mid-generation frees its slot by itself
# instead of holding it forever.
_SLOT = """
local now = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZSCORE', KEYS[1], ARGV[4]) == false then
  if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
    return 0
  end
end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[3]), ARGV[4])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]) + 60)
return 1
"""


async def check_rate(redis: Redis, key: str, *, limit: int, window: int) -> bool:
    """Count one request against a fixed window. False means refuse it."""
    allowed = await redis.eval(_RATE, 1, key, limit, window)
    return bool(allowed)


async def acquire_slot(redis: Redis, key: str, *, limit: int, ttl: int, token: str) -> bool:
    """Take one of `limit` concurrent slots. Re-acquiring with the same token is a renew."""
    now = await _now(redis)
    taken = await redis.eval(_SLOT, 1, key, now, limit, ttl, token)
    return bool(taken)


async def release_slot(redis: Redis, key: str, token: str) -> None:
    """Give a slot back. Releasing a token you do not hold does nothing."""
    await redis.zrem(key, token)


async def _now(redis: Redis) -> float:
    """Redis time, not the caller's: several app processes must agree on expiry."""
    seconds, microseconds = await redis.time()
    return seconds + microseconds / 1_000_000
