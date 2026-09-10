from __future__ import annotations

import hashlib
import json

from .config import EmbeddingConfig
from .factory import _OPENAI_COMPATIBLE_DEFAULTS

# The openai SDK's own default when no base_url is passed. Resolved explicitly here so
# an unset base_url and the same URL typed in by hand are one index, not two.
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _normalized_base_url(config: EmbeddingConfig) -> str:
    explicit = (config.base_url or "").strip()
    if explicit:
        return explicit.rstrip("/")
    default = _OPENAI_COMPATIBLE_DEFAULTS.get(config.provider) or OPENAI_DEFAULT_BASE_URL
    return default.rstrip("/")


def embedding_fingerprint(config: EmbeddingConfig) -> str:
    """Identify the vector space a bot's chunks live in.

    Two chunks are only comparable when provider, model and endpoint match, so the
    fingerprint covers exactly those. The API key is excluded: rotating a key must
    not orphan a corpus. Any future option that changes the vectors belongs here.

    It cannot see through a name: an endpoint that swaps the weights behind an
    unchanged model id produces the same fingerprint, so the operator must publish
    a new model identifier instead.
    """
    canonical = json.dumps(
        {
            "provider": config.provider,
            "model": config.model,
            "base_url": _normalized_base_url(config),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
