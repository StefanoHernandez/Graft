"""The heartbeat must not outlive the visitor.

While `_with_heartbeat` is parked on a keep-alive it holds a pending read of the
answer stream. If the visitor leaves and that read is never cancelled, the task
dangles and `_stream`'s finally — the one that gives the Redis slots back — does
not run until the slot TTL expires.
"""
from __future__ import annotations

import asyncio

from graft.api import chat


async def test_leaving_mid_keepalive_closes_the_answer_stream(monkeypatch):
    monkeypatch.setattr(chat, "HEARTBEAT_SECONDS", 0.01)
    closed: list[str] = []

    async def never_answers():
        try:
            await asyncio.sleep(3600)  # a model that is still thinking
            yield b"unreachable"
        finally:
            closed.append("released")

    wrapped = chat._with_heartbeat(never_answers())
    assert await wrapped.__anext__() == b": keep-alive\n\n"

    await wrapped.aclose()  # the visitor closed the tab
    await asyncio.sleep(0.05)  # let the cancellation land

    assert closed == ["released"]
