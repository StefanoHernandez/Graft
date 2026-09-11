"""Exact-origin matching for the public chat endpoint.

No wildcards, no suffix matching: `https://example.test.evil.com` must not pass a
check written for `https://example.test`. A missing or `null` Origin is refused —
a sandboxed iframe sends `null`, and there is no bot that can be.

This is a browser rule, not authentication. Anything outside a browser can send
whatever Origin it likes, so this limits which *pages* can spend a bot's quota,
and must never be described as protection from determined callers.
"""
from __future__ import annotations

from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_origin(origin: str | None) -> str | None:
    """Reduce an Origin header to `scheme://host[:port]`, or None if unusable."""
    if not origin:
        return None
    candidate = origin.strip().rstrip("/")
    if not candidate or candidate == "null":
        return None
    parts = urlsplit(candidate)
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
        return None
    host = parts.hostname.lower()
    try:
        port = parts.port
    except ValueError:
        return None
    if port is None or port == _DEFAULT_PORTS[parts.scheme]:
        return f"{parts.scheme}://{host}"
    return f"{parts.scheme}://{host}:{port}"


def origin_allowed(origin: str | None, allowed: list[str]) -> bool:
    normalized = normalize_origin(origin)
    if normalized is None:
        return False
    return normalized in {normalize_origin(entry) for entry in allowed}
