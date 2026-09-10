from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

SOURCE_NAME = "source"


def _document_dir(root: Path, bot_id: uuid.UUID | str, document_id: uuid.UUID | str) -> Path:
    return Path(root) / str(bot_id) / str(document_id)


def _resolved(root: Path, storage_key: str) -> Path:
    """Resolve a storage key inside the root, or refuse it.

    A storage_key comes back from the database, so it is untrusted input even
    though we wrote it: one bad row must not turn a read into an arbitrary file
    read, or a delete into an arbitrary unlink.
    """
    root = Path(root).resolve()
    target = (root / storage_key).resolve()
    if target != root and root not in target.parents:
        raise ValueError("storage key escapes the storage root")
    return target


def save_source(
    root: Path, bot_id: uuid.UUID | str, document_id: uuid.UUID | str, data: bytes
) -> str:
    """Store an original under ids only and return its storage key.

    The uploaded filename never reaches the path — it is metadata. The write goes
    to a temp file in the same directory and is then renamed, so a crash mid-write
    leaves no half file that a worker would happily parse.
    """
    directory = _document_dir(root, bot_id, document_id)
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".{SOURCE_NAME}.{uuid.uuid4().hex}.part"
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, directory / SOURCE_NAME)
    finally:
        tmp.unlink(missing_ok=True)
    return f"{bot_id}/{document_id}/{SOURCE_NAME}"


def read_source(root: Path, storage_key: str) -> bytes:
    return _resolved(root, storage_key).read_bytes()


def delete_source(root: Path, storage_key: str) -> None:
    """Remove an original and its document directory. Safe to call twice."""
    target = _resolved(root, storage_key)
    target.unlink(missing_ok=True)
    parent = target.parent
    if parent != Path(root).resolve() and parent.exists():
        shutil.rmtree(parent, ignore_errors=True)
