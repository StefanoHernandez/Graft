#!/usr/bin/env bash
set -e
# The venv binaries directly: nothing resolves, syncs or reaches the network at
# boot. A container that needs its package manager to start is a container that
# can fail to start for reasons that have nothing to do with this release.
/app/.venv/bin/alembic upgrade head
exec /app/.venv/bin/uvicorn graft.main:app --host 0.0.0.0 --port 8000
