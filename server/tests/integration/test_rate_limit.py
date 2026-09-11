"""Limits must hold under concurrency, which is why they are Lua, not read-then-write.

Two callers hitting the same counter at the same moment is the normal case for a
public endpoint, not an edge case.
"""
import asyncio

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from testcontainers.community.redis import RedisContainer

from graft.security.rate_limit import acquire_slot, check_rate, release_slot


@pytest.fixture(scope="module")
def redis_container():
    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        container.dsn = f"redis://{host}:{port}"
        yield container


@pytest_asyncio.fixture
async def redis(redis_container):
    client = Redis.from_url(redis_container.dsn)
    await client.flushall()
    yield client
    await client.aclose()


# --- counters ----------------------------------------------------------------


async def test_requests_up_to_the_limit_pass(redis):
    assert [await check_rate(redis, "k", limit=3, window=60) for _ in range(3)] == [True] * 3


async def test_the_request_over_the_limit_is_refused(redis):
    for _ in range(3):
        await check_rate(redis, "k", limit=3, window=60)
    assert await check_rate(redis, "k", limit=3, window=60) is False


async def test_counters_are_per_key(redis):
    await check_rate(redis, "bot:a", limit=1, window=60)
    assert await check_rate(redis, "bot:b", limit=1, window=60) is True


async def test_the_window_expires(redis):
    assert await check_rate(redis, "k", limit=1, window=1) is True
    assert await check_rate(redis, "k", limit=1, window=1) is False
    await asyncio.sleep(1.2)
    assert await check_rate(redis, "k", limit=1, window=1) is True


async def test_the_ttl_is_set_on_the_first_hit(redis):
    await check_rate(redis, "k", limit=5, window=60)
    assert 0 < await redis.ttl("k") <= 60


async def test_a_burst_never_exceeds_the_limit(redis):
    results = await asyncio.gather(
        *(check_rate(redis, "k", limit=5, window=60) for _ in range(20))
    )
    assert sum(results) == 5


# --- concurrency slots -------------------------------------------------------


async def test_slots_are_handed_out_up_to_the_limit(redis):
    assert await acquire_slot(redis, "gen", limit=2, ttl=30, token="a") is True
    assert await acquire_slot(redis, "gen", limit=2, ttl=30, token="b") is True
    assert await acquire_slot(redis, "gen", limit=2, ttl=30, token="c") is False


async def test_releasing_frees_a_slot(redis):
    await acquire_slot(redis, "gen", limit=1, ttl=30, token="a")
    assert await acquire_slot(redis, "gen", limit=1, ttl=30, token="b") is False
    await release_slot(redis, "gen", "a")
    assert await acquire_slot(redis, "gen", limit=1, ttl=30, token="b") is True


async def test_releasing_someone_elses_slot_does_nothing(redis):
    await acquire_slot(redis, "gen", limit=1, ttl=30, token="a")
    await release_slot(redis, "gen", "stranger")
    assert await acquire_slot(redis, "gen", limit=1, ttl=30, token="b") is False


async def test_an_abandoned_slot_expires_instead_of_leaking(redis):
    """A worker that dies mid-generation must not hold a slot forever."""
    assert await acquire_slot(redis, "gen", limit=1, ttl=1, token="dead") is True
    assert await acquire_slot(redis, "gen", limit=1, ttl=1, token="next") is False
    await asyncio.sleep(1.2)
    assert await acquire_slot(redis, "gen", limit=1, ttl=1, token="next") is True


async def test_reacquiring_with_the_same_token_does_not_double_count(redis):
    await acquire_slot(redis, "gen", limit=1, ttl=30, token="a")
    assert await acquire_slot(redis, "gen", limit=1, ttl=30, token="a") is True
    await release_slot(redis, "gen", "a")
    assert await acquire_slot(redis, "gen", limit=1, ttl=30, token="b") is True


async def test_a_burst_of_acquirers_never_oversubscribes(redis):
    results = await asyncio.gather(
        *(acquire_slot(redis, "gen", limit=2, ttl=30, token=f"t{i}") for i in range(10))
    )
    assert sum(results) == 2
